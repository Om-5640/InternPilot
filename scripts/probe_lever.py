"""Probe candidate Lever slugs to find which companies are still active on Lever.

Usage:  uv run python scripts/probe_lever.py
"""
from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, ".")

CANDIDATES = [
    "amplitude",
    "gusto",
    "intercom",
    "webflow",
    "rippling",
    "gem",
    "ironclad",
    "attentive",
    "lattice",
    "circle",
    "coda",
    "dbt-labs",
    "productboard",
    "mercury",
    "remote",
]


async def main() -> None:
    import httpx

    print("Probing Lever slugs (non-zero = active):\n")
    async with httpx.AsyncClient(timeout=10.0) as c:
        for slug in CANDIDATES:
            try:
                r = await c.get(
                    f"https://api.lever.co/v0/postings/{slug}?mode=json&limit=100",
                    follow_redirects=True,
                )
                if r.status_code == 200:
                    jobs = r.json() if isinstance(r.json(), list) else []
                    intern_jobs = [
                        j for j in jobs if "intern" in j.get("text", "").lower()
                    ]
                    print(f"  {slug:<20} status=200  total={len(jobs):>3}  intern={len(intern_jobs)}")
                else:
                    print(f"  {slug:<20} status={r.status_code}")
            except Exception as exc:
                print(f"  {slug:<20} ERROR: {exc}")


asyncio.run(main())
