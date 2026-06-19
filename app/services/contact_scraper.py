"""Firecrawl-powered contact discovery for the referral pipeline.

When the contacts_alumni table has no entries for a company, this module
scrapes the company's LinkedIn people page (and falls back to their team/
about page) to populate real contacts.

Strategy:
  1. LinkedIn company people page — publicly visible without login
  2. Company's own /team or /about page (derived from company name → domain guess)
  3. Gracefully return [] if both fail or FIRECRAWL_API_KEY is not set

Contacts are saved with source='firecrawl' and relationship='second_degree'
(since we don't have confirmed alumni data).
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.contact import Contact, RelationshipType
from app.services.university_normalizer import canonicalize as _canonicalize_uni

logger = logging.getLogger(__name__)

_FIRECRAWL_BASE = "https://api.firecrawl.dev/v1"
_SCRAPE_TIMEOUT = 55.0

# ---------------------------------------------------------------------------
# LinkedIn slug derivation
# ---------------------------------------------------------------------------

_NON_ALPHANUM = re.compile(r"[^a-z0-9\s-]")
_MULTI_SPACE = re.compile(r"\s+")


def _linkedin_slug(company_name: str) -> str:
    """Derive a best-guess LinkedIn company URL slug from company name."""
    slug = company_name.lower()
    slug = _NON_ALPHANUM.sub("", slug)
    slug = _MULTI_SPACE.sub("-", slug).strip("-")
    return slug


# ---------------------------------------------------------------------------
# Firecrawl scrape
# ---------------------------------------------------------------------------


async def _firecrawl_scrape(url: str) -> str:
    """Scrape a URL via Firecrawl. Returns empty string on failure."""
    if not settings.FIRECRAWL_API_KEY:
        return ""
    try:
        async with httpx.AsyncClient(timeout=_SCRAPE_TIMEOUT) as client:
            resp = await client.post(
                f"{_FIRECRAWL_BASE}/scrape",
                headers={
                    "Authorization": f"Bearer {settings.FIRECRAWL_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "url": url,
                    "formats": ["markdown"],
                    "onlyMainContent": True,
                    "waitFor": 3000,
                    "timeout": 45000,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            if not data.get("success"):
                return ""
            md = str(data.get("data", {}).get("markdown") or "")
            # If LinkedIn returned a sign-in prompt, it's useless
            if "sign in" in md.lower()[:500] and "linkedin" in url.lower():
                logger.info("LinkedIn returned login page for %s — skipping", url)
                return ""
            return md
    except Exception as exc:  # noqa: BLE001
        logger.warning("Firecrawl scrape error (%s): %s", url, exc)
        return ""


# ---------------------------------------------------------------------------
# LLM extraction
# ---------------------------------------------------------------------------

_EXTRACT_SYSTEM = """You extract professional contact information from website content for a student referral platform.

Given markdown from a company's LinkedIn people page or team page, extract real employees
who could serve as referrals for a student internship applicant.

Return a JSON array. Each element:
{
  "name": "Full name of the person",
  "role": "Current job title at the company (e.g. 'Senior Software Engineer', 'Engineering Manager')",
  "university": "University they attended if visible (null if not mentioned)",
  "grad_year": integer graduation year if visible (null if not mentioned),
  "linkedin_url": "Full LinkedIn profile URL if available (null otherwise)"
}

Rules:
- Only extract REAL people with a name and role
- Prefer engineering, product, and technical roles (most relevant for tech interns)
- Extract up to 12 people maximum
- Do NOT fabricate names, roles, universities, or LinkedIn URLs
- If university/grad_year are not visible on the page, set them to null
- Skip generic entries like "LinkedIn Member" with no real name
- If the page has no employee data (just marketing text), return []

