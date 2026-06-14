"""Delete all postings and companies from the main DB so a clean refresh can run.

Usage:  uv run python scripts/clear_postings.py
"""
from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, ".")


async def main() -> None:
    from sqlalchemy import text

    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        await db.execute(text("DELETE FROM postings"))
        await db.execute(text("DELETE FROM companies"))
        await db.commit()
        print("Cleared all postings and companies from main DB.")


asyncio.run(main())
