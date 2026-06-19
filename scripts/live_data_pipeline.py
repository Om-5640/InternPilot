"""InternPilot Live Data Pipeline
==================================
Fetches real internship postings from all configured job boards, normalises
and filters the data with strict Python rules, enriches descriptions and
requirements via the LLM router (with per-call cooldown to respect rate
limits), and stores everything to the configured PostgreSQL database.

Additionally seeds / refreshes research opportunities from a curated list of
real labs, pulling recent paper titles from the arXiv API and writing
LLM-generated summaries.

Usage:
    uv run python scripts/live_data_pipeline.py
    uv run python scripts/live_data_pipeline.py --no-llm      # skip LLM enrichment
    uv run python scripts/live_data_pipeline.py --dry-run     # fetch + filter, no DB writes
    uv run python scripts/live_data_pipeline.py --research-only
    uv run python scripts/live_data_pipeline.py --postings-only
"""
from __future__ import annotations

import argparse
import asyncio
import html
import logging
import re
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Make project root importable
# ---------------------------------------------------------------------------
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Third-party imports that don't depend on sys.path manipulation
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# First-party: register all models with SQLAlchemy's mapper before any ORM query fires
import app.models.application  # noqa: E402, F401
import app.models.artifact  # noqa: E402, F401
import app.models.company  # noqa: E402, F401
import app.models.contact  # noqa: E402, F401
import app.models.evaluation  # noqa: E402, F401
import app.models.notification  # noqa: E402, F401
import app.models.outcome  # noqa: E402, F401
import app.models.posting  # noqa: E402, F401
import app.models.profile  # noqa: E402, F401
import app.models.referral  # noqa: E402, F401
import app.models.research_outreach  # noqa: E402, F401
import app.models.user  # noqa: E402, F401
from app.core.config import settings  # noqa: E402
from app.models.posting import Posting  # noqa: E402
from app.models.research_opportunity import ResearchOpportunity  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger("pipeline")

# ---------------------------------------------------------------------------
# Rate-limit / cooldown config
# ---------------------------------------------------------------------------
LLM_COOLDOWN_SECS: float = 2.5      # wait between LLM calls
ARXIV_COOLDOWN_SECS: float = 1.0    # wait between arXiv API calls
MAX_LLM_ENRICH_PER_RUN: int = 60    # cap per-run to avoid burning quota
POSTING_MIN_DESC_LEN: int = 150     # discard very short descriptions
POSTING_MAX_REQUIREMENTS_EMPTY: int = 2  # re-extract if fewer than this many bullets

# ---------------------------------------------------------------------------
# HTML / text normalisation helpers
# ---------------------------------------------------------------------------

_TAG_RE = re.compile(r"<[^>]+>")
_ENTITY_RE = re.compile(r"&[a-zA-Z0-9#]+;")
_WHITESPACE_RE = re.compile(r"\s{3,}")


def strip_html(raw: str) -> str:
    """Remove HTML tags, decode entities, collapse excess whitespace."""
    text = _TAG_RE.sub(" ", raw)
    text = html.unescape(text)
    text = _ENTITY_RE.sub(" ", text)
    text = _WHITESPACE_RE.sub("\n\n", text)
    return text.strip()


def normalise_location(loc: str | None) -> str | None:
    """Standardise common location aliases to canonical City, ST format."""
    if not loc:
        return None
    loc = loc.strip()
    # Remove trailing country codes like ", US" or ", United States"
    loc = re.sub(r",?\s*(US|USA|United States|United Kingdom|UK)$", "", loc, flags=re.IGNORECASE).strip()

    # Exact-match aliases (case-insensitive)
    _aliases: dict[str, str] = {
        "NYC": "New York, NY",
        "New York": "New York, NY",
        "New York City": "New York, NY",
        "New York, New York": "New York, NY",
        "SF": "San Francisco, CA",
        "San Francisco": "San Francisco, CA",
        "San Francisco Bay Area": "San Francisco Bay Area, CA",
        "SFBay": "San Francisco Bay Area, CA",
        "Bay Area": "San Francisco Bay Area, CA",
        "Silicon Valley": "San Francisco Bay Area, CA",
        "LA": "Los Angeles, CA",
        "Los Angeles": "Los Angeles, CA",
        "Seattle": "Seattle, WA",
        "Seattle, Washington": "Seattle, WA",
        "Boston": "Boston, MA",
        "Boston, Massachusetts": "Boston, MA",
        "Cambridge": "Cambridge, MA",
        "Cambridge, MA": "Cambridge, MA",
        "Chicago": "Chicago, IL",
        "Chicago, Illinois": "Chicago, IL",
        "Austin": "Austin, TX",
        "Austin, Texas": "Austin, TX",
        "Denver": "Denver, CO",
        "Denver, Colorado": "Denver, CO",
        "Atlanta": "Atlanta, GA",
        "Atlanta, Georgia": "Atlanta, GA",
        "Washington DC": "Washington, DC",
        "Washington D.C.": "Washington, DC",
        "Washington, D.C.": "Washington, DC",
        "DC": "Washington, DC",
        "Raleigh": "Raleigh, NC",
        "Pittsburgh": "Pittsburgh, PA",
        "Minneapolis": "Minneapolis, MN",
        "Portland": "Portland, OR",
        "Dallas": "Dallas, TX",
        "Houston": "Houston, TX",
        "Phoenix": "Phoenix, AZ",
        "San Diego": "San Diego, CA",
        "San Jose": "San Jose, CA",
        "Remote": "Remote",
        "Worldwide": "Remote",
        "Anywhere": "Remote",
        "Global": "Remote",
        "Work from home": "Remote",
        "Work From Home": "Remote",
        "WFH": "Remote",
        "Hybrid": "Hybrid",
        "Onsite": "On-site",
        "On Site": "On-site",
        "On-site": "On-site",
    }
    for alias, canonical in _aliases.items():
        if re.fullmatch(re.escape(alias), loc, re.IGNORECASE):
            return canonical
    # Partial-match: if "remote" appears anywhere treat as Remote
    if re.search(r"\bremote\b", loc, re.IGNORECASE):
        return "Remote"
    return loc


