"""Module 10 — evaluations table (Platform IQ time-series).

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-15 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "evaluations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("n_outcomes", sa.Integer(), nullable=False),
        sa.Column("response_brier", sa.Float(), nullable=False, server_default="0"),
        sa.Column("response_auc", sa.Float(), nullable=True),
        sa.Column("response_accuracy", sa.Float(), nullable=False, server_default="0"),
        sa.Column("ghost_precision", sa.Float(), nullable=False, server_default="0"),
        sa.Column("ghost_recall", sa.Float(), nullable=False, server_default="0"),
        sa.Column("ghost_f1", sa.Float(), nullable=False, server_default="0"),
        sa.Column("platform_iq", sa.Float(), nullable=False, server_default="0"),
        sa.Column("model_version", sa.String(100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_evaluations_run_at", "evaluations", ["run_at"])


def downgrade() -> None:
    op.drop_index("ix_evaluations_run_at", table_name="evaluations")
    op.drop_table("evaluations")
