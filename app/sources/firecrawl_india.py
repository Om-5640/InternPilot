"""Firecrawl-powered scraper for Indian internship sites.

Scrapes Internshala and LetsIntern using Firecrawl's JavaScript-rendering
API, extracts structured listings via LLM, and normalises them to RawPosting.

Silently skips (returns []) if FIRECRAWL_API_KEY is not set.
Called from AggregationService.refresh() alongside other sources.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

import httpx

from app.sources.base import RawPosting
from app.sources.normalize import build_dedup_key, detect_work_mode

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pages to scrape — keep small so we don't exhaust Firecrawl free quota
# ---------------------------------------------------------------------------
_INDIA_PAGES: list[dict[str, str]] = [
    {
        "url": "https://internshala.com/internships/computer-science-internship/",
        "source": "internshala",
        "category": "Computer Science",
    },
    {
        "url": "https://internshala.com/internships/web-development-internship/",
        "source": "internshala",
        "category": "Web Development",
    },
    {
        "url": "https://internshala.com/internships/data-science-internship/",
        "source": "internshala",
        "category": "Data Science",
    },
    {
        "url": "https://internshala.com/internships/machine-learning-internship/",
        "source": "internshala",
        "category": "Machine Learning",
    },
    {
        "url": "https://internshala.com/internships/python-internship/",
        "source": "internshala",
        "category": "Python",
    },
    {
        "url": "https://letsintern.com/internships",
        "source": "letsintern",
        "category": "General Tech",
    },
]

# INR to USD conversion rate (approximate)
_INR_USD = 83.0

_FIRECRAWL_BASE = "https://api.firecrawl.dev/v1"
_SCRAPE_TIMEOUT = 55.0
_BETWEEN_SCRAPES = 2.0
_MAX_PAGES_PER_RUN = 6  # cap to preserve Firecrawl free quota

# ---------------------------------------------------------------------------
# Indian location normalisation
# ---------------------------------------------------------------------------
_INDIA_CITIES: dict[str, str] = {
    "bangalore": "Bangalore, India",
    "bengaluru": "Bangalore, India",
    "mumbai": "Mumbai, India",
    "bombay": "Mumbai, India",
    "delhi": "New Delhi, India",
    "new delhi": "New Delhi, India",
    "gurgaon": "Gurgaon, India",
    "gurugram": "Gurgaon, India",
    "noida": "Noida, India",
    "hyderabad": "Hyderabad, India",
    "pune": "Pune, India",
    "chennai": "Chennai, India",
    "madras": "Chennai, India",
    "kolkata": "Kolkata, India",
    "calcutta": "Kolkata, India",
    "ahmedabad": "Ahmedabad, India",
    "jaipur": "Jaipur, India",
    "chandigarh": "Chandigarh, India",
    "lucknow": "Lucknow, India",
    "indore": "Indore, India",
    "bhopal": "Bhopal, India",
    "kochi": "Kochi, India",
    "cochin": "Kochi, India",
    "visakhapatnam": "Visakhapatnam, India",
    "coimbatore": "Coimbatore, India",
    "vadodara": "Vadodara, India",
    "surat": "Surat, India",
    "nagpur": "Nagpur, India",
    "thiruvananthapuram": "Thiruvananthapuram, India",
    "trivandrum": "Thiruvananthapuram, India",
    "mysore": "Mysore, India",
    "mysuru": "Mysore, India",
}


def _normalise_india_location(raw: str) -> tuple[str, str]:
    """Return (location, work_mode) for an Indian internship location string."""
    low = raw.strip().lower()
    if any(w in low for w in ("work from home", "remote", "wfh", "online", "virtual", "anywhere")):
        return "Remote", "remote"
    if "hybrid" in low:
        for city, canonical in _INDIA_CITIES.items():
            if city in low:
                return canonical, "hybrid"
        return "Hybrid, India", "hybrid"
    for city, canonical in _INDIA_CITIES.items():
        if city in low:
            return canonical, "onsite"
    return raw.strip() or "India", "onsite"


def _parse_inr_stipend(raw: str) -> int | None:
    """Parse '₹15,000/month', 'Rs. 10000 per month', etc. → USD (approx)."""
    clean = raw.lower().replace(",", "").replace("₹", "rs ")
    # Match INR amounts
    m = re.search(
        r"(?:rs\.?\s*|inr\s*|rupees?\s*)(\d+(?:\.\d+)?)\s*(?:k\b)?",
        clean,
    )
    if not m:
        # Also try bare numbers preceded by ₹ in the original
        m = re.search(r"(\d{4,6})", clean)
    if not m:
        return None
    val = float(m.group(1).replace(",", ""))
    if "k" in clean[m.start():m.end() + 2]:
        val *= 1000
    # If the value looks like INR (>=1000), convert to USD
    if val >= 500:  # noqa: PLR2004
        usd = round(val / _INR_USD)
        return usd if usd > 0 else None
    # Small numbers might already be USD
    return int(val) if val > 0 else None


# ---------------------------------------------------------------------------
# Firecrawl scrape
# ---------------------------------------------------------------------------


async def _firecrawl_scrape(url: str, api_key: str) -> str:
    """Scrape a URL via Firecrawl with JavaScript rendering enabled."""
    try:
        async with httpx.AsyncClient(timeout=_SCRAPE_TIMEOUT) as client:
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
                    "waitFor": 2500,   # wait for JS-rendered listings
                    "timeout": 45000,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            if not data.get("success"):
                logger.warning("Firecrawl failed for %s: %s", url, data.get("error"))
                return ""
            return str(data.get("data", {}).get("markdown") or "")
    except httpx.HTTPStatusError as exc:
        logger.warning("Firecrawl HTTP %s for %s", exc.response.status_code, url)
        return ""
    except Exception as exc:  # noqa: BLE001
        logger.warning("Firecrawl error for %s: %s", url, exc)
        return ""


# ---------------------------------------------------------------------------
# LLM extraction
# ---------------------------------------------------------------------------

_EXTRACT_SYSTEM = """You extract internship listings from scraped website markdown for a student career platform.