def is_genuine_internship_title(title: str) -> bool:
    """True when the title is a real internship (not a full-time or senior role)."""
    lower = title.lower()
    # Must contain intern keyword
    if not re.search(r"\bintern(ship)?\b", lower):
        return False
    # Reject titles that are clearly senior/principal/staff despite containing "intern"
    return not re.search(
        r"\b(principal|staff|director|vp|vice president|head of|senior director)\b", lower
    )


def quality_filter(raw_desc: str, title: str) -> tuple[bool, str]:
    """
    Returns (passes, cleaned_description).
    Fails if description is too short or title is not a genuine internship.
    """
    if not is_genuine_internship_title(title):
        return False, ""
    cleaned = strip_html(raw_desc)
    if len(cleaned) < POSTING_MIN_DESC_LEN:
        return False, ""
    return True, cleaned


def extract_requirements_from_text(text: str) -> list[str]:
    """Heuristic extraction without LLM — used as a fallback."""
    pattern = re.compile(
        r"(?:Requirements?|Qualifications?|What you.ll need|You.ll need|Must.have|"
        r"We.re looking for|Looking for|Ideal candidate|You have|You bring)[:\s]*\n"
        r"((?:.+\n?)+?)(?:\n\n|\Z)",
        re.IGNORECASE,
    )
    m = pattern.search(text)
    if not m:
        return []
    block = m.group(1)
    bullets = re.split(r"\n[•\-\*]\s*|\n\d+\.\s*|\n", block)
    return [b.strip() for b in bullets if 12 < len(b.strip()) < 300][:8]


# ---------------------------------------------------------------------------
# LLM enrichment helpers (batched, with cooldown)
# ---------------------------------------------------------------------------

_last_llm_call: float = 0.0
LLM_BATCH_SIZE: int = 5  # postings per LLM call — amortises system-prompt tokens


async def _llm_with_cooldown(messages: list[dict]) -> str:
    global _last_llm_call  # noqa: PLW0603
    elapsed = time.monotonic() - _last_llm_call
    if elapsed < LLM_COOLDOWN_SECS:
        await asyncio.sleep(LLM_COOLDOWN_SECS - elapsed)
    from app.llm.router import complete
    result = await complete(messages)
    _last_llm_call = time.monotonic()
    return result


_BATCH_SYSTEM = (
    "You extract structured data from job postings. "
    "Return ONLY valid JSON — no markdown fences, no explanations. "
    "The JSON must be an array where each element has:\n"
    '  "idx": integer (same as input),\n'
    '  "requirements": array of 5-8 short strings (domain-specific skills, under 70 chars each),\n'
    '  "keywords": array of 8-15 important keywords for resume/ATS matching (tools, frameworks, '
    "domain terms — be domain-aware: for chemical engineering include HYSYS, ASPEN, thermodynamics; "
    "for finance include Excel, Bloomberg, DCF; for software include language names, frameworks),\n"
    '  "summary": one sentence, domain-specific, describing what the intern will do day-to-day.'
)


