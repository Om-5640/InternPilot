"""One-shot probe: run refresh against live feeds and report counts.

Usage:  uv run python scripts/probe_refresh.py
"""
from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, ".")


async def main() -> None:
    from sqlalchemy import func, select

    from app.core.config import settings
    from app.core.database import AsyncSessionLocal
    from app.models.company import Company
    from app.models.posting import Posting
    from app.services.aggregation_service import AggregationService

    print(f"INTERNSHIP_FILTER = {settings.INTERNSHIP_FILTER}")
    print("Connecting to:", settings.DATABASE_URL[:40], "...")

    async with AsyncSessionLocal() as db:
        svc = AggregationService(db)
        print("\nFetching from live sources …")
        counts = await svc.refresh()
        print(f"\nRefresh result: {counts}")

        total_postings: int = (
            await db.execute(select(func.count()).select_from(Posting))
        ).scalar_one()
        total_companies: int = (
            await db.execute(select(func.count()).select_from(Company))
        ).scalar_one()

        print(f"DB totals  -> postings: {total_postings}, companies: {total_companies}")

        # Show breakdown by source
        from sqlalchemy import text
        rows = (
            await db.execute(
                text("SELECT source, COUNT(*) FROM postings GROUP BY source ORDER BY COUNT(*) DESC")
            )
        ).all()
        print("\nBy source:")
        for source, cnt in rows:
            print(f"  {source:<12} {cnt}")

        # Show work_mode breakdown
        rows2 = (
            await db.execute(
                text("SELECT work_mode, COUNT(*) FROM postings GROUP BY work_mode ORDER BY COUNT(*) DESC")
            )
        ).all()
        print("\nBy work_mode:")
        for wm, cnt in rows2:
            print(f"  {wm:<12} {cnt}")

        # Spot-check a few titles
        sample = (
            await db.execute(
                select(Posting.title, Company.name)
                .join(Company, Posting.company_id == Company.id)
                .limit(10)
            )
        ).all()
        print("\nSample titles:")
        for title, co in sample:
            print(f"  [{co}] {title}")


asyncio.run(main())