Return ONLY the JSON array, no markdown fences."""


async def _llm_extract_contacts(
    markdown: str,
    company_name: str,
    llm_fn: Any,
) -> list[dict[str, Any]]:
    """Extract contact data from scraped markdown via LLM."""
    trimmed = markdown[:6000]
    user_msg = (
        f"Company: {company_name}\n\n"
        f"--- Page content ---\n{trimmed}"
    )
    try:
        raw = await llm_fn([
            {"role": "system", "content": _EXTRACT_SYSTEM},
            {"role": "user", "content": user_msg},
        ])
        text = raw.strip()
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
        logger.warning("Contact LLM extract failed for %s: %s", company_name, exc)
        return []


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def discover_contacts(
    company_id: uuid.UUID,
    company_name: str,
    db: AsyncSession,
    *,
    llm_fn: Any | None = None,
) -> list[Contact]:
    """
    Scrape LinkedIn and company team pages to find potential referral contacts.

    Saves discovered contacts to the contacts_alumni table with source='firecrawl'.
    Returns the list of newly saved Contact objects (may be empty).

    Only runs if FIRECRAWL_API_KEY is configured. Silently returns [] otherwise.
    """
    if not settings.FIRECRAWL_API_KEY:
        logger.info("FIRECRAWL_API_KEY not set — skipping contact discovery for %s", company_name)
        return []

    if llm_fn is None:
        from app.llm.router import complete as _complete
        llm_fn = _complete

    slug = _linkedin_slug(company_name)
    markdown = ""

    # --- Attempt 1: LinkedIn company people page ---
    linkedin_people_url = f"https://www.linkedin.com/company/{slug}/people/"
    logger.info("Contact discovery: trying LinkedIn people page for %s", company_name)
    markdown = await _firecrawl_scrape(linkedin_people_url)

    # --- Attempt 2: LinkedIn main company page ---
    if not markdown or len(markdown) < 150:  # noqa: PLR2004
        linkedin_url = f"https://www.linkedin.com/company/{slug}/"
        logger.info("Contact discovery: trying LinkedIn main page for %s", company_name)
        markdown = await _firecrawl_scrape(linkedin_url)

    if not markdown or len(markdown) < 150:  # noqa: PLR2004
        logger.info("Contact discovery: no usable content found for %s", company_name)
        return []

    logger.info("Contact discovery: %d chars scraped for %s — extracting…", len(markdown), company_name)
    raw_contacts = await _llm_extract_contacts(markdown, company_name, llm_fn)
    logger.info("Contact discovery: %d raw contacts extracted for %s", len(raw_contacts), company_name)

    saved: list[Contact] = []
    for c in raw_contacts:
        name = str(c.get("name") or "").strip()
        role = str(c.get("role") or "").strip() or None
        if not name or name.lower() in ("linkedin member", "unknown", ""):
            continue

        # Check for duplicate by name + company
        existing = (
            await db.execute(
                select(Contact).where(
                    Contact.company_id == company_id,
                    Contact.name == name,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            saved.append(existing)
            continue

        university = str(c.get("university") or "").strip() or None
        grad_year_raw = c.get("grad_year")
        grad_year: int | None = int(grad_year_raw) if grad_year_raw and str(grad_year_raw).isdigit() else None
        linkedin_url = str(c.get("linkedin_url") or "").strip() or None
        if linkedin_url and not linkedin_url.startswith("http"):
            linkedin_url = None

        try:
            contact = Contact(
                name=name,
                company_id=company_id,
                role=role,
                grad_year=grad_year,
                university=university,
                university_canonical=_canonicalize_uni(university) if university else None,
                linkedin=linkedin_url,
                relationship=RelationshipType.second_degree,
                source="firecrawl",
            )
            db.add(contact)
            await db.flush()
            saved.append(contact)
            logger.info("  Saved contact: %s (%s) at %s", name, role, company_name)
        except Exception as exc:  # noqa: BLE001
            logger.warning("  Failed to save contact %s: %s", name, exc)
            await db.rollback()

    if saved:
        await db.commit()
        logger.info("Contact discovery: saved %d contacts for %s", len(saved), company_name)

    return saved