async def llm_enrich_batch(
    postings_batch: list[tuple[int, str, str]],
) -> dict[int, dict[str, Any]]:
    """
    Send up to LLM_BATCH_SIZE postings in one call.
    postings_batch: list of (idx, title, description[:2000])
    Returns: {idx: {requirements, keywords, summary}}
    """
    import json as _json

    lines: list[str] = []
    for idx, title, desc in postings_batch:
        lines.append(f"[{idx}] Title: {title}\nDescription: {desc[:1800]}")
    user_msg = (
        f"Analyse these {len(postings_batch)} internship postings and return a JSON array "
        f"with one object per posting:\n\n" + "\n\n---\n\n".join(lines)
    )

    try:
        raw = await _llm_with_cooldown([
            {"role": "system", "content": _BATCH_SYSTEM},
            {"role": "user", "content": user_msg},
        ])
        # Strip markdown fences if present
        raw = re.sub(r"^```[a-z]*\n?", "", raw.strip())
        raw = re.sub(r"\n?```$", "", raw.strip())
        items = _json.loads(raw)
        result: dict[int, dict[str, Any]] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            idx_val = int(item.get("idx", -1))
            if idx_val < 0:
                continue
            result[idx_val] = {
                "requirements": [str(r).strip() for r in item.get("requirements", []) if r][:8],
                "keywords": [str(k).strip() for k in item.get("keywords", []) if k][:15],
                "summary": str(item.get("summary", "")).strip(),
            }
        return result
    except Exception as exc:  # noqa: BLE001
        logger.warning("llm_enrich_batch failed (batch_size=%d): %s", len(postings_batch), exc)
        return {}


async def llm_extract_requirements(title: str, description: str) -> list[str]:
    """Single-posting fallback (used when batch returns no result for this posting)."""
    result = await llm_enrich_batch([(0, title, description)])
    return result.get(0, {}).get("requirements", [])


# ---------------------------------------------------------------------------
# arXiv API helper for recent paper lookup
# ---------------------------------------------------------------------------

_last_arxiv_call: float = 0.0


async def arxiv_recent_paper(
    search_query: str,
    max_results: int = 3,
) -> dict[str, Any] | None:
    """
    Fetch the most recent arXiv paper matching the search query.
    Returns {"title": str, "year": int} or None.
    """
    global _last_arxiv_call  # noqa: PLW0603
    elapsed = time.monotonic() - _last_arxiv_call
    if elapsed < ARXIV_COOLDOWN_SECS:
        await asyncio.sleep(ARXIV_COOLDOWN_SECS - elapsed)

    import httpx
    url = "https://export.arxiv.org/api/query"
    params = {
        "search_query": f"all:{search_query}",
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "max_results": max_results,
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params)
        _last_arxiv_call = time.monotonic()
        if resp.status_code != 200:
            return None

        # Simple XML parse — no lxml dependency
        xml = resp.text
        titles = re.findall(r"<title>(?!ArXiv Query)(.+?)</title>", xml, re.DOTALL)
        dates = re.findall(r"<published>(\d{4})", xml)
        if titles:
            title = re.sub(r"\s+", " ", titles[0]).strip()
            year = int(dates[0]) if dates else datetime.now(UTC).year
            return {"title": title, "year": year}
    except Exception as exc:  # noqa: BLE001
        logger.warning("arxiv_recent_paper failed query=%r: %s", search_query, exc)
    return None


# ---------------------------------------------------------------------------
# Postings pipeline
# ---------------------------------------------------------------------------

