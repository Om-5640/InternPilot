"""Quick probe: test each source adapter individually to diagnose 0-result sources."""
from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, ".")


async def main() -> None:
    import httpx

    print("=== RemoteOK ===")
    try:
        async with httpx.AsyncClient(timeout=20.0, headers={"User-Agent": "InternPilot/1.0"}) as c:
            r = await c.get("https://remoteok.com/api")
            print(f"  status={r.status_code}  content-type={r.headers.get('content-type','?')}")
            if r.status_code == 200:
                data = r.json()
                print(f"  type={type(data).__name__}  len={len(data) if isinstance(data, list) else '?'}")
                if isinstance(data, list) and len(data) > 1:
                    print(f"  sample[1] keys: {list(data[1].keys())[:6]}")
    except Exception as exc:
        print(f"  ERROR: {exc}")

    print("\n=== Remotive ===")
    try:
        async with httpx.AsyncClient(timeout=20.0) as c:
            r = await c.get("https://remotive.com/api/remote-jobs?search=intern&limit=10")
            print(f"  status={r.status_code}  content-type={r.headers.get('content-type','?')}")
            if r.status_code == 200:
                data = r.json()
                jobs = data.get("jobs", [])
                print(f"  jobs count={len(jobs)}")
                if jobs:
                    print(f"  sample title: {jobs[0].get('title','?')}")
    except Exception as exc:
        print(f"  ERROR: {exc}")

    print("\n=== Lever slug check ===")
    for slug in ("lyft", "airtable", "vercel", "netflix", "scale"):
        try:
            async with httpx.AsyncClient(timeout=10.0) as c:
                r = await c.get(f"https://api.lever.co/v0/postings/{slug}?mode=json&limit=5")
                cnt = len(r.json()) if r.status_code == 200 and isinstance(r.json(), list) else "N/A"
                print(f"  {slug:<12} status={r.status_code}  jobs={cnt}")
        except Exception as exc:
            print(f"  {slug:<12} ERROR: {exc}")


asyncio.run(main())
