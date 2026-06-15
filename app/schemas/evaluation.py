"""Pydantic schemas for Module 10 — Evaluation / Platform IQ."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, field_serializer

from app.models.evaluation import Evaluation


class EvaluationSchema(BaseModel):
    id: uuid.UUID
    run_at: datetime
    n_outcomes: int
    response_brier: float
    response_auc: float | None
    response_accuracy: float
    ghost_precision: float
    ghost_recall: float
    ghost_f1: float
    platform_iq: float
    model_version: str | None
    created_at: datetime

    @field_serializer("id")
    def _id(self, v: uuid.UUID) -> str:
        return str(v)

    @field_serializer("run_at", "created_at")
    def _dt(self, v: datetime) -> str:
        return v.isoformat()

    model_config = {"from_attributes": True}


class IQPoint(BaseModel):
    """Single point in the Platform IQ trend curve."""

    date: str   # ISO datetime (run_at of the evaluation row)
    value: float  # platform_iq 0..100


class MetricsResponse(BaseModel):
    """GET /api/evaluation/metrics response."""

    latest: EvaluationSchema | None
    iq_trend: list[IQPoint]


class RunResponse(BaseModel):
    """POST /api/evaluation/run response."""

    latest: EvaluationSchema


class ReplayResponse(BaseModel):
    """POST /api/evaluation/replay response."""

    iq_trend: list[IQPoint]
    points: int


def coerce_evaluation_schema(e: Evaluation) -> EvaluationSchema:
    return EvaluationSchema(
        id=e.id,
        run_at=e.run_at,
        n_outcomes=e.n_outcomes,
        response_brier=e.response_brier,
        response_auc=e.response_auc,
        response_accuracy=e.response_accuracy,
        ghost_precision=e.ghost_precision,
        ghost_recall=e.ghost_recall,
        ghost_f1=e.ghost_f1,
        platform_iq=e.platform_iq,
        model_version=e.model_version,
        created_at=e.created_at,
    )


def to_iq_point(e: Evaluation) -> IQPoint:
    return IQPoint(date=e.run_at.isoformat(), value=round(e.platform_iq, 4))
