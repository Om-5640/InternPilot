from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db

router = APIRouter()


@router.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    db_status = "down"
    try:
        await db.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception:
        pass
    return {"status": "ok", "db": db_status}
