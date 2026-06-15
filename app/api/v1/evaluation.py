"""Module 10 — Evaluation / Platform IQ endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import APIError
from app.core.security import get_current_user
from app.models.user import User, UserRole
from app.schemas.evaluation import (
    MetricsResponse,
    ReplayResponse,
    RunResponse,
    coerce_evaluation_schema,
    to_iq_point,
)
from app.services.evaluation_service import EvaluationService

router = APIRouter(tags=["evaluation"])


async def _require_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    if current_user.role != UserRole.admin:
        raise APIError(403, "FORBIDDEN", "Admin role required")
    return current_user


@router.get("/evaluation/metrics", response_model=MetricsResponse)
async def get_metrics(
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MetricsResponse:
    """Return the latest evaluate_now snapshot and the full IQ trend curve."""
    svc = EvaluationService(db)
    latest_row = await svc.get_latest_formula()
    history = await svc.get_history_rows()
    return MetricsResponse(
        latest=coerce_evaluation_schema(latest_row) if latest_row else None,
        iq_trend=[to_iq_point(r) for r in history],
    )


@router.post("/evaluation/run", status_code=202, response_model=RunResponse)
async def run_evaluation(
    _: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
) -> RunResponse:
    """Score all known outcomes against snapshotted predictions and persist result."""
    svc = EvaluationService(db)
    row = await svc.evaluate_now()
    return RunResponse(latest=coerce_evaluation_schema(row))


@router.post("/evaluation/replay", status_code=202, response_model=ReplayResponse)
async def replay_evaluation(
    _: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
) -> ReplayResponse:
    """Temporal replay: build the full IQ trend curve from historical outcomes."""
    svc = EvaluationService(db)
    rows = await svc.build_history()
    points = [to_iq_point(r) for r in rows]
    return ReplayResponse(iq_trend=points, points=len(points))
