"""Normalize raw postings → Posting-ready dicts and company names."""
from __future__ import annotations

import hashlib
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
    return hashlib.sha256(parts.encode()).hexdigest()[:16]


def detect_work_mode(text: str) -> str:
    lower = text.lower()
    has_remote = "remote" in lower
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


def extract_requirements(description: str) -> list[str]:
    # Find a requirements/qualifications section
    pattern = re.compile(
        r"(?:Requirements?|Qualifications?|What you.ll need|You.ll need|Must.have)[:\s]*\n"
        r"((?:.+\n?)+?)(?:\n\n|\Z)",
        re.IGNORECASE,
    )
    m = pattern.search(description)
    if not m:
        return []
    block = m.group(1)
    bullets = re.split(r"\n[•\-\*]\s*|\n\d+\.\s*|\n", block)
    return [b.strip() for b in bullets if 10 < len(b.strip()) < 300][:10]


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

    return {
        "title": title,
        "description": description,
        "requirements": requirements,
        "location": location,
        "work_mode": work_mode,
        "stipend": raw.get("stipend"),
        "source": raw["source"],
        "source_url": raw["source_url"],
        "posted_at": _parse_date(raw.get("posted_at")),
        "last_seen_at": datetime.now(UTC),
        "status": "active",
        "ghost_score": 0.0,
        "is_ghost": False,
        "dedup_key": dedup_key,
    }
