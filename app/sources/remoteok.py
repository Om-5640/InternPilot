"""RemoteOK job-board adapter."""
from __future__ import annotations

import logging

import httpx

from app.sources.base import RawPosting

logger = logging.getLogger(__name__)

_API = "https://remoteok.com/api?tags=intern"


class RemoteOKSource:
    name = "remoteok"

    async def fetch(self) -> list[RawPosting]:
        results: list[RawPosting] = []
        try:
            async with httpx.AsyncClient(
                timeout=20.0,
                headers={"User-Agent": "InternPilot/1.0"},
            ) as client:
                resp = await client.get(_API)
                if resp.status_code != 200:
                    return results
                data = resp.json()
                if not isinstance(data, list):
                    return results
                # First element is a legend/metadata dict — skip it
                for item in data[1:]:
                    if not isinstance(item, dict):
                        continue
                    title = str(item.get("position") or "").strip()
                    url = str(item.get("url") or "").strip()
                    if not title or not url:
                        continue
                    company = str(item.get("company") or "")
                    description = str(item.get("description") or "")
                    posted_at = str(item.get("date") or "") or None
                    salary_min = item.get("salary_min")
                    # RemoteOK salary_min is annual USD — convert to monthly
                    stipend: int | None = None
                    if isinstance(salary_min, int | float) and salary_min > 0:
                        monthly = int(salary_min / 12)
                        stipend = monthly if 200 <= monthly <= 20_000 else None
                    results.append({
                        "title": title,
                        "company_name": company,
                        "description": description,
                        "source": "remoteok",
                        "source_url": url,
                        "location": "Remote",
                        "work_mode": "remote",
                        "stipend": stipend,
                        "posted_at": posted_at,
                        "requirements": [],
                    })
        except Exception as exc:  # noqa: BLE001
            logger.warning("remoteok error=%s", exc)
        return results