Given markdown from an Indian internship site (Internshala, LetsIntern, etc.), extract ALL specific
internship listings visible on the page.

Return a JSON array. Each element MUST have these exact fields:
{
  "title": "Job title, must contain 'intern' or 'internship' (e.g. 'Python Developer Internship')",
  "company_name": "Company name exactly as shown",
  "location": "City name, or 'Work From Home', or 'Remote' (e.g. 'Bangalore', 'Mumbai', 'Work From Home')",
  "stipend_text": "Raw stipend string as shown (e.g. '₹15,000/month', 'Rs. 10,000 - 15,000/month', 'Unpaid', ''),
  "apply_url": "Direct URL to this specific listing (must be a full https:// URL, not a relative path)",
  "skills": ["skill1", "skill2"],
  "description": "1-2 sentence description of what the intern will do (from the listing text)"
}

Critical rules:
- Only extract REAL listings with a company name and title
- apply_url MUST be a complete https:// URL for the specific listing (e.g. https://internshala.com/internship/detail/...)
- If the listing has no direct URL, use the source page URL as fallback
- Do NOT fabricate URLs, company names, or skills
- If stipend is 'Unpaid' or not mentioned, set stipend_text to ''
- skills should be domain-specific technical skills extracted from the listing
- title must sound like an internship (contains 'intern', 'trainee', 'apprentice')
- Extract up to 15 listings maximum; prefer tech/engineering/data roles
- If a listing is clearly incomplete (no company name), skip it