async def run_postings_pipeline(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    dry_run: bool,
    use_llm: bool,
) -> dict[str, int]:
    """Fetch from all sources, filter, enrich, and persist."""
    from app.services.aggregation_service import AggregationService

    # ---- Step 1: Fetch from all sources ----
    logger.info("=== POSTINGS PIPELINE ===")
    logger.info("Fetching from all job board sources…")

    if not dry_run:
        async with session_factory() as db:
            svc = AggregationService(db)
            result = await svc.refresh()
            logger.info(
                "Aggregation complete — ingested=%d  deduped=%d",
                result["ingested"], result["deduped"],
            )
    else:
        # In dry-run mode, still fetch to measure quality
        import asyncio as _asyncio  # noqa: I001

        from app.sources.ashby import AshbySource
        from app.sources.greenhouse import GreenhouseSource
        from app.sources.remoteok import RemoteOKSource
        from app.sources.remotive import RemotiveSource

        sources = [GreenhouseSource(), AshbySource(), RemoteOKSource(), RemotiveSource()]
        raw_batches = await _asyncio.gather(*[s.fetch() for s in sources], return_exceptions=True)
        all_raws = []
        for batch in raw_batches:
            if isinstance(batch, list):
                all_raws.extend(batch)

        pass_count = fail_count = 0
        for raw in all_raws:
            ok, _ = quality_filter(raw.get("description") or "", raw.get("title") or "")
            if ok:
                pass_count += 1
            else:
                fail_count += 1
        logger.info("[dry-run] fetched=%d  passed_filter=%d  rejected=%d", len(all_raws), pass_count, fail_count)
        return {"fetched": len(all_raws), "passed": pass_count, "rejected": fail_count}

    # ---- Step 2: Post-process — clean descriptions, fill missing requirements ----
    logger.info("Post-processing stored postings (description clean + requirements backfill)…")
    enriched = skipped = errors = 0

    async with session_factory() as db:
        # Only process postings that have either:
        #   - HTML in description (strip it)
        #   - Very few requirements (re-extract)
        # Limit to recent postings to keep the run fast
        cutoff = datetime.now(UTC) - timedelta(days=30)
        stmt = (
            select(Posting)
            .where(Posting.status == "active")
            .where(Posting.created_at >= cutoff)
            .order_by(Posting.created_at.desc())
            .limit(500)
        )
        postings = list((await db.execute(stmt)).scalars().all())
        logger.info("Checking %d recent postings for quality issues…", len(postings))

        llm_calls = 0

        # Phase A: Per-posting clean + quality gate (no LLM)
        needs_llm: list[Posting] = []
        for p in postings:
            try:
                changed = False

                # Clean HTML from description
                if "<" in (p.description or ""):
                    cleaned = strip_html(p.description or "")
                    if len(cleaned) >= POSTING_MIN_DESC_LEN:
                        p.description = cleaned
                        changed = True
                    else:
                        p.status = "stale"
                        db.add(p)
                        await db.commit()
                        skipped += 1
                        continue

                # Normalise location
                normalised_loc = normalise_location(p.location)
                if normalised_loc != p.location:
                    p.location = normalised_loc
                    changed = True

                # Quality-gate title
                if not is_genuine_internship_title(p.title or ""):
                    p.status = "stale"
                    db.add(p)
                    await db.commit()
                    skipped += 1
                    continue

                # Heuristic requirement extraction (no LLM quota used)
                reqs = p.requirements or []
                if len(reqs) < POSTING_MAX_REQUIREMENTS_EMPTY:
                    desc = p.description or ""
                    heuristic_reqs = extract_requirements_from_text(desc)
                    if heuristic_reqs:
                        p.requirements = heuristic_reqs
                        changed = True
                    elif use_llm and len(desc) > 200 and llm_calls < MAX_LLM_ENRICH_PER_RUN:  # noqa: PLR2004
                        needs_llm.append(p)

                if changed:
                    db.add(p)
                    await db.commit()
                    enriched += 1

            except Exception as exc:  # noqa: BLE001
                logger.warning("post-process failed posting_id=%s: %s", p.id, exc)
                await db.rollback()
                errors += 1

        # Phase B: Batched LLM enrichment for postings that need it
        # Batching 5 per call dramatically reduces token usage vs 1-per-call
        if needs_llm:
            logger.info("Batched LLM enrichment for %d postings (%d calls)…",
                        len(needs_llm), -(-len(needs_llm) // LLM_BATCH_SIZE))

        batch_input: list[tuple[int, str, str]] = [
            (i, p.title or "", p.description or "")
            for i, p in enumerate(needs_llm)
        ]
        for batch_start in range(0, len(batch_input), LLM_BATCH_SIZE):
            if llm_calls >= MAX_LLM_ENRICH_PER_RUN:
                logger.info("LLM cap (%d) reached — stopping enrichment", MAX_LLM_ENRICH_PER_RUN)
                break
            batch = batch_input[batch_start : batch_start + LLM_BATCH_SIZE]
            titles_str = ", ".join(t for _, t, _ in batch)
            logger.info("  LLM batch [%d-%d]: %s", batch_start, batch_start + len(batch) - 1, titles_str[:100])
            try:
                results = await llm_enrich_batch(batch)
                llm_calls += 1
                for local_idx, _, _ in batch:
                    if local_idx not in results:
                        continue
                    p = needs_llm[local_idx]
                    enrichment = results[local_idx]
                    changed = False
                    if enrichment.get("requirements"):
                        p.requirements = enrichment["requirements"]
                        changed = True
                    # Store keywords + summary in decode_cache for immediate ATS use
                    if enrichment.get("keywords") or enrichment.get("summary"):
                        existing_cache = p.decode_cache or {}
                        cache_update = {
                            "requirements": p.requirements or [],
                            "keywords": enrichment.get("keywords", existing_cache.get("keywords", [])),
                            "summary": enrichment.get("summary", existing_cache.get("summary", "")),
                        }
                        p.decode_cache = cache_update
                        changed = True
                    if changed:
                        db.add(p)
                        enriched += 1
                await db.commit()
            except Exception as exc:  # noqa: BLE001
                logger.warning("llm batch failed: %s", exc)
                await db.rollback()
                errors += 1

        # Phase C: Backfill embeddings for postings that have none
        from app.llm.embeddings import embed as _embed
        unembedded = [p for p in postings if p.embedding is None and p.status == "active"]
        if unembedded:
            logger.info("Backfilling embeddings for %d postings without vectors…", len(unembedded))
            for p in unembedded:
                try:
                    text = f"{p.title}. {(p.description or '')[:800]}"
                    vecs = await _embed([text])
                    if vecs:
                        p.embedding = vecs[0]
                        db.add(p)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("embed backfill failed posting_id=%s: %s", p.id, exc)
            try:
                await db.commit()
                logger.info("Embeddings backfilled for %d postings.", len(unembedded))
            except Exception as exc:  # noqa: BLE001
                logger.warning("embed backfill commit failed: %s", exc)
                await db.rollback()

    logger.info("Post-process done — enriched=%d  skipped=%d  errors=%d  llm_calls=%d",
                enriched, skipped, errors, llm_calls)
    return {"enriched": enriched, "skipped": skipped, "errors": errors}


# ---------------------------------------------------------------------------
# Research opportunities pipeline
# ---------------------------------------------------------------------------

# Curated list of real research labs with verifiable URLs
_RESEARCH_LABS: list[dict[str, Any]] = [
    # --- NLP / ML ---
    {
        "professor_name": "Prof. Percy Liang",
        "institution": "Stanford University",
        "lab_name": "Center for Research on Foundation Models (CRFM)",
        "research_area": "Foundation models · evaluation · robustness",
        "description": (
            "CRFM studies the capabilities, limitations, and societal impact of large language "
            "models. Current projects include HELM (holistic evaluation), instruction following, "
            "and training efficiency. We actively host undergrad/masters research interns."
        ),
        "desired_skills": ["Python", "PyTorch", "LLM fine-tuning", "evaluation benchmarks", "statistics"],
        "contact_email": "crfm-internship@cs.stanford.edu",
        "url": "https://crfm.stanford.edu",
        "program": "Research Internship",
        "region": "Palo Alto, CA (hybrid)",
        "arxiv_query": "Percy Liang foundation models HELM evaluation",
    },
    {
        "professor_name": "Prof. Yejin Choi",
        "institution": "University of Washington / Allen Institute for AI",
        "lab_name": "NLP & Commonsense Reasoning Lab",
        "research_area": "Commonsense reasoning · knowledge graphs · NLU",
        "description": (
            "We work on commonsense knowledge representation, reasoning, and language grounding. "
            "Projects span dataset creation (ATOMIC, WinoGrande), model probing, and symbolic-neural hybrids. "
            "Strong candidates have experience with transformer architectures and benchmark datasets."
        ),
        "desired_skills": ["Python", "Transformers", "NLU", "PyTorch", "knowledge graphs"],
        "contact_email": None,
        "url": "https://homes.cs.washington.edu/~yejin/",
        "program": "Research Assistant",
        "region": "Seattle, WA (hybrid)",
        "arxiv_query": "Yejin Choi commonsense reasoning language models",
    },
    {
        "professor_name": "Prof. Graham Neubig",
        "institution": "Carnegie Mellon University",
        "lab_name": "Language Technologies Institute (LTI) / Neulab",
        "research_area": "Multilingual NLP · code generation · low-resource languages",
        "description": (
            "Neulab works on multilingual and low-resource NLP, code generation, and machine "
            "translation. We are especially interested in students with cross-lingual transfer "
            "experience or open-source contributions to HuggingFace/fairseq ecosystems."
        ),
        "desired_skills": ["Python", "PyTorch", "HuggingFace", "multilingual NLP", "machine translation"],
        "contact_email": "gneubig@cs.cmu.edu",
        "url": "https://www.cs.cmu.edu/~gneubig/",
        "program": "Research Internship / REU",
        "region": "Pittsburgh, PA (on-site)",
        "arxiv_query": "Graham Neubig multilingual NLP code generation",
    },
    # --- Systems / ML Systems ---
    {
        "professor_name": "Prof. Ion Stoica",
        "institution": "UC Berkeley",
        "lab_name": "RISELab / SkyLab",
        "research_area": "Distributed ML systems · LLM serving · Ray",
        "description": (
            "SkyLab builds the infrastructure for next-generation AI applications — spanning "
            "LLM serving (vLLM), cloud cost optimisation (SkyPilot), and distributed training. "
            "We look for students who can write high-performance Python/C++ and reason about "
            "distributed systems tradeoffs."
        ),
        "desired_skills": ["Python", "C++", "CUDA", "distributed systems", "PyTorch", "Kubernetes"],
        "contact_email": None,
        "url": "https://sky.cs.berkeley.edu",
        "program": "Research Intern",
        "region": "Berkeley, CA (on-site preferred)",
        "arxiv_query": "Ion Stoica vLLM SkyPilot LLM serving",
    },
    {
        "professor_name": "Prof. Tim Kraska",
        "institution": "MIT",
        "lab_name": "Data Systems Group",
        "research_area": "Learned data structures · ML for databases · query optimisation",
        "description": (
            "We integrate machine learning into database internals — learned indexes, "
            "cardinality estimation, and AI-assisted query optimisation. Interns typically "
            "implement ML models in C++ inside database engines or design benchmark suites."
        ),
        "desired_skills": ["C++", "Python", "database internals", "machine learning", "statistics"],
        "contact_email": None,
        "url": "https://groups.csail.mit.edu/data/",
        "program": "Research Intern (UROP eligible)",
        "region": "Cambridge, MA (on-site)",
        "arxiv_query": "Tim Kraska learned index database machine learning",
    },
    # --- Robotics / CV ---
    {
        "professor_name": "Prof. Pieter Abbeel",
        "institution": "UC Berkeley",
        "lab_name": "Robot Learning Lab",
        "research_area": "Robot learning · imitation learning · reinforcement learning",
        "description": (
            "We build robots that learn from demonstrations and minimal supervision. "
            "Current projects include diffusion-policy for manipulation, language-conditioned "
            "policies, and sim-to-real transfer. Strong robotics or RL background required."
        ),
        "desired_skills": ["Python", "PyTorch", "reinforcement learning", "ROS", "robot manipulation"],
        "contact_email": None,
        "url": "https://people.eecs.berkeley.edu/~pabbeel/",
        "program": "Research Intern",
        "region": "Berkeley, CA (on-site)",
        "arxiv_query": "Pieter Abbeel robot learning imitation policy diffusion",
    },
    {
        "professor_name": "Prof. Deva Ramanan",
        "institution": "Carnegie Mellon University",
        "lab_name": "Vision & Autonomous Systems Lab",
        "research_area": "Computer vision · 3D perception · autonomous driving",
        "description": (
            "Our lab works on 3D object detection, tracking, and scene understanding for "
            "autonomous vehicles. Projects span dataset curation, novel architectures, and "
            "deployment in partnership with Argo AI / Waymo. Python + PyTorch required."
        ),
        "desired_skills": ["Python", "PyTorch", "computer vision", "3D detection", "NumPy"],
        "contact_email": None,
        "url": "https://www.cs.cmu.edu/~deva/",
        "program": "Research Intern",
        "region": "Pittsburgh, PA",
        "arxiv_query": "Deva Ramanan 3D object detection autonomous driving",
    },
    # --- Security / Privacy ---
    {
        "professor_name": "Prof. Dawn Song",
        "institution": "UC Berkeley",
        "lab_name": "DeepDrive / Berkeley AI Safety (BAIR)",
        "research_area": "AI security · differential privacy · adversarial robustness",
        "description": (
            "We investigate attacks and defences for machine learning models — adversarial "
            "examples, membership inference, and LLM safety. We also work on privacy-preserving "
            "ML using differential privacy and secure multi-party computation."
        ),
        "desired_skills": ["Python", "PyTorch", "ML security", "cryptography", "differential privacy"],
        "contact_email": None,
        "url": "https://dawnsong.io",
        "program": "Research Intern (funded)",
        "region": "Berkeley, CA (hybrid)",
        "arxiv_query": "Dawn Song adversarial robustness AI safety differential privacy",
    },
    # --- HCI / CSCW ---
    {
        "professor_name": "Prof. Bjoern Hartmann",
        "institution": "UC Berkeley",
        "lab_name": "Jacobs Institute / EECS — Human-Computer Interaction",
        "research_area": "Developer tools · AI-assisted programming · mixed reality",
        "description": (
            "We build tools that help programmers and designers work with AI — intelligent code "
            "editors, mixed-initiative sketching, and programming by demonstration. Interns "
            "typically build prototypes in JavaScript/TypeScript + Python."
        ),
        "desired_skills": ["JavaScript", "TypeScript", "React", "Python", "user studies"],
        "contact_email": None,
        "url": "https://people.eecs.berkeley.edu/~bjoern/",
        "program": "Research Intern / UROP",
        "region": "Berkeley, CA",
        "arxiv_query": "Bjoern Hartmann HCI programming tools AI",
    },
    # --- Bioinformatics ---
    {
        "professor_name": "Prof. Bing Ren",
        "institution": "UC San Diego",
        "lab_name": "Ludwig Institute — Genomics",
        "research_area": "Single-cell genomics · epigenetics · chromatin accessibility",
        "description": (
            "We develop computational methods to analyse single-cell ATAC-seq and RNA-seq data, "
            "building tools to map gene regulatory networks. Python + R skills with bioinformatics "
            "pipeline experience (Snakemake, Nextflow) strongly preferred."
        ),
        "desired_skills": ["Python", "R", "bioinformatics", "single-cell RNA-seq", "machine learning"],
        "contact_email": None,
        "url": "https://renlab.sdsc.edu",
        "program": "Computational Biology Intern",
        "region": "San Diego, CA",
        "arxiv_query": "Bing Ren single cell ATAC-seq epigenomics gene regulation",
    },
    # --- Quantum Computing ---
    {
        "professor_name": "Prof. John Preskill",
        "institution": "Caltech",
        "lab_name": "Institute for Quantum Information and Matter (IQIM)",
        "research_area": "Quantum error correction · quantum algorithms · near-term QC",
        "description": (
            "IQIM explores quantum computing theory and near-term device applications. "
            "Intern projects span quantum error correction codes, classical simulation of "
            "quantum circuits (using tensor networks), and variational quantum algorithms. "
            "Strong linear algebra and Python required; Qiskit/Cirq experience a plus."
        ),
        "desired_skills": ["Python", "linear algebra", "quantum computing", "Qiskit", "tensor networks"],
        "contact_email": None,
        "url": "https://iqim.caltech.edu",
        "program": "Summer Research Fellow",
        "region": "Pasadena, CA",
        "arxiv_query": "John Preskill quantum error correction fault tolerant",
    },
    # --- Graphics / Vision ---
    {
        "professor_name": "Prof. Alexei Efros",
        "institution": "UC Berkeley",
        "lab_name": "Berkeley AI Research (BAIR) — Vision",
        "research_area": "Image synthesis · diffusion models · self-supervised visual learning",
        "description": (
            "We work on generative models for images and video — GANs, diffusion, and "
            "self-supervised representation learning. Current projects include controllable "
            "generation, 3D-aware synthesis, and learning from internet-scale video."
        ),
        "desired_skills": ["Python", "PyTorch", "computer vision", "generative models", "CUDA"],
        "contact_email": None,
        "url": "https://people.eecs.berkeley.edu/~efros/",
        "program": "Research Intern",
        "region": "Berkeley, CA",
        "arxiv_query": "Alexei Efros diffusion models image synthesis self-supervised",
    },
]


async def run_research_pipeline(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    dry_run: bool,
    use_llm: bool,
) -> dict[str, int]:
    """Seed / refresh research opportunities from live Firecrawl + curated labs."""
    logger.info("=== RESEARCH OPPORTUNITIES PIPELINE ===")
    from app.llm.embeddings import embed

    inserted = updated = skipped = errors = 0

    # ---- Phase A: Live Firecrawl scraping (Tier 1 portals) ----
    firecrawl_opps: list[dict[str, Any]] = []
    if settings.FIRECRAWL_API_KEY and not dry_run:
        from app.sources.firecrawl_research import fetch_research_opportunities as _fc_fetch
        logger.info("Firecrawl: scraping %d Tier 1 research portals…", 12)
        firecrawl_opps = await _fc_fetch(settings.FIRECRAWL_API_KEY, _llm_with_cooldown)
        logger.info("Firecrawl: %d opportunities extracted", len(firecrawl_opps))
    else:
        if not settings.FIRECRAWL_API_KEY:
            logger.info("FIRECRAWL_API_KEY not set — using curated labs only")

    async with session_factory() as db:
        # ---- Upsert Firecrawl opportunities ----
        for opp_data in firecrawl_opps:
            try:
                existing = (
                    await db.execute(
                        select(ResearchOpportunity)
                        .where(
                            ResearchOpportunity.professor_name == opp_data["professor_name"],
                            ResearchOpportunity.institution == opp_data["institution"],
                        )
                    )
                ).scalar_one_or_none()

                if dry_run:
                    logger.info("[dry-run] firecrawl: %s @ %s", opp_data["professor_name"], opp_data["institution"])
                    inserted += 1
                    continue

                embed_text = (
                    f"{opp_data['professor_name']} {opp_data['institution']} "
                    f"{opp_data['research_area']}. {opp_data['description'][:500]}"
                )
                vectors = await embed([embed_text])
                embedding = vectors[0] if vectors else None

                if existing is None:
                    opp = ResearchOpportunity(
                        professor_name=opp_data["professor_name"],
                        institution=opp_data["institution"],
                        lab_name=opp_data.get("lab_name"),
                        research_area=opp_data["research_area"],
                        description=opp_data["description"],
                        desired_skills=opp_data.get("desired_skills", []),
                        program=opp_data.get("program"),
                        region=opp_data.get("region"),
                        contact_email=opp_data.get("contact_email"),
                        url=opp_data.get("url"),
                        source="firecrawl",
                        posted_at=datetime.now(UTC),
                        last_seen_at=datetime.now(UTC),
                        embedding=embedding,
                    )
                    db.add(opp)
                    await db.commit()
                    inserted += 1
                    logger.info("  [fc] inserted: %s @ %s", opp_data["professor_name"], opp_data["institution"])
                else:
                    existing.description = opp_data["description"]
                    existing.last_seen_at = datetime.now(UTC)
                    existing.source = "firecrawl"
                    if opp_data.get("desired_skills"):
                        existing.desired_skills = opp_data["desired_skills"]
                    if embedding:
                        existing.embedding = embedding
                    db.add(existing)
                    await db.commit()
                    updated += 1
                    logger.info("  [fc] updated: %s @ %s", opp_data["professor_name"], opp_data["institution"])

            except Exception as exc:  # noqa: BLE001
                logger.warning("firecrawl upsert failed %s: %s", opp_data.get("professor_name"), exc)
                await db.rollback()
                errors += 1

        # ---- Phase B: Curated labs (with arXiv enrichment) ----
        for lab in _RESEARCH_LABS:
            try:
                # Check if already in DB by professor_name + institution
                existing = (
                    await db.execute(
                        select(ResearchOpportunity)
                        .where(
                            ResearchOpportunity.professor_name == lab["professor_name"],
                            ResearchOpportunity.institution == lab["institution"],
                        )
                    )
                ).scalar_one_or_none()

                # ---- Fetch recent arXiv paper ----
                recent_paper: dict[str, Any] | None = None
                if lab.get("arxiv_query"):
                    recent_paper = await arxiv_recent_paper(lab["arxiv_query"])
                    if recent_paper:
                        logger.info(
                            "  arXiv: %s (%d) — %s",
                            recent_paper["title"][:60],
                            recent_paper["year"],
                            lab["professor_name"],
                        )

                # ---- LLM-enrich description if we have a recent paper ----
                description = lab["description"]
                if use_llm and recent_paper:
                    enriched_desc = await _llm_with_cooldown([
                        {
                            "role": "system",
                            "content": (
                                "You write concise, honest research lab descriptions for a student "
                                "internship platform. Use only facts from the provided context. "
                                "3-4 sentences max. No hype."
                            ),
                        },
                        {
                            "role": "user",
                            "content": (
                                f"Lab: {lab['lab_name']} at {lab['institution']}\n"
                                f"Research area: {lab['research_area']}\n"
                                f"Base description: {lab['description']}\n"
                                f"Recent publication: \"{recent_paper['title']}\" ({recent_paper['year']})\n\n"
                                "Write a 3-sentence description suitable for a student browsing research "
                                "opportunities. Mention the recent paper by title. Be specific."
                            ),
                        },
                    ])
                    if enriched_desc.strip():
                        description = enriched_desc.strip()

                if dry_run:
                    logger.info(
                        "[dry-run] would upsert: %s @ %s",
                        lab["professor_name"], lab["institution"],
                    )
                    inserted += 1
                    continue

                # ---- Compute embedding (rich text improves semantic match quality) ----
                embed_text = (
                    f"{lab['professor_name']} {lab['institution']} "
                    f"{lab['research_area']}. {lab['description'][:500]}"
                )
                vectors = await embed([embed_text])
                embedding = vectors[0] if vectors else None

                if existing is None:
                    opp = ResearchOpportunity(
                        professor_name=lab["professor_name"],
                        institution=lab["institution"],
                        lab_name=lab.get("lab_name"),
                        research_area=lab["research_area"],
                        description=description,
                        desired_skills=lab["desired_skills"],
                        program=lab.get("program"),
                        region=lab.get("region"),
                        contact_email=lab.get("contact_email"),
                        url=lab.get("url"),
                        source="pipeline",
                        posted_at=datetime.now(UTC),
                        last_seen_at=datetime.now(UTC),
                        recent_paper=recent_paper,
                        embedding=embedding,
                    )
                    db.add(opp)
                    await db.commit()
                    inserted += 1
                    logger.info("  inserted: %s @ %s", lab["professor_name"], lab["institution"])
                else:
                    # Update description, recent_paper, last_seen_at, embedding
                    existing.description = description
                    existing.last_seen_at = datetime.now(UTC)
                    if recent_paper:
                        existing.recent_paper = recent_paper
                    if embedding:
                        existing.embedding = embedding
                    db.add(existing)
                    await db.commit()
                    updated += 1
                    logger.info("  updated: %s @ %s", lab["professor_name"], lab["institution"])

            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "research_pipeline failed %s @ %s: %s",
                    lab.get("professor_name"), lab.get("institution"), exc,
                )
                await db.rollback()
                errors += 1

    logger.info(
        "Research pipeline done — inserted=%d  updated=%d  skipped=%d  errors=%d",
        inserted, updated, skipped, errors,
    )
    return {"inserted": inserted, "updated": updated, "skipped": skipped, "errors": errors}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main(args: argparse.Namespace) -> None:
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    t0 = time.monotonic()
    total_stats: dict[str, Any] = {}

    try:
        if not args.research_only:
            stats = await run_postings_pipeline(
                session_factory,
                dry_run=args.dry_run,
                use_llm=not args.no_llm,
            )
            total_stats["postings"] = stats

        if not args.postings_only:
            stats = await run_research_pipeline(
                session_factory,
                dry_run=args.dry_run,
                use_llm=not args.no_llm,
            )
            total_stats["research"] = stats

    finally:
        await engine.dispose()

    elapsed = time.monotonic() - t0
    logger.info("=== PIPELINE COMPLETE in %.1fs ===", elapsed)
    for section, stats in total_stats.items():
        logger.info("  [%s] %s", section, "  ".join(f"{k}={v}" for k, v in stats.items()))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="InternPilot live data pipeline")
    parser.add_argument("--dry-run", action="store_true", help="Fetch + filter only, no DB writes")
    parser.add_argument("--no-llm", action="store_true", help="Skip LLM enrichment (faster, no API cost)")
    parser.add_argument("--research-only", action="store_true", help="Only run research opportunities pipeline")
    parser.add_argument("--postings-only", action="store_true", help="Only run postings pipeline")
    args = parser.parse_args()

    asyncio.run(main(args))
