"""Module 9 — Interview Prep table.

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-15 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "interview_preps",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("application_id", sa.UUID(), nullable=True),
        sa.Column("company_name", sa.String(500), nullable=False),
        sa.Column("role", sa.String(500), nullable=False),
        sa.Column("opportunity_type", sa.String(20), nullable=False, server_default="company"),
        sa.Column("region", sa.String(100), nullable=True),
        sa.Column("company_type", sa.String(20), nullable=False, server_default="unknown"),
        sa.Column("questions", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("weak_spots", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("reverse_questions", sa.JSON(), nullable=False, server_default="[]"),
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
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_interview_preps_user_id", "interview_preps", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_interview_preps_user_id", table_name="interview_preps")
    op.drop_table("interview_preps")
