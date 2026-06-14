"""Lever job-board adapter."""
from __future__ import annotations

import logging

import httpx

from app.sources.base import RawPosting
from app.sources.config import LEVER_SLUGS

logger = logging.getLogger(__name__)

_API = "https://api.lever.co/v0/postings/{slug}?mode=json&limit=100"
_SINGLE_API = "https://api.lever.co/v0/postings/{slug}/{posting_id}"


def _parse_posting(posting: dict[str, object], slug: str) -> RawPosting:
    cats = posting.get("categories") or {}
    location: str | None = None
    if isinstance(cats, dict):
        location = cats.get("location") or None
    created_ms = posting.get("createdAt")
    posted_at: str | None = None
    if isinstance(created_ms, int | float):
        from datetime import UTC, datetime
        posted_at = datetime.fromtimestamp(created_ms / 1000, tz=UTC).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    return {
        "title": str(posting.get("text") or ""),
        "company_name": slug,
        "description": str(posting.get("descriptionPlain") or posting.get("description") or ""),
        "source": "lever",
        "source_url": str(posting.get("hostedUrl") or ""),
        "location": location,
        "work_mode": None,
        "stipend": None,
        "posted_at": posted_at,
        "requirements": [],
    }


class LeverSource:
    name = "lever"

    async def fetch(self) -> list[RawPosting]:
        results: list[RawPosting] = []
        async with httpx.AsyncClient(timeout=15.0) as client:
            for slug in LEVER_SLUGS:
                try:
                    resp = await client.get(_API.format(slug=slug))
                    if resp.status_code != 200:
                        continue
                    postings = resp.json()
                    if not isinstance(postings, list):
                        continue
                    for p in postings:
                        if isinstance(p, dict):
                            results.append(_parse_posting(p, slug))
                except Exception as exc:  # noqa: BLE001
                    logger.warning("lever slug=%s error=%s", slug, exc)
        return results


async def fetch_lever_single(url: str) -> RawPosting | None:
    """Fetch one Lever posting by its hosted URL."""
    # URL shape: https://jobs.lever.co/{slug}/{posting_id}
    try:
        parts = url.rstrip("/").split("/")
        posting_id = parts[-1]
        slug = parts[-2]
        api_url = _SINGLE_API.format(slug=slug, posting_id=posting_id)
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(api_url)
            if resp.status_code != 200:
                return None
            data = resp.json()
            if not isinstance(data, dict):
                return None
            return _parse_posting(data, slug)
    except Exception as exc:  # noqa: BLE001
        logger.warning("lever single url=%s error=%s", url, exc)
        return None
