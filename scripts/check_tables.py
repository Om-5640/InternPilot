import asyncio

from sqlalchemy import text

from app.core.database import AsyncSessionLocal


async def check() -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"))
        tables = [r[0] for r in result.all()]
        print("Tables in main DB:", tables)

asyncio.run(check())
