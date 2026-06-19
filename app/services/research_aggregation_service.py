"""ResearchAggregationService — live research internship fetching with TTL cache.

Same pipeline as InterestAggregationService but targets the research_opportunities
table and uses Mistral (open-mistral-7b) as the LLM relevance gate:

  1. Derive research-specific search terms from research_interests + skills.
  2. Fire Adzuna, USAJobs, JSearch in parallel.
  3. research_basic_filter(): drop no-URL, short descriptions, senior roles,
     postings with zero research signal.  Deduplicates by URL.
  4. mistral_filter_research(): Mistral classifies batches of 12 at a time;
     keeps only confirmed research internships / REUs relevant to user's work.
     Falls back to title-keyword filter on Mistral error.
  5. Map survivors → RawResearchOpportunity → upsert into research_opportunities
     table with embedding (so semantic matching in ResearchService still works).
  6. Update InterestSearchCache with "r_" prefixed fingerprint (72-h TTL,
     separate from the company-internship cache bucket).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from datetime import UTC, datetime, timedelta
from typing import TypedDict

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.embeddings import embed
from app.models.interest_search_cache import InterestSearchCache
from app.models.research_opportunity import ResearchOpportunity
from app.sources.base import RawPosting

logger = logging.getLogger(__name__)

TTL_HOURS = 72          # research postings change slower than company roles


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
MAX_TERMS = 8           # increased: synonym expansion yields more terms per interest
LLM_BATCH = 12          # postings per Mistral call — keeps token count bounded

# Job-board vocabulary is rarely "biotechnology research intern" — map academic
# interest labels to the terms that actually appear in listings.
_INTEREST_SYNONYMS: dict[str, list[str]] = {
    "biotechnology": ["biotech", "biology", "molecular biology", "life sciences", "biochemistry"],
    "microtechnology": ["nanotechnology", "MEMS", "semiconductor", "nanoscale engineering", "microsystems"],
    "microbiology": ["microbiology", "biology", "life sciences", "biotech"],
    "ai-ml": ["machine learning", "artificial intelligence", "deep learning", "NLP"],
    "ai": ["artificial intelligence", "machine learning", "deep learning"],
    "machine learning": ["machine learning", "deep learning", "NLP", "computer vision"],
    "deep learning": ["deep learning", "neural network", "computer vision", "ML"],
    "nlp": ["natural language processing", "NLP", "computational linguistics"],
    "computer vision": ["computer vision", "image recognition", "CV research"],
    "data science": ["data science", "machine learning", "statistical analysis"],
    "neuroscience": ["neuroscience", "computational neuroscience", "brain research"],
    "quantum computing": ["quantum computing", "quantum information", "quantum algorithm"],
    "robotics": ["robotics", "autonomous systems", "robot", "control systems"],
    "climate": ["climate science", "environmental science", "sustainability research"],
    "materials science": ["materials science", "materials engineering", "nanomaterials"],
    "bioinformatics": ["bioinformatics", "computational biology", "genomics"],
    "genomics": ["genomics", "bioinformatics", "computational biology"],
    "chemistry": ["chemistry", "organic chemistry", "chemical engineering"],
    "physics": ["physics", "computational physics", "applied physics"],
    "mathematics": ["mathematics", "applied math", "computational math"],
    "cybersecurity": ["cybersecurity", "information security", "network security"],
    "systems biology": ["systems biology", "bioinformatics", "computational biology"],
}

_SKIP_SKILLS = {
    "git", "github", "linux", "bash", "html", "css", "json",
    "powerpoint", "n8n", "cursor", "postman", "rest", "rest apis",
    "object-oriented programming", "oop", "data structures & algorithms",
}

_SENIOR_WORDS = {
    "senior", "sr.", "staff", "principal", "director", "vp", "vice president",
    "head of", "manager", "architect", "fellow", "distinguished", "executive",
}

_LEAD_RE = re.compile(r"\blead\b")

# A posting must contain at least one of these signals to survive basic_filter
_RESEARCH_SIGNALS = {
    "research", "lab", "intern", "reu", "assistant", "phd", "professor",
    "university", "graduate", "undergraduate", "faculty", "postdoc",
    "fellowship", "scholar", "academic", "thesis", "grant", "paper",
}


# ---------------------------------------------------------------------------
# TypedDict for normalised research opportunity before DB insert
# ---------------------------------------------------------------------------

class RawResearchOpportunity(TypedDict):
    professor_name: str
    institution: str
    lab_name: str | None
    research_area: str
    description: str
    desired_skills: list[str]
    program: str | None
    region: str | None
    contact_email: str | None
    url: str
    source: str
    posted_at: str | None


# ---------------------------------------------------------------------------
# Fingerprint & search-term helpers
# ---------------------------------------------------------------------------

def make_research_fingerprint(skills: list[str], research_interests: list[str]) -> str:
    """'r_'-prefixed fingerprint keeps research cache separate from company cache."""
    canonical = sorted(
        s.lower().strip() for s in (skills[:10] + research_interests) if s.strip()
    )
    return "r_" + hashlib.sha256(",".join(canonical).encode()).hexdigest()[:30]


def extract_research_search_terms(
    skills: list[str],
    research_interests: list[str],
) -> list[tuple[str, str]]:
    """
    Returns (search_term, research_area) pairs.
    Expands academic interest labels to job-board vocabulary via _INTEREST_SYNONYMS.
    research_area is stored on the ResearchOpportunity for semantic matching.
    """
    pairs: list[tuple[str, str]] = []
    seen_terms: set[str] = set()

    def _add(term: str, area: str) -> None:
        t = term.strip()
        if t and t not in seen_terms and len(pairs) < MAX_TERMS:
            seen_terms.add(t)
            pairs.append((t, area))

    for interest in research_interests[:4]:
        raw_interest = interest.strip()
        if not raw_interest or len(raw_interest) <= 2:
            continue
        key = raw_interest.lower()
        synonyms = _INTEREST_SYNONYMS.get(key)
        if synonyms:
            # Use first synonym as primary search term (most job-board-friendly)
            _add(f"{synonyms[0]} intern", raw_interest)
            # Add a second synonym as a separate search term for coverage
            if len(synonyms) > 1:
                _add(f"{synonyms[1]} research internship", raw_interest)
        else:
            # Verbatim interest — may still match some postings
            _add(f"{raw_interest} intern", raw_interest)
            _add(f"{raw_interest} research assistant", raw_interest)

    # REU-style search for the top interest
    if research_interests:
        top = research_interests[0].strip()
        if top:
            key = top.lower()
            synonyms = _INTEREST_SYNONYMS.get(key, [top])
            _add(f"REU {synonyms[0]} undergraduate research", top)

    # Skill-based terms to fill remaining slots
    meaningful = [
        s for s in skills
        if s.lower().strip() not in _SKIP_SKILLS and len(s) > 2
    ]
    for skill in meaningful:
        _add(f"{skill} research internship", skill)

    if not pairs:
        pairs = [
            ("computer science research internship", "Computer Science"),
            ("STEM undergraduate research REU", "STEM Research"),
            ("machine learning research intern", "Machine Learning"),
        ]

    return pairs[:MAX_TERMS]


# ---------------------------------------------------------------------------
# Normalise raw API posting → RawResearchOpportunity
# ---------------------------------------------------------------------------

def _strip_html(text: str) -> str:
    import html as _html
    cleaned = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = _html.unescape(cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _map_to_research_opp(
    raw: RawPosting, research_area: str
) -> RawResearchOpportunity | None:
    url = str(raw.get("source_url") or "").strip()
    description = _strip_html(str(raw.get("description") or "")).strip()
    company = str(raw.get("company_name") or "").strip()
    title = str(raw.get("title") or "").strip()

    if not url or len(description) < 50:
        return None

    from app.sources.normalize import extract_requirements

    full_desc = description if title in description else f"{title}\n\n{description}"

    return RawResearchOpportunity(
        professor_name=company or "Research Group",
        institution=company or "Unknown Institution",
        lab_name=None,
        research_area=research_area,
        description=full_desc,
        desired_skills=extract_requirements(description),
        program=None,
        region=raw.get("location"),
        contact_email=None,
        url=url,
        source=str(raw.get("source") or "live_fetch"),
        posted_at=str(raw.get("posted_at") or "") or None,
    )


# ---------------------------------------------------------------------------
# Pre-filter — fast, no LLM
# ---------------------------------------------------------------------------

def research_basic_filter(
    pairs: list[tuple[RawPosting, str]],
) -> list[tuple[RawPosting, str]]:
    """
    Keeps postings that:
    - Have a URL and description ≥ 50 chars
    - Are not clearly senior-level (unless "intern" in title)
    - Contain at least one research-domain signal
    Deduplicates by URL.
    """
    seen: set[str] = set()
    kept: list[tuple[RawPosting, str]] = []

    for raw, area in pairs:
        title = str(raw.get("title") or "").lower()
        url = str(raw.get("source_url") or "").strip()
        description = _strip_html(str(raw.get("description") or ""))

        if not url or not url.startswith("http") or url in seen:
            continue
        if len(description) < 50:  # noqa: PLR2004
            continue
        if (any(w in title for w in _SENIOR_WORDS) or bool(_LEAD_RE.search(title))) and "intern" not in title:
            continue

        combined = title + " " + description[:800].lower()
        if not any(signal in combined for signal in _RESEARCH_SIGNALS):
            continue

        seen.add(url)
        kept.append((raw, area))

    return kept


# ---------------------------------------------------------------------------
# Mistral relevance gate
# ---------------------------------------------------------------------------

async def _mistral_complete(messages: list[dict[str, str]]) -> str:
    """Calls Mistral open-mistral-7b directly; falls back to LLM router."""
    from app.core.config import settings

    api_key = getattr(settings, "MISTRAL_API_KEY", "")
    if api_key:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://api.mistral.ai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "open-mistral-7b",
                    "messages": messages,
                    "max_tokens": 80,
                    "temperature": 0.0,
                },
            )
            resp.raise_for_status()
            return str(resp.json()["choices"][0]["message"]["content"])

    from app.llm.router import complete
    return await complete(messages, max_tokens=80, temperature=0.0)


async def mistral_filter_research(
    pairs: list[tuple[RawPosting, str]],
    skills: list[str],
    research_interests: list[str],
) -> list[tuple[RawPosting, str]]:
    """
    Sends batches of LLM_BATCH postings to Mistral.
    Keeps only confirmed research internships/REUs relevant to user interests.
    Falls back to keyword title-check on any Mistral error.
    """
    interests_str = ", ".join((research_interests[:4] + skills[:4]))
    kept: list[tuple[RawPosting, str]] = []

    for i in range(0, len(pairs), LLM_BATCH):
        batch = pairs[i : i + LLM_BATCH]

        lines = []
        for idx, (raw, area) in enumerate(batch):
            snippet = _strip_html(str(raw.get("description") or ""))[:150].replace("\n", " ")
            lines.append(
                f"{idx}. {raw.get('title', '')} @ {raw.get('company_name', '?')} [{area}] — {snippet}"
            )

        prompt = (
            f"Research interests: {interests_str}\n\n"
            f"Return indices of listings that are (1) research internship/REU/RA AND (2) match interests.\n"
            f"Reply with JSON int array only. E.g. [0,3] or []\n\n"
            + "\n".join(lines)
        )

        try:
            result = await _mistral_complete([
                {
                    "role": "system",
                    "content": (
                        "Research internship classifier. "
                        "Reply ONLY with a JSON array of integers. No explanation."
                    ),
                },
                {"role": "user", "content": prompt},
            ])

            indices = _extract_int_array(result or "")
            if indices is None:
                raise ValueError(f"no JSON array in: {result!r}")
            for idx in indices:
                if 0 <= idx < len(batch):
                    kept.append(batch[idx])

        except Exception as exc:  # noqa: BLE001
            logger.warning("mistral_filter batch %d failed (%s) — keyword fallback", i, exc)
            for raw, area in batch:
                combined = (str(raw.get("title") or "") + " " + str(raw.get("description") or "")[:150]).lower()
                if any(w in combined for w in _RESEARCH_SIGNALS):
                    kept.append((raw, area))

    return kept


# ---------------------------------------------------------------------------
# Upsert into research_opportunities
# ---------------------------------------------------------------------------

async def _upsert_research_opportunity(
    db: AsyncSession,
    raw_ro: RawResearchOpportunity,
) -> bool:
    """Returns True if already existed (duplicate)."""
    url = raw_ro["url"]

    existing = (
        await db.execute(
            select(ResearchOpportunity).where(ResearchOpportunity.url == url)
        )
    ).scalar_one_or_none()

    if existing is not None:
        existing.last_seen_at = datetime.now(UTC)
        await db.commit()
        return True

    # Compute embedding so semantic matching in ResearchService works
    embed_text = f"{raw_ro['research_area']} research. {raw_ro['description'][:600]}"
    embedding = None
    try:
        vectors = await embed([embed_text])
        if vectors:
            embedding = vectors[0]
    except Exception:  # noqa: BLE001
        pass

    # Parse posted_at from string if available
    _posted_at: datetime | None = None
    if raw_ro.get("posted_at"):
        try:
            s = str(raw_ro["posted_at"]).replace("Z", "+00:00")
            dt = datetime.fromisoformat(s)
            _posted_at = dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)
        except (ValueError, TypeError):
            pass

    db.add(ResearchOpportunity(
        professor_name=raw_ro["professor_name"],
        institution=raw_ro["institution"],
        lab_name=raw_ro["lab_name"],
        research_area=raw_ro["research_area"],
        description=raw_ro["description"],
        desired_skills=raw_ro["desired_skills"],
        program=raw_ro["program"],
        region=raw_ro["region"],
        contact_email=raw_ro["contact_email"],
        url=url,
        source=raw_ro["source"],
        posted_at=_posted_at,
        last_seen_at=datetime.now(UTC),
        embedding=embedding,
    ))
    await db.commit()
    return False


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class ResearchAggregationService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def is_stale(self, fingerprint: str) -> bool:
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
        from app.core.config import settings

        term_area_pairs = extract_research_search_terms(skills, research_interests)
        logger.info(
            "research_refresh fp=%s terms=%s",
            fingerprint[:8], [t for t, _ in term_area_pairs],
        )

        adzuna_id   = getattr(settings, "ADZUNA_APP_ID",   "")
        adzuna_key  = getattr(settings, "ADZUNA_APP_KEY",  "")
        adzuna_ctry = getattr(settings, "ADZUNA_COUNTRY",  "us")
        usa_key     = getattr(settings, "USAJOBS_API_KEY", "")
        usa_email   = getattr(settings, "USAJOBS_EMAIL",   "")
        jsearch_key = getattr(settings, "JSEARCH_API_KEY", "")

        # ── 1. Fetch all sources in parallel ────────────────────────────────
        tasks: list[asyncio.Task[list[RawPosting]]] = []
        areas: list[str] = []

        for term, area in term_area_pairs:
            if adzuna_id and adzuna_key:
                tasks.append(asyncio.create_task(
                    _fetch_adzuna(term, adzuna_id, adzuna_key, adzuna_ctry)
                ))
                areas.append(area)
            if usa_key and usa_email:
                tasks.append(asyncio.create_task(
                    _fetch_usajobs(term, usa_key, usa_email)
                ))
                areas.append(area)
            if jsearch_key:
                tasks.append(asyncio.create_task(
                    _fetch_jsearch(term, jsearch_key)
                ))
                areas.append(area)

        results = await asyncio.gather(*tasks, return_exceptions=True)

        raw_pairs: list[tuple[RawPosting, str]] = []
        for result, area in zip(results, areas, strict=False):
            if isinstance(result, list):
                raw_pairs.extend((r, area) for r in result)
            elif isinstance(result, Exception):
                logger.warning("research_source_error: %s", result)

        logger.info("research_refresh fp=%s raw=%d", fingerprint[:8], len(raw_pairs))

        # ── 2. Pre-filter ────────────────────────────────────────────────────
        filtered = research_basic_filter(raw_pairs)
        logger.info("research_refresh fp=%s after_basic=%d", fingerprint[:8], len(filtered))

        # ── 3. Mistral gate ──────────────────────────────────────────────────
        relevant: list[tuple[RawPosting, str]] = []
        if filtered:
            try:
                relevant = await mistral_filter_research(filtered, skills, research_interests)
            except Exception as exc:  # noqa: BLE001
                logger.warning("mistral_total_fail: %s — keyword fallback", exc)
                _kw = {"research", "reu", "intern", "lab", "phd", "assistant"}
                relevant = [
                    (raw, area) for raw, area in filtered
                    if any(w in str(raw.get("title") or "").lower() for w in _kw)
                ]

        logger.info("research_refresh fp=%s after_mistral=%d", fingerprint[:8], len(relevant))

        # ── 4. Map + upsert ──────────────────────────────────────────────────
        ingested = 0
        for raw, area in relevant:
            raw_ro = _map_to_research_opp(raw, area)
            if raw_ro is None:
                continue
            try:
                duped = await _upsert_research_opportunity(self.db, raw_ro)
                if not duped:
                    ingested += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("research_upsert_failed url=%s err=%s", raw_ro.get("url"), exc)
                await self.db.rollback()

        # ── 5. Firecrawl Tier-1 programs (SURF, NSF REU, DAAD RISE, CERN, etc.) ─
        firecrawl_key = getattr(settings, "FIRECRAWL_API_KEY", "")
        if firecrawl_key:
            try:
                from app.llm.router import complete as _llm_fn
                from app.sources.firecrawl_research import fetch_research_opportunities
                firecrawl_opps = await fetch_research_opportunities(
                    firecrawl_key, _llm_fn, max_pages=4
                )
                for opp in firecrawl_opps:
                    if not opp.get("url") or not opp.get("description"):
                        continue
                    raw_ro = RawResearchOpportunity(
                        professor_name=str(opp.get("professor_name") or "Program Team"),
                        institution=str(opp.get("institution") or "Unknown"),
                        lab_name=opp.get("lab_name"),
                        research_area=str(opp.get("research_area") or "Research"),
                        description=str(opp.get("description") or ""),
                        desired_skills=list(opp.get("desired_skills") or []),
                        program=opp.get("program"),
                        region=opp.get("region"),
                        contact_email=opp.get("contact_email"),
                        url=str(opp.get("url") or ""),
                        source="firecrawl",
                        posted_at=None,
                    )
                    try:
                        duped = await _upsert_research_opportunity(self.db, raw_ro)
                        if not duped:
                            ingested += 1
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("firecrawl_upsert_failed url=%s err=%s", raw_ro.get("url"), exc)
                        await self.db.rollback()
                logger.info("research_refresh fp=%s firecrawl=%d", fingerprint[:8], len(firecrawl_opps))
            except Exception as exc:  # noqa: BLE001
                logger.warning("firecrawl_research_failed: %s", exc)

        # ── 6. Update cache ──────────────────────────────────────────────────
        now = datetime.now(UTC)
        terms_list = [t for t, _ in term_area_pairs]
        existing_cache = (
            await self.db.execute(
                select(InterestSearchCache).where(
                    InterestSearchCache.fingerprint == fingerprint
                )
            )
        ).scalar_one_or_none()

        if existing_cache is not None:
            existing_cache.search_terms = terms_list
            existing_cache.last_fetched_at = now
            existing_cache.expires_at = now + timedelta(hours=TTL_HOURS)
            existing_cache.result_count = ingested
        else:
            self.db.add(InterestSearchCache(
                fingerprint=fingerprint,
                search_terms=terms_list,
                last_fetched_at=now,
                expires_at=now + timedelta(hours=TTL_HOURS),
                result_count=ingested,
            ))
        await self.db.commit()

        logger.info(
            "research_refresh_done fp=%s raw=%d basic=%d mistral=%d ingested=%d",
            fingerprint[:8], len(raw_pairs), len(filtered), len(relevant), ingested,
        )

        return ingested


# ---------------------------------------------------------------------------
# Background entry-point — owns its own DB session
# ---------------------------------------------------------------------------

async def refresh_research_background(
    fingerprint: str,
    skills: list[str],
    research_interests: list[str],
) -> None:
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        try:
            svc = ResearchAggregationService(db)
            await svc.refresh(fingerprint, skills, research_interests)
        except Exception as exc:  # noqa: BLE001
            logger.error("research_background_failed err=%s", exc)


# ---------------------------------------------------------------------------
# Source helpers
# ---------------------------------------------------------------------------

async def _fetch_adzuna(
    term: str, app_id: str, app_key: str, country: str
) -> list[RawPosting]:
    from app.sources.adzuna import _parse_job as _parse

    results: list[RawPosting] = []
    base = f"https://api.adzuna.com/v1/api/jobs/{country}/search/{{page}}"
    async with httpx.AsyncClient(timeout=20.0) as client:
        for page in range(1, 3):
            try:
                resp = await client.get(
                    base.format(page=page),
                    params={
                        "app_id": app_id, "app_key": app_key, "what": term,
                        "results_per_page": 50, "content-type": "application/json",
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
                logger.warning("r_adzuna term=%r err=%s", term, exc)
                break
    return results


async def _fetch_usajobs(term: str, api_key: str, email: str) -> list[RawPosting]:
    from app.sources.usajobs import _parse_job as _parse

    results: list[RawPosting] = []
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                "https://data.usajobs.gov/api/search",
                headers={"Host": "data.usajobs.gov", "User-Agent": email, "Authorization-Key": api_key},
                params={"Keyword": term, "NumberOfResults": 100, "Fields": "Minimum"},
            )
            if resp.status_code == 200:
                for item in resp.json().get("SearchResult", {}).get("SearchResultItems", []):
                    parsed = _parse(item)
                    if parsed:
                        results.append(parsed)
    except Exception as exc:  # noqa: BLE001
        logger.warning("r_usajobs term=%r err=%s", term, exc)
    return results


async def _fetch_jsearch(term: str, api_key: str) -> list[RawPosting]:
    from app.sources.jsearch import JSearchSource
    try:
        return await JSearchSource().fetch_by_term(term, api_key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("r_jsearch term=%r err=%s", term, exc)
        return []
