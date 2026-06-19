"""InterestAggregationService — live, interest-driven fetching with TTL caching.

Pipeline per user visit (when cache is stale):
  1.  Derive search terms from skills + research_interests.
  2.  Fire all 4 sources in parallel: Adzuna, USAJobs, JSearch, Remotive.
  3.  basic_filter(): drop postings with no URL, empty description,
      clearly-senior roles (Director/VP/Manager without "intern"), duplicates.
  4.  llm_filter_postings(): send batches of 12 to LLM; keep only those the
      LLM confirms are (a) internship-level and (b) relevant to the user's
      fields of interest.  Falls back to title-based filter on LLM error.
  5.  Upsert survivors via AggregationService._upsert_one() (embedding included).
  6.  Re-score ghost signals, update cache row with 48-h TTL.

Cache key = SHA-256 of sorted canonical interests → shared across users with
identical profiles, so we never fetch the same interest bucket twice within TTL.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.interest_search_cache import InterestSearchCache
from app.sources.base import RawPosting

logger = logging.getLogger(__name__)

TTL_HOURS = 48


def _extract_int_array(text: str) -> list[int] | None:
    """Robustly extract a JSON integer array from LLM output."""
    for pattern in (r"\[[\d\s,]*\]", r"\[.*?\]"):
        m = re.search(pattern, text, re.DOTALL)
        if m:
            try:
                parsed = json.loads(m.group())
                if isinstance(parsed, list):
                    return [int(x) for x in parsed if isinstance(x, (int, float)) and int(x) == x]
            except (json.JSONDecodeError, ValueError):
                continue
    return None
MAX_TERMS = 5
ADZUNA_PAGES_PER_TERM = 2   # 100 results per term; stays inside 250/month free tier
LLM_BATCH_SIZE = 12          # postings per LLM call

_SKIP_SKILLS = {
    "git", "github", "linux", "bash", "http", "html", "css", "json", "xml",
    "rest", "powerpoint", "postman",
    "cursor", "n8n", "rest apis", "object-oriented programming", "oop",
    "data structures", "data structures & algorithms", "algorithms",
}

# Senior-level title words that disqualify a posting unless "intern" also appears.
# "lead" is handled separately via word-boundary regex to catch "team lead" endings.
_SENIOR_WORDS = {
    "senior", "sr.", "staff", "principal", "director", "vp", "vice president",
    "head of", "manager", "architect", "distinguished", "fellow", "executive",
}

_LEAD_RE = re.compile(r"\blead\b")


# ---------------------------------------------------------------------------
# Pure helpers — fingerprint + search-term extraction
# ---------------------------------------------------------------------------

def make_fingerprint(skills: list[str], research_interests: list[str]) -> str:
    """32-char SHA-256 of sorted canonical interests → shared cache key."""
    canonical = sorted(
        s.lower().strip() for s in (skills[:10] + research_interests) if s.strip()
    )
    return hashlib.sha256(",".join(canonical).encode()).hexdigest()[:32]


def extract_search_terms(skills: list[str], research_interests: list[str]) -> list[str]:
    """Derive up to MAX_TERMS meaningful search queries from a user's profile."""
    terms: list[str] = []

    for interest in research_interests[:3]:
        interest = interest.strip()
        if interest and len(interest) > 2:
            terms.append(f"{interest} internship")

    meaningful = [
        s for s in skills
        if s.lower().strip() not in _SKIP_SKILLS and len(s) > 2
    ]
    for skill in meaningful[: MAX_TERMS - len(terms)]:
        terms.append(f"{skill} internship")

    if not terms:
        terms = ["software engineering internship", "technology internship"]

    return terms[:MAX_TERMS]


# ---------------------------------------------------------------------------
# Pre-filter: fast, no LLM, cuts obviously irrelevant postings
# ---------------------------------------------------------------------------

