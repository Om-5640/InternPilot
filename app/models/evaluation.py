"""Module 10 — Evaluation (Platform IQ) model.

GLOBAL table — no user_id. Stores aggregate accuracy snapshots only;
never exposes individual user rows.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Evaluation(Base):
    """One accuracy snapshot — either a current evaluate_now() run or a build_history() checkpoint."""

    __tablename__ = "evaluations"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    n_outcomes: Mapped[int] = mapped_column(Integer, nullable=False)
    response_brier: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    response_auc: Mapped[float | None] = mapped_column(Float, nullable=True)
    response_accuracy: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    ghost_precision: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    ghost_recall: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    ghost_f1: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    platform_iq: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    model_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
