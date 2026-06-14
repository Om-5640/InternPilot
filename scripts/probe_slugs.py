"""Quick smoke-test of all new slugs + fixed RemoteOK/Remotive URLs.

Usage:  uv run python scripts/probe_slugs.py
"""
from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, ".")


async def check_greenhouse(client: object, slug: str) -> tuple[str, int]:
    import httpx

    assert isinstance(client, httpx.AsyncClient)
    try:
        r = await client.get(
            f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=false"
        )
        if r.status_code == 200:
            jobs = r.json().get("jobs", [])
            return slug, len(jobs)
        return slug, -r.status_code
    except Exception:
        return slug, 0


async def check_ashby(client: object, slug: str) -> tuple[str, int]:
    import httpx

    assert isinstance(client, httpx.AsyncClient)
    try:
        r = await client.get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
        if r.status_code == 200:
            jobs = r.json().get("jobPostings", [])
            return slug, len(jobs)
        return slug, -r.status_code
    except Exception:
        return slug, 0


async def main() -> None:
    import httpx

    from app.sources.config import ASHBY_SLUGS, GREENHOUSE_SLUGS

    async with httpx.AsyncClient(
        timeout=15.0, headers={"User-Agent": "InternPilot/1.0"}
    ) as c:
        print("=== Greenhouse slugs ===")
        gh_tasks = [check_greenhouse(c, s) for s in GREENHOUSE_SLUGS]
        for slug, cnt in await asyncio.gather(*gh_tasks):
            status = f"{cnt:>4} jobs" if cnt >= 0 else f"HTTP {-cnt}"
            print(f"  {slug:<20} {status}")

        print("\n=== Ashby slugs ===")
        ab_tasks = [check_ashby(c, s) for s in ASHBY_SLUGS]
        for slug, cnt in await asyncio.gather(*ab_tasks):
            status = f"{cnt:>4} jobs" if cnt >= 0 else f"HTTP {-cnt}"
            print(f"  {slug:<20} {status}")

        print("\n=== RemoteOK (intern filter) ===")
        try:
            r = await c.get("https://remoteok.com/api?tags=intern")
            data = r.json() if r.status_code == 200 else []
            items = [x for x in (data[1:] if isinstance(data, list) else []) if isinstance(x, dict)]
            print(f"  status={r.status_code}  items={len(items)}")
            if items:
                print(f"  sample title: {items[0].get('position','?')!r}")
        except Exception as exc:
            print(f"  ERROR: {exc}")

        print("\n=== Remotive (intern search) ===")
        try:
            r = await c.get("https://remotive.com/api/remote-jobs?search=intern")
            data = r.json() if r.status_code == 200 else {}
            jobs = data.get("jobs", [])
            print(f"  status={r.status_code}  jobs={len(jobs)}")
            if jobs:
                print(f"  sample title: {jobs[0].get('title','?')!r}")
        except Exception as exc:
            print(f"  ERROR: {exc}")


asyncio.run(main())
