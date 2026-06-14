"""Greenhouse job-board adapter."""
from __future__ import annotations

import logging

import httpx

from app.sources.base import RawPosting
from app.sources.config import GREENHOUSE_SLUGS

logger = logging.getLogger(__name__)

_API = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
_SINGLE_API = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{job_id}"


def _parse_job(job: dict[str, object], company_name: str) -> RawPosting:
    loc_obj = job.get("location") or {}
    location: str | None = None
    if isinstance(loc_obj, dict):
        location = loc_obj.get("name") or None
    content = str(job.get("content") or "")
    return {
        "title": str(job.get("title") or ""),
        "company_name": company_name,
        "description": content,
        "source": "greenhouse",
        "source_url": str(job.get("absolute_url") or ""),
        "location": location,
        "work_mode": None,
        "stipend": None,
        "posted_at": str(job.get("updated_at") or "") or None,
        "requirements": [],
    }


class GreenhouseSource:
    name = "greenhouse"

    async def fetch(self) -> list[RawPosting]:
        results: list[RawPosting] = []
        async with httpx.AsyncClient(timeout=15.0) as client:
            for slug in GREENHOUSE_SLUGS:
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
                    logger.warning("greenhouse slug=%s error=%s", slug, exc)
        return results


async def fetch_greenhouse_single(url: str) -> RawPosting | None:
    """Fetch one Greenhouse posting by its board URL."""
    # URL shape: https://boards.greenhouse.io/{slug}/jobs/{job_id}
    try:
        parts = url.rstrip("/").split("/")
        job_id = parts[-1]
        slug = parts[-3]
        api_url = _SINGLE_API.format(slug=slug, job_id=job_id)
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(api_url)
            if resp.status_code != 200:
                return None
            job = resp.json()
            if not isinstance(job, dict):
                return None
            return _parse_job(job, slug)
    except Exception as exc:  # noqa: BLE001
        logger.warning("greenhouse single url=%s error=%s", url, exc)
        return None
