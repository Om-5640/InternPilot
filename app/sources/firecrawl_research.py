"""Firecrawl-powered research internship scraper.

Scrapes Tier 1 research program portals using Firecrawl's markdown API,
then extracts structured research opportunity data via the LLM router.

Silently skips if FIRECRAWL_API_KEY is not set.
Usage: called from scripts/live_data_pipeline.py run_research_pipeline()
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tier 1 program pages — high-quality structured research portals
# ---------------------------------------------------------------------------
_PROGRAM_PAGES: list[dict[str, str]] = [
    {
        "url": "https://surf.caltech.edu/",
        "program": "SURF",
        "institution": "Caltech",
        "region": "Pasadena, CA",
    },
    {
        "url": "https://amgenscholars.com/",
        "program": "Amgen Scholars",
        "institution": "Multiple Universities",
        "region": "USA / International",
    },
    {
        "url": "https://www.mitacs.ca/en/programs/globalink/research-internship/",
        "program": "MITACS Globalink",
        "institution": "Canadian Universities",
        "region": "Canada",
    },
    {
        "url": "https://www.daad.de/rise/en/",
        "program": "DAAD RISE",
        "institution": "German Universities / Research Institutes",
        "region": "Germany",
    },
    {
        "url": "https://science.osti.gov/wdts/suli",
        "program": "SULI (DOE)",
        "institution": "DOE National Laboratories",
        "region": "USA (various national labs)",
    },
    {
        "url": "https://www.jncasr.ac.in/public_html/education-training/summer-research-fellowship/",
        "program": "JNCASR SRF",
        "institution": "JNCASR",
        "region": "Bangalore, India",
    },
    {
        "url": "https://www.ias.ac.in/Initiatives/Summer_Research_Fellowship/",
        "program": "IAS SRF",
        "institution": "Indian Academy of Sciences",
        "region": "India (various institutes)",
    },
    {
        "url": "https://surge.iitk.ac.in/",
        "program": "IIT SURGE",
        "institution": "IIT Kanpur",
        "region": "Kanpur, India",
    },
    {
        "url": "https://www.prl.res.in/prl-eng/student_internship",
        "program": "PRL Student Internship",
        "institution": "Physical Research Laboratory",
        "region": "Ahmedabad, India",
    },
    {
        "url": "https://new.nsf.gov/funding/opportunities/research-experiences-undergraduates-reu",
        "program": "NSF REU",
        "institution": "US Universities",
        "region": "USA (various)",
    },
    {
        "url": "https://jobs.sciencecareers.org/jobs/research-internships/",
        "program": "Science Careers",
        "institution": "Various Research Institutions",
        "region": "USA / International",
    },
    {
        "url": "https://www.cern.ch/careers/student-opportunities/summer-student-programme",
        "program": "CERN Summer Student",
        "institution": "CERN",
        "region": "Geneva, Switzerland",
    },
]

_FIRECRAWL_BASE = "https://api.firecrawl.dev/v1"
_SCRAPE_TIMEOUT_SECS = 50.0
_BETWEEN_SCRAPES_SECS = 1.5

# ---------------------------------------------------------------------------
# LLM extraction system prompt
# ---------------------------------------------------------------------------
_EXTRACT_SYSTEM = """You are a research internship data extractor for a student career platform.

Given scraped markdown from a research program or internship portal page, extract ALL
specific research internship / fellowship opportunities mentioned.

Return a JSON array. Each element MUST have these exact fields:
{
  "professor_name": "Specific professor name, 'Program Director', or 'Program Team' if none listed",
  "institution": "University, lab, or research institution full name",
  "lab_name": "Lab, department, or sub-program name (null if not mentioned)",
  "research_area": "Specific research field/domain — 2-6 words (e.g. 'Machine Learning', 'Organic Chemistry', 'Particle Physics')",
  "description": "2-4 sentence factual description of intern work, research focus, and learning outcomes",
  "desired_skills": ["specific skill 1", "skill 2"],
  "contact_email": "email@domain.com or null",
  "url": "direct application/info URL or null",
  "program": "Program name (e.g. 'SURF', 'NSF REU', 'DAAD RISE', 'MITACS Globalink')",
  "region": "Location — city + country or 'Remote' or 'USA (various)'"
}

Critical rules:
- Only extract REAL, specific opportunities with enough detail to be useful to students
- Do NOT fabricate email addresses, skills, or research areas
- Keep descriptions factual — only what is stated on the page
- For program-level pages (e.g., DAAD RISE, MITACS), create 2-4 entries covering the
  main research domains/fields available (e.g., Physics, Chemistry, Biology, CS)
- For pages listing specific labs/professors, extract one entry per lab
- desired_skills must be relevant and domain-specific (not generic like 'teamwork')
- If truly no research internship info is present, return []