Return ONLY the JSON array, no markdown fences, no explanations."""


async def _llm_extract_listings(
    markdown: str,
    page_meta: dict[str, str],
    llm_fn: Any,
) -> list[dict[str, Any]]:
    """Extract internship listings from scraped markdown via LLM."""
    trimmed = markdown[:8000] if len(markdown) > 8000 else markdown

    user_msg = (
        f"Source: {page_meta.get('source', 'internshala')}\n"
        f"Category: {page_meta.get('category', 'Tech')}\n"
        f"Page URL: {page_meta.get('url', '')}\n\n"
        f"--- Page content ---\n{trimmed}"
    )

    try:
        raw = await llm_fn([
            {"role": "system", "content": _EXTRACT_SYSTEM},
            {"role": "user", "content": user_msg},
        ])
        text = raw.strip()

        # Strip markdown code fences
        fence = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
        if fence:
            text = fence.group(1)
        else:
            bracket = re.search(r"\[.*\]", text, re.DOTALL)
            if bracket:
                text = bracket.group(0)

        parsed = json.loads(text)
        return [e for e in parsed if isinstance(e, dict)] if isinstance(parsed, list) else []
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM extract failed for %s: %s", page_meta.get("url"), exc)
        return []


# ---------------------------------------------------------------------------
# Normaliser
# ---------------------------------------------------------------------------

_URL_SCHEME_RE = re.compile(r"^https?://")


def _normalise_listing(raw: dict[str, Any], page_meta: dict[str, str]) -> RawPosting | None:
    """Validate and normalise one extracted listing → RawPosting."""
    title = str(raw.get("title") or "").strip()
    company = str(raw.get("company_name") or "").strip()
    if not title or not company:
        return None
    # Must look like an internship
    if not re.search(r"\b(intern|internship|trainee|apprentice)\b", title, re.IGNORECASE):
        return None

    raw_loc = str(raw.get("location") or "").strip()
    location, work_mode = _normalise_india_location(raw_loc) if raw_loc else ("India", "any")

    # Combine title + description for work_mode detection if not clear
    combined_text = f"{title} {raw.get('description', '')} {raw_loc}"
    if work_mode == "any":
        work_mode = detect_work_mode(combined_text)

    # Stipend
    stipend: int | None = None
    stipend_text = str(raw.get("stipend_text") or "").strip()
    if stipend_text and stipend_text.lower() not in ("unpaid", "no stipend", ""):
        stipend = _parse_inr_stipend(stipend_text)

    # Apply URL — must be a real https:// URL
    apply_url = str(raw.get("apply_url") or "").strip()
    if not _URL_SCHEME_RE.match(apply_url):
        apply_url = page_meta.get("url", "")
    if not apply_url:
        return None

    # Skills → requirements
    skills_raw = raw.get("skills") or []
    requirements: list[str] = [str(s).strip() for s in skills_raw if isinstance(s, str) and s.strip()][:8]

    description = str(raw.get("description") or "").strip()
    if len(description) < 20:  # noqa: PLR2004
        description = f"{title} internship at {company}."

    return {
        "title": title,
        "company_name": company,
        "description": description,
        "source": page_meta.get("source", "internshala"),
        "source_url": apply_url,
        "location": location,
        "work_mode": work_mode,
        "stipend": stipend,
        "posted_at": datetime.now(UTC).isoformat(),
        "requirements": requirements,
    }


# ---------------------------------------------------------------------------
# Source class
# ---------------------------------------------------------------------------


class IndiaFirecrawlSource:
    """Scrapes Indian internship sites via Firecrawl + LLM extraction."""

    name = "india_firecrawl"

    def __init__(self, api_key: str, llm_fn: Any | None = None) -> None:
        self._api_key = api_key
        self._llm_fn = llm_fn  # async callable (messages) → str

    async def fetch(self) -> list[RawPosting]:
        if not self._api_key:
            return []
        if self._llm_fn is None:
            return []

        results: list[RawPosting] = []
        seen_dedup: set[str] = set()

        pages = _INDIA_PAGES[:_MAX_PAGES_PER_RUN]
        for page_meta in pages:
            url = page_meta["url"]
            logger.info("India scrape → %s", url)

            markdown = await _firecrawl_scrape(url, self._api_key)
            if not markdown or len(markdown) < 100:  # noqa: PLR2004
                logger.warning("  No usable content from %s — skipping", url)
                await asyncio.sleep(_BETWEEN_SCRAPES)
                continue

            logger.info("  %d chars — extracting listings…", len(markdown))
            raw_entries = await _llm_extract_listings(markdown, page_meta, self._llm_fn)
            logger.info("  %d raw entries", len(raw_entries))

            page_count = 0
            for raw in raw_entries:
                normalised = _normalise_listing(raw, page_meta)
                if not normalised:
                    continue
                dedup = build_dedup_key(normalised["company_name"], normalised["title"], normalised["location"])
                if dedup in seen_dedup:
                    continue
                seen_dedup.add(dedup)
                results.append(normalised)
                page_count += 1

            logger.info("  %d accepted from %s", page_count, url)
            await asyncio.sleep(_BETWEEN_SCRAPES)

        logger.info("India source: %d total listings", len(results))
        return results
