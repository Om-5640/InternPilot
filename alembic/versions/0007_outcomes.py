"""outcomes table + cohort_applied_count on companies + gmail_token on users.

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-14 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "companies",
        sa.Column(
            "cohort_applied_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )

    op.add_column(
        "users",
        sa.Column("gmail_token", sa.JSON(), nullable=True),
    )

    op.create_table(
        "outcomes",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "application_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("applications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("outcome_type", sa.String(50), nullable=False),
        sa.Column("responded", sa.Boolean(), nullable=False),
        sa.Column("time_to_response_hours", sa.Float(), nullable=True),
        sa.Column(
            "source",
            sa.String(50),
            nullable=False,
            server_default="manual",
        ),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_outcomes_application_id", "outcomes", ["application_id"])


def downgrade() -> None:
    op.drop_index("ix_outcomes_application_id", table_name="outcomes")
    op.drop_table("outcomes")
    op.drop_column("users", "gmail_token")
    op.drop_column("companies", "cohort_applied_count")
