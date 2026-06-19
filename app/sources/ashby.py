"""Ashby job-board adapter."""
from __future__ import annotations

import logging

import httpx

from app.sources.base import RawPosting
from app.sources.config import ASHBY_SLUGS

logger = logging.getLogger(__name__)

_API = "https://api.ashbyhq.com/posting-api/job-board/{slug}"


def _parse_job(job: dict[str, object], slug: str) -> RawPosting:
    comp = job.get("compensation") or {}
    stipend: int | None = None
    if isinstance(comp, dict):
        components = comp.get("summaryComponents") or []
        if isinstance(components, list) and components:
            first = components[0]
            if isinstance(first, dict):
                val = first.get("minValue") or first.get("maxValue")
                if isinstance(val, int | float) and val > 0:
                    # Ashby compensation is typically annual — convert to monthly
                    monthly = int(val / 12)
                    stipend = monthly if 200 <= monthly <= 20_000 else None
    return {
        "title": str(job.get("title") or ""),
        "company_name": slug,
        "description": str(job.get("descriptionHtml") or job.get("descriptionPlain") or ""),
        "source": "ashby",
        "source_url": str(job.get("jobUrl") or ""),
        "location": str(job.get("locationName") or "") or None,
        "work_mode": None,
        "stipend": stipend,
        "posted_at": str(job.get("publishedAt") or "") or None,
        "requirements": [],
    }


class AshbySource:
    name = "ashby"

    async def fetch(self) -> list[RawPosting]:
        results: list[RawPosting] = []
        async with httpx.AsyncClient(timeout=15.0) as client:
            for slug in ASHBY_SLUGS:
                try:
                    resp = await client.get(_API.format(slug=slug))
                    if resp.status_code != 200:
                        continue
                    data = resp.json()
                    jobs = data.get("jobs") or []
                    for job in jobs:
                        if isinstance(job, dict):
                            results.append(_parse_job(job, slug))
                except Exception as exc:  # noqa: BLE001
                    logger.warning("ashby slug=%s error=%s", slug, exc)
        return results


async def fetch_ashby_single(url: str) -> RawPosting | None:
    """Fetch one Ashby posting by fetching all for the company and matching by URL."""
    # URL shape: https://jobs.ashbyhq.com/{slug}/{job_id}
    try:
        parts = url.rstrip("/").split("/")
        job_id = parts[-1]
        slug = parts[-2]
        api_url = _API.format(slug=slug)
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(api_url)
            if resp.status_code != 200:
                return None
            data = resp.json()
            jobs = data.get("jobs") or []
            for job in jobs:
                if not isinstance(job, dict):
                    continue
                if str(job.get("id") or "") == job_id or job_id in str(job.get("jobUrl") or ""):
                    return _parse_job(job, slug)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("ashby single url=%s error=%s", url, exc)
        return None
