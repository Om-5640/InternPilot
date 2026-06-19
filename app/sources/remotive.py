"""Remotive job-board adapter."""
from __future__ import annotations

import logging

import httpx

from app.sources.base import RawPosting

logger = logging.getLogger(__name__)

_API = "https://remotive.com/api/remote-jobs?search=intern"


class RemotiveSource:
    name = "remotive"

    async def fetch(self) -> list[RawPosting]:
        results: list[RawPosting] = []
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(_API)
                if resp.status_code != 200:
                    return results
                data = resp.json()
                jobs = data.get("jobs") or []
                if not isinstance(jobs, list):
                    return results
                for job in jobs:
                    if not isinstance(job, dict):
                        continue
                    title = str(job.get("title") or "").strip()
                    url = str(job.get("url") or "").strip()
                    if not title or not url:
                        continue
                    results.append({
                        "title": title,
                        "company_name": str(job.get("company_name") or "").strip(),
                        "description": str(job.get("description") or ""),
                        "source": "remotive",
                        "source_url": url,
                        "location": "Remote",
                        "work_mode": "remote",
                        "stipend": None,
                        "posted_at": str(job.get("publication_date") or "") or None,
                        "requirements": [],
                    })
        except Exception as exc:  # noqa: BLE001
            logger.warning("remotive error=%s", exc)
        return results
