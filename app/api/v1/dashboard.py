"""Module 11 — Dashboard endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.dashboard import DashboardSummary, DigestResponse
from app.services.dashboard_service import DashboardService

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard", response_model=DashboardSummary)
async def get_dashboard(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DashboardSummary:
    return await DashboardService(db, current_user.id).get_summary()


@router.get("/digest", response_model=DigestResponse)
async def get_digest(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DigestResponse:
    return await DashboardService(db, current_user.id).get_digest()