def basic_filter(raws: list[RawPosting]) -> list[RawPosting]:
    """
    Drop postings that:
    - Have no source_url or empty title
    - Have a description shorter than 50 characters (after stripping HTML/whitespace)
    - Are clearly senior-level roles without 'intern' in the title
    Deduplicate by (lowercase title, lowercase company).
    """
    seen: set[tuple[str, str]] = set()
    kept: list[RawPosting] = []

    for raw in raws:
        title = str(raw.get("title") or "").strip()
        url = str(raw.get("source_url") or "").strip()
        company = str(raw.get("company_name") or "").strip()

        if not title or not url:
            continue
        if not url.startswith("http"):
            continue

        description = _strip_html(str(raw.get("description") or ""))
        if len(description) < 50:  # noqa: PLR2004
            continue

        title_lower = title.lower()
        is_intern = "intern" in title_lower
        if not is_intern and (
            any(w in title_lower for w in _SENIOR_WORDS)
            or bool(_LEAD_RE.search(title_lower))
        ):
            continue

        key = (title_lower, company.lower())
        if key in seen:
            continue
        seen.add(key)

        kept.append(raw)

    return kept


# ---------------------------------------------------------------------------
# LLM relevance gate
# ---------------------------------------------------------------------------

def _strip_html(text: str) -> str:
    import html as _html
    cleaned = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = _html.unescape(cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


async def llm_filter_postings(
    raws: list[RawPosting],
    skills: list[str],
    research_interests: list[str],
) -> list[RawPosting]:
    """
    Send batches of LLM_BATCH_SIZE postings to the LLM.
    Keep only those the LLM confirms are:
      (1) an internship / intern-level role
      (2) relevant to the user's skills + research interests
    Falls back to title-based filter ('intern' in title) on any LLM error.
    """
    from app.llm.router import complete

    interests_str = ", ".join((research_interests[:4] + skills[:6]))
    kept: list[RawPosting] = []

    for batch_start in range(0, len(raws), LLM_BATCH_SIZE):
        batch = raws[batch_start : batch_start + LLM_BATCH_SIZE]

        listing_lines = []
        for idx, raw in enumerate(batch):
            snippet = _strip_html(str(raw.get("description") or ""))[:150].replace("\n", " ")
            listing_lines.append(
                f"{idx}. {raw.get('title', '')} @ {raw.get('company_name', '?')} — {snippet}"
            )
        listing_text = "\n".join(listing_lines)

        prompt = (
            f"Interests: {interests_str}\n\n"
            f"Return indices of listings that are (1) internship-level AND (2) match interests.\n"
            f"Reply with JSON int array only. E.g. [0,2] or []\n\n"
            + listing_text
        )

        try:
            result = await complete(
                [
                    {
                        "role": "system",
                        "content": (
                            "Job relevance classifier. "
                            "Reply ONLY with a JSON array of integers. No explanation, no prose."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                max_tokens=80,
                temperature=0.0,
                prefer="fast",
            )

            indices = _extract_int_array(result or "")
            if indices is None:
                raise ValueError(f"no JSON array in LLM response: {result!r}")
            for idx in indices:
                if 0 <= idx < len(batch):
                    kept.append(batch[idx])

        except Exception as exc:  # noqa: BLE001
            logger.warning("llm_filter batch %d failed (%s) — falling back to title filter", batch_start, exc)
            for raw in batch:
                if "intern" in str(raw.get("title") or "").lower():
                    kept.append(raw)

    return kept


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class InterestAggregationService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def is_stale(self, fingerprint: str) -> bool:
        """True when cache is absent or past TTL."""
        row = (
            await self.db.execute(
                select(InterestSearchCache).where(
                    InterestSearchCache.fingerprint == fingerprint
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return True
        return row.expires_at < datetime.now(UTC)

    async def refresh(
        self,
        fingerprint: str,
        skills: list[str],
        research_interests: list[str],
    ) -> int:
        """
        Full pipeline: fetch → filter → llm-gate → upsert → cache.
        Returns number of net-new postings ingested.
        """
        from app.core.config import settings

        terms = extract_search_terms(skills, research_interests)
        logger.info("interest_refresh fp=%s terms=%s", fingerprint[:8], terms)

        # ── 1. Gather from all 4 sources in parallel ─────────────────────────
        adzuna_id   = getattr(settings, "ADZUNA_APP_ID",   "")
        adzuna_key  = getattr(settings, "ADZUNA_APP_KEY",  "")
        adzuna_ctry = getattr(settings, "ADZUNA_COUNTRY",  "us")
        usa_key     = getattr(settings, "USAJOBS_API_KEY", "")
        usa_email   = getattr(settings, "USAJOBS_EMAIL",   "")
        jsearch_key = getattr(settings, "JSEARCH_API_KEY", "")

        tasks: list[asyncio.Task[list[RawPosting]]] = []

        if adzuna_id and adzuna_key:
            for term in terms:
                tasks.append(asyncio.create_task(
                    _adzuna_search(term, adzuna_id, adzuna_key, adzuna_ctry)
                ))

        if usa_key and usa_email:
            for term in terms[:3]:
                tasks.append(asyncio.create_task(
                    _usajobs_search(term, usa_key, usa_email)
                ))

        if jsearch_key:
            for term in terms:
                tasks.append(asyncio.create_task(
                    _jsearch_search(term, jsearch_key)
                ))

        # Remotive is free / no auth — always included
        for term in terms[:3]:
            tasks.append(asyncio.create_task(_remotive_search(term)))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        raws: list[RawPosting] = []
        for r in results:
            if isinstance(r, list):
                raws.extend(r)
            elif isinstance(r, Exception):
                logger.warning("source_task_error: %s", r)

        logger.info("interest_refresh fp=%s raw=%d", fingerprint[:8], len(raws))

        # ── 2. Pre-filter ─────────────────────────────────────────────────────
        filtered = basic_filter(raws)
        logger.info("interest_refresh fp=%s after_basic=%d", fingerprint[:8], len(filtered))

        # ── 3. LLM relevance gate ─────────────────────────────────────────────
        relevant: list[RawPosting] = []
        if filtered:
            try:
                relevant = await llm_filter_postings(filtered, skills, research_interests)
            except Exception as exc:  # noqa: BLE001
                logger.warning("llm_filter_total_fail: %s — keeping title-filtered", exc)
                relevant = [r for r in filtered if "intern" in str(r.get("title") or "").lower()]

        logger.info("interest_refresh fp=%s after_llm=%d", fingerprint[:8], len(relevant))

        # ── 4. Upsert survivors ───────────────────────────────────────────────
        from app.services.aggregation_service import AggregationService
        from app.services.ghost_service import GhostService

        agg = AggregationService(self.db)
        ingested = 0
        for raw in relevant:
            try:
                duped = await agg._upsert_one(raw)
                if not duped:
                    ingested += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("upsert_failed title=%s err=%s", raw.get("title"), exc)
                await self.db.rollback()

        # ── 5. Ghost rescore ──────────────────────────────────────────────────
        await GhostService(self.db).rescore_all()

        # ── 6. Update cache ───────────────────────────────────────────────────
        now = datetime.now(UTC)
        existing = (
            await self.db.execute(
                select(InterestSearchCache).where(
                    InterestSearchCache.fingerprint == fingerprint
                )
            )
        ).scalar_one_or_none()

        if existing is not None:
            existing.search_terms = terms
            existing.last_fetched_at = now
            existing.expires_at = now + timedelta(hours=TTL_HOURS)
            existing.result_count = ingested
        else:
            self.db.add(InterestSearchCache(
                fingerprint=fingerprint,
                search_terms=terms,
                last_fetched_at=now,
                expires_at=now + timedelta(hours=TTL_HOURS),
                result_count=ingested,
            ))
        await self.db.commit()

        logger.info(
            "interest_refresh_done fp=%s raw=%d filtered=%d llm_passed=%d ingested=%d",
            fingerprint[:8], len(raws), len(filtered), len(relevant), ingested,
        )
        return ingested


# ---------------------------------------------------------------------------
# Background entry-point — owns its own DB session
# ---------------------------------------------------------------------------

async def refresh_interests_background(
    fingerprint: str,
    skills: list[str],
    research_interests: list[str],
) -> None:
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        try:
            svc = InterestAggregationService(db)
            await svc.refresh(fingerprint, skills, research_interests)
        except Exception as exc:  # noqa: BLE001
            logger.error("background_refresh_failed error=%s", exc)


# ---------------------------------------------------------------------------
# Source helpers — each accepts a custom search term
# ---------------------------------------------------------------------------

async def _adzuna_search(
    term: str,
    app_id: str,
    app_key: str,
    country: str,
) -> list[RawPosting]:
    from app.sources.adzuna import _parse_job as _parse

    results: list[RawPosting] = []
    base = f"https://api.adzuna.com/v1/api/jobs/{country}/search/{{page}}"

    async with httpx.AsyncClient(timeout=20.0) as client:
        for page in range(1, ADZUNA_PAGES_PER_TERM + 1):
            try:
                resp = await client.get(
                    base.format(page=page),
                    params={
                        "app_id": app_id,
                        "app_key": app_key,
                        "what": term,
                        "results_per_page": 50,
                        "content-type": "application/json",
                        "sort_by": "date",
                    },
                )
                if resp.status_code != 200:
                    break
                for job in resp.json().get("results") or []:
                    parsed = _parse(job)
                    if parsed:
                        results.append(parsed)
            except Exception as exc:  # noqa: BLE001
                logger.warning("adzuna term=%r page=%d err=%s", term, page, exc)
                break

    return results


async def _usajobs_search(term: str, api_key: str, email: str) -> list[RawPosting]:
    from app.sources.usajobs import _parse_job as _parse

    results: list[RawPosting] = []
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                "https://data.usajobs.gov/api/search",
                headers={
                    "Host": "data.usajobs.gov",
                    "User-Agent": email,
                    "Authorization-Key": api_key,
                },
                params={"Keyword": term, "NumberOfResults": 100, "Fields": "Minimum"},
            )
            if resp.status_code == 200:
                for item in (
                    resp.json().get("SearchResult", {}).get("SearchResultItems", [])
                ):
                    parsed = _parse(item)
                    if parsed:
                        results.append(parsed)
    except Exception as exc:  # noqa: BLE001
        logger.warning("usajobs term=%r err=%s", term, exc)

    return results


async def _jsearch_search(term: str, api_key: str) -> list[RawPosting]:
    from app.sources.jsearch import JSearchSource
    src = JSearchSource()
    try:
        return await src.fetch_by_term(term, api_key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("jsearch term=%r err=%s", term, exc)
        return []


async def _remotive_search(term: str) -> list[RawPosting]:
    results: list[RawPosting] = []
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                "https://remotive.com/api/remote-jobs",
                params={"search": term, "limit": 50},
            )
            if resp.status_code != 200:
                return results
            for job in resp.json().get("jobs") or []:
                title = str(job.get("title") or "").strip()
                url = str(job.get("url") or "").strip()
                if not title or not url:
                    continue
                description = re.sub(r"<[^>]+>", " ", str(job.get("description") or "")).strip()
                results.append({
                    "title": title,
                    "company_name": str(job.get("company_name") or ""),
                    "description": description,
                    "source": "remotive",
                    "source_url": url,
                    "location": str(job.get("candidate_required_location") or "Remote") or "Remote",
                    "work_mode": "remote",
                    "stipend": None,
                    "posted_at": str(job.get("publication_date") or "") or None,
                    "requirements": [],
                })
    except Exception as exc:  # noqa: BLE001
        logger.warning("remotive term=%r err=%s", term, exc)

    return results