Return ONLY the JSON array, no markdown fences, no explanations."""

# ---------------------------------------------------------------------------
# Firecrawl scrape
# ---------------------------------------------------------------------------


async def _firecrawl_scrape(url: str, api_key: str) -> str:
    """Scrape a URL via Firecrawl API and return markdown content."""
    try:
        async with httpx.AsyncClient(timeout=_SCRAPE_TIMEOUT_SECS) as client:
            resp = await client.post(
                f"{_FIRECRAWL_BASE}/scrape",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "url": url,
                    "formats": ["markdown"],
                    "onlyMainContent": True,
                    "timeout": 35000,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            if not data.get("success"):
                logger.warning("Firecrawl scrape not successful for %s: %s", url, data.get("error"))
                return ""
            return str(data.get("data", {}).get("markdown") or "")
    except httpx.HTTPStatusError as exc:
        logger.warning("Firecrawl HTTP %s for %s: %s", exc.response.status_code, url, exc)
        return ""
    except Exception as exc:  # noqa: BLE001
        logger.warning("Firecrawl error for %s: %s", url, exc)
        return ""


# ---------------------------------------------------------------------------
# LLM extraction
# ---------------------------------------------------------------------------


async def _llm_extract(
    markdown: str,
    page_meta: dict[str, str],
    llm_fn: Any,
) -> list[dict[str, Any]]:
    """Extract structured research opportunities from scraped markdown via LLM."""
    trimmed = markdown[:6000] if len(markdown) > 6000 else markdown

    user_msg = (
        f"Program: {page_meta.get('program', 'Unknown')}\n"
        f"Institution: {page_meta.get('institution', 'Unknown')}\n"
        f"Region: {page_meta.get('region', 'Unknown')}\n"
        f"Source URL: {page_meta.get('url', '')}\n\n"
        f"--- Page content ---\n{trimmed}"
    )

    try:
        raw_response = await llm_fn([
            {"role": "system", "content": _EXTRACT_SYSTEM},
            {"role": "user", "content": user_msg},
        ])
        text = raw_response.strip()

        # Strip markdown code fence if present
        fence_match = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
        if fence_match:
            text = fence_match.group(1)
        else:
            bracket_match = re.search(r"\[.*\]", text, re.DOTALL)
            if bracket_match:
                text = bracket_match.group(0)

        parsed = json.loads(text)
        if not isinstance(parsed, list):
            return []
        return [entry for entry in parsed if isinstance(entry, dict)]
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM extraction failed for %s: %s", page_meta.get("url"), exc)
        return []


# ---------------------------------------------------------------------------
# Normalizer
# ---------------------------------------------------------------------------


def _normalize_entry(raw: dict[str, Any], page_meta: dict[str, str]) -> dict[str, Any] | None:
    """Validate and normalize a raw extracted research opportunity."""
    professor_name = str(raw.get("professor_name") or "").strip()
    institution = str(raw.get("institution") or "").strip()
    research_area = str(raw.get("research_area") or "").strip()
    description = str(raw.get("description") or "").strip()

    if not professor_name or not institution or not research_area:
        return None
    if len(description) < 60:
        return None

    skills_raw = raw.get("desired_skills", [])
    skills: list[str] = [str(s).strip() for s in (skills_raw if isinstance(skills_raw, list) else [])]
    skills = [s for s in skills if 2 < len(s) < 80]

    lab_name = str(raw.get("lab_name") or "").strip() or None

    email = str(raw.get("contact_email") or "").strip()
    contact_email = email if "@" in email else None

    raw_url = str(raw.get("url") or "").strip()
    if not raw_url.startswith(("http://", "https://")):
        raw_url = page_meta.get("url", "")
    url: str | None = raw_url or None

    program = str(raw.get("program") or page_meta.get("program", "")).strip() or None
    region = str(raw.get("region") or page_meta.get("region", "")).strip() or None

    return {
        "professor_name": professor_name,
        "institution": institution,
        "lab_name": lab_name,
        "research_area": research_area,
        "description": description,
        "desired_skills": skills,
        "contact_email": contact_email,
        "url": url,
        "program": program,
        "region": region,
        "source": "firecrawl",
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def fetch_research_opportunities(
    api_key: str,
    llm_fn: Any,
    *,
    max_pages: int | None = None,
) -> list[dict[str, Any]]:
    """Scrape Tier 1 research program pages and extract structured opportunities.

    Silently returns [] if api_key is empty.
    Each page is scraped, LLM-extracted, normalized, and deduplicated.
    """
    if not api_key:
        logger.info("FIRECRAWL_API_KEY not set — skipping live research scraping")
        return []

    pages = _PROGRAM_PAGES if max_pages is None else _PROGRAM_PAGES[:max_pages]
    all_opportunities: list[dict[str, Any]] = []
    seen: set[str] = set()  # dedup by (professor_name, institution)

    for page_meta in pages:
        url = page_meta["url"]
        logger.info("Firecrawl → %s", url)

        markdown = await _firecrawl_scrape(url, api_key)
        if not markdown or len(markdown) < 80:
            logger.warning("  No content from %s — skipping", url)
            await asyncio.sleep(_BETWEEN_SCRAPES_SECS)
            continue

        logger.info("  %d chars scraped — extracting…", len(markdown))
        raw_entries = await _llm_extract(markdown, page_meta, llm_fn)
        logger.info("  %d raw entries extracted", len(raw_entries))

        page_count = 0
        for raw in raw_entries:
            normalized = _normalize_entry(raw, page_meta)
            if not normalized:
                continue
            key = f"{normalized['professor_name'].lower()}|{normalized['institution'].lower()}"
            if key in seen:
                continue
            seen.add(key)
            all_opportunities.append(normalized)
            page_count += 1

        logger.info("  %d opportunities accepted from %s", page_count, url)
        await asyncio.sleep(_BETWEEN_SCRAPES_SECS)

    logger.info(
        "Firecrawl research: %d total opportunities from %d pages",
        len(all_opportunities),
        len(pages),
    )
    return all_opportunities
