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
from app.services.eval_grounding_service import EvalGroundingService
from app.services.eval_matching_service import EvalMatchingService
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


@router.post("/evaluation/matching", status_code=200)
async def run_matching_eval(
    _: User = Depends(_require_admin),
) -> dict:
    """Offline golden-set matching quality eval: NDCG@3/5, Precision@3, MRR, weight grid-search.

    No DB required — runs the production scoring formula against 32 hand-labeled
    (profile archetype, opportunity) pairs and returns structured diagnostics including
    a weight-update recommendation and regression detection vs the previous run.
    """
    svc = EvalMatchingService()
    result = await svc.run_eval()
    return {
        "ndcg_at_3": result.ndcg_at_3,
        "ndcg_at_5": result.ndcg_at_5,
        "precision_at_3": result.precision_at_3,
        "mrr": result.mrr,
        "current_weights": result.current_weights,
        "optimal_weights": result.optimal_weights,
        "optimal_ndcg_at_5": result.optimal_ndcg_at_5,
        "weight_gain_pct": result.weight_gain_pct,
        "weight_recommendation": result.weight_recommendation,
        "profile_breakdown": [
            {
                "profile_id": p.profile_id,
                "label": p.label,
                "ndcg_at_3": p.ndcg_at_3,
                "ndcg_at_5": p.ndcg_at_5,
                "precision_at_3": p.precision_at_3,
                "mrr": p.mrr,
                "top_match": p.top_match_label,
                "top_match_correct": p.top_match_is_correct,
            }
            for p in result.profile_breakdown
        ],
        "regression_detected": result.regression_detected,
        "previous_ndcg_at_5": result.previous_ndcg_at_5,
        "health": result.health,
        "run_at": result.run_at,
    }


@router.get("/evaluation/grounding", status_code=200)
async def run_grounding_calibration(
    _: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Live grounding score calibration: Spearman ρ, ECE, optimal threshold recommendation.

    Joins all research_pitch artifacts (with grounding_score) against terminal-state
    research outreach records to determine whether higher grounding score actually
    predicts higher professor reply rates, and whether GROUNDING_THRESHOLD should change.
    """
    svc = EvalGroundingService(db)
    result = await svc.run_calibration()
    return {
        "n_pitches": result.n_pitches,
        "n_with_outcomes": result.n_with_outcomes,
        "spearman_rho": result.spearman_rho,
        "spearman_p_value": result.spearman_p_value,
        "is_predictive": result.is_predictive,
        "ece": result.ece,
        "current_threshold": result.current_threshold,
        "optimal_threshold": result.optimal_threshold,
        "f1_at_current": result.f1_at_current,
        "f1_at_optimal": result.f1_at_optimal,
        "threshold_recommendation": result.threshold_recommendation,
        "bucket_analysis": result.bucket_analysis,
        "health": result.health,
        "run_at": result.run_at,
    }
