"""Adzuna job aggregator source — covers ALL fields and industries.

Adzuna aggregates from thousands of job boards: chemical engineering, finance,
healthcare, logistics, research, and every other field alongside tech.

Free tier: 250 API calls/month, ~50 results per call.
Register at https://developer.adzuna.com/

Set in .env:
    ADZUNA_APP_ID=<your app id>
    ADZUNA_APP_KEY=<your app key>
    ADZUNA_COUNTRY=us   # or gb, de, au, in, ca, etc.

If APP_ID or APP_KEY is empty, this source is silently skipped.
"""
from __future__ import annotations

import logging

import httpx

from app.core.config import settings
from app.sources.base import RawPosting

logger = logging.getLogger(__name__)

_BASE = "https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"
_RESULTS_PER_PAGE = 50
_MAX_PAGES = 5  # 250 results max per refresh to stay in free tier


class AdzunaSource:
    name = "adzuna"

    async def fetch(self) -> list[RawPosting]:
        app_id = getattr(settings, "ADZUNA_APP_ID", "")
        app_key = getattr(settings, "ADZUNA_APP_KEY", "")
        country = getattr(settings, "ADZUNA_COUNTRY", "us")

        if not app_id or not app_key:
            logger.debug("AdzunaSource: ADZUNA_APP_ID or ADZUNA_APP_KEY not set — skipping")
            return []

        results: list[RawPosting] = []

        async with httpx.AsyncClient(timeout=20.0) as client:
            for page in range(1, _MAX_PAGES + 1):
                url = _BASE.format(country=country, page=page)
                params = {
                    "app_id": app_id,
                    "app_key": app_key,
                    "what": "intern OR internship",
                    "results_per_page": _RESULTS_PER_PAGE,
                    "content-type": "application/json",
                    "sort_by": "date",
                }
                try:
                    resp = await client.get(url, params=params)
                    if resp.status_code != 200:
                        logger.warning("Adzuna page %d returned %d", page, resp.status_code)
                        break
                    data = resp.json()
                    jobs = data.get("results") or []
                    if not jobs:
                        break
                    for job in jobs:
                        parsed = _parse_job(job)
                        if parsed:
                            results.append(parsed)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Adzuna page %d error: %s", page, exc)
                    break

        logger.info("Adzuna: fetched %d raw postings", len(results))
        return results


def _parse_job(job: dict[str, object]) -> RawPosting | None:
    from typing import Any
    j: dict[str, Any] = dict(job)

    title = str(j.get("title") or "")
    if not title:
        return None

    company = str(
        (j.get("company") or {}).get("display_name") or "Unknown Company"
    )
    url = str(j.get("redirect_url") or "")
    if not url:
        return None

    description = str(j.get("description") or "")
    location_obj: dict[str, Any] = j.get("location") or {}
    area = location_obj.get("area") or []
    location: str | None = ", ".join(str(a) for a in area if a) or None if isinstance(area, list) else None

    # Salary → monthly stipend estimate (Adzuna reports annual USD)
    stipend: int | None = None
    sal_min = j.get("salary_min")
    if isinstance(sal_min, int | float) and sal_min > 0:
        monthly = int(sal_min / 12)
        stipend = monthly if 200 <= monthly <= 15_000 else None

    posted_at = str(j.get("created") or "")

    return {
        "title": title,
        "company_name": company,
        "description": description,
        "source": "adzuna",
        "source_url": url,
        "location": location,
        "work_mode": None,
        "stipend": stipend,
        "posted_at": posted_at or None,
        "requirements": [],
    }
