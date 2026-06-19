"""Normalize raw postings → Posting-ready dicts and company names."""
from __future__ import annotations

import hashlib
import html
import re
from datetime import UTC, datetime
from typing import Any

from app.sources.base import RawPosting

_LEGAL_SUFFIX = re.compile(
    r"\b(llc|inc|corp|ltd|co|company|technologies|tech|labs|lab|ai|hq)\b\.?",
    re.IGNORECASE,
)
_NON_ALNUM = re.compile(r"[^a-z0-9]")


def normalize_company_name(name: str) -> str:
    """Lowercase, strip legal suffixes and punctuation."""
    cleaned = _LEGAL_SUFFIX.sub("", name)
    return _NON_ALNUM.sub("", cleaned.lower()).strip()


def build_dedup_key(company: str, title: str, location: str | None) -> str:
    parts = "|".join([
        _NON_ALNUM.sub("", company.lower()),
        _NON_ALNUM.sub("", title.lower()),
        _NON_ALNUM.sub("", (location or "").lower()),
    ])
    return hashlib.sha256(parts.encode()).hexdigest()[:24]


def detect_work_mode(text: str) -> str:
    lower = text.lower()
    has_remote = "remote" in lower or "distributed team" in lower or "work from anywhere" in lower
    has_hybrid = "hybrid" in lower
    has_onsite = any(w in lower for w in ("on-site", "onsite", "in-person", "in office", "in-office"))
    if has_remote and (has_hybrid or has_onsite):
        return "hybrid"
    if has_hybrid:
        return "hybrid"
    if has_remote:
        return "remote"
    if has_onsite:
        return "onsite"
    return "any"


_INR_USD = 83.0

# Matches: $2,000/month  $2k/month  $25/hr
_USD_PAY_RE = re.compile(
    r"\$\s*(\d{1,4}(?:,\d{3})*|\d+)\s*(k|,000)?\s*"
    r"(?:per month|/month|/mo|pm\b|p\.m\.|per hour|/hr|/hour|hourly)?",
    re.IGNORECASE,
)
# Matches: ₹15,000/month  Rs 10000/month  INR 12000 per month  15000 INR/month
_INR_PAY_RE = re.compile(
    r"(?:₹|rs\.?\s+|inr\s+|rupees?\s+)(\d{1,3}(?:,\d{3})*|\d+)\s*(k|,000)?\b"
    r"|(\d{1,3}(?:,\d{3})*|\d+)\s*(k)?\s*(?:inr|rupees?)(?:\s*/\s*month)?",
    re.IGNORECASE,
)


def extract_stipend(text: str) -> int | None:
    """
    Extract monthly stipend from job description text.
    Returns USD integer or None.
    Converts INR → USD at approx 83:1.
    """
    # Check USD first
    m = _USD_PAY_RE.search(text)
    if m:
        raw = m.group(1).replace(",", "")
        val = float(raw)
        if m.group(2):          # "k" or ",000" suffix
            val *= 1000
        # Check if hourly rate within the matched + surrounding text
        window = text[max(0, m.start() - 4):m.end() + 12].lower()
        if "/hr" in window or "hourly" in window or "per hour" in window:
            val = val * 160     # 160 hr/month
        if 200 <= val <= 20_000:  # noqa: PLR2004 — sane monthly USD range
            return int(val)

    # Check INR
    m = _INR_PAY_RE.search(text)
    if m:
        raw = (m.group(1) or m.group(3) or "0").replace(",", "")
        val = float(raw)
        suffix = m.group(2) or m.group(4) or ""
        if suffix and suffix.lower() in ("k", ",000"):
            val *= 1000
        if val >= 1000:  # noqa: PLR2004 — looks like INR
            usd = round(val / _INR_USD)
            if 10 <= usd <= 2000:  # noqa: PLR2004 — sane range after conversion
                return usd

    return None


def extract_requirements(description: str) -> list[str]:
    # Find a requirements/qualifications section
    pattern = re.compile(
        r"(?:Requirements?|Qualifications?|What you[''']ll need|You[''']ll need|Must[ -]have)[:\s]*\n"
        r"((?:.+\n?)+?)(?:\n\n|\Z)",
        re.IGNORECASE,
    )
    m = pattern.search(description)
    if not m:
        return []
    block = m.group(1)
    bullets = re.split(r"\n[•\-\*]\s*|\n\d+\.\s*|\n", block)
    return [b.strip() for b in bullets if 10 < len(b.strip()) < 300][:10]


def strip_html(text: str) -> str:
    """Remove HTML tags and decode entities."""
    cleaned = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = html.unescape(cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _parse_date(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)
    except (ValueError, TypeError):
        return None


def normalize(raw: RawPosting) -> dict[str, Any]:
    """Convert a RawPosting to a dict of Posting fields (no id/company_id)."""
    title = raw["title"].strip()
    description = raw.get("description") or ""
    location = raw.get("location")
    raw_wm = raw.get("work_mode")

    work_mode: str = raw_wm or detect_work_mode(f"{title} {location or ''} {description}")

    requirements = raw.get("requirements") or extract_requirements(description)

    dedup_key = build_dedup_key(raw["company_name"], title, location)

    # Prefer source-provided stipend; fall back to heuristic extraction from description
    stipend = raw.get("stipend")
    if stipend is None and description:
        stipend = extract_stipend(description)

    return {
        "title": title,
        "description": description,
        "requirements": requirements,
        "location": location,
        "work_mode": work_mode,
        "stipend": stipend,
        "source": raw["source"],
        "source_url": raw["source_url"],
        "posted_at": _parse_date(raw.get("posted_at")),
        "last_seen_at": datetime.now(UTC),
        "status": "active",
        "ghost_score": 0.0,
        "is_ghost": False,
        "dedup_key": dedup_key,
    }
