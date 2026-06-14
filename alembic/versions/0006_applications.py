"""applications and artifacts tables.

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-14 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "applications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "posting_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("postings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("channel", sa.String(50), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="saved"),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column(
            "predicted_response_prob",
            sa.Float,
            nullable=False,
            server_default="0.0",
        ),
        sa.Column(
            "predicted_ghost",
            sa.Boolean,
            nullable=False,
            server_default="false",
        ),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "last_status_at",
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
    op.create_index("ix_applications_user_id", "applications", ["user_id"])

    op.create_table(
        "artifacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "application_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("applications.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("ats_score", sa.Integer, nullable=True),
        sa.Column("missing_keywords", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("grounding_score", sa.Float, nullable=True),
        sa.Column("predicted_response", sa.Float, nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
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
    op.create_index("ix_artifacts_user_id", "artifacts", ["user_id"])
    op.create_index("ix_artifacts_application_id", "artifacts", ["application_id"])


def downgrade() -> None:
    op.drop_index("ix_artifacts_application_id", table_name="artifacts")
    op.drop_index("ix_artifacts_user_id", table_name="artifacts")
    op.drop_table("artifacts")
    op.drop_index("ix_applications_user_id", table_name="applications")
    op.drop_table("applications")
