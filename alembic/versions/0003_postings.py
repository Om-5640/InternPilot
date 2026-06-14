"""postings — companies + postings tables with pgvector embedding

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-13 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- companies -----------------------------------------------------------
    op.create_table(
        "companies",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("domain", sa.String(255), nullable=True),
        sa.Column("industry", sa.String(255), nullable=True),
        sa.Column("size", sa.String(100), nullable=True),
        sa.Column("normalized_name", sa.String(500), nullable=False),
        sa.Column(
            "responsiveness_score",
            sa.Float,
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "ghost_history_score",
            sa.Float,
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_companies_normalized_name", "companies", ["normalized_name"], unique=True)

    # --- postings ------------------------------------------------------------
    op.create_table(
        "postings",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("requirements", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("location", sa.String(255), nullable=True),
        sa.Column("work_mode", sa.String(20), nullable=False, server_default="any"),
        sa.Column("stipend", sa.Integer, nullable=True),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("source_url", sa.String(2000), nullable=False),
        sa.Column("posted_at", sa.String(50), nullable=True),
        sa.Column("last_seen_at", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column(
            "ghost_score",
            sa.Float,
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "is_ghost",
            sa.Boolean,
            nullable=False,
            server_default="false",
        ),
        sa.Column("dedup_key", sa.String(64), nullable=False),
        # pgvector column — written as TEXT then altered below
        sa.Column("embedding", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_postings_company_id", "postings", ["company_id"])
    op.create_index("ix_postings_source_url", "postings", ["source_url"], unique=True)
    op.create_index("ix_postings_dedup_key", "postings", ["dedup_key"])

    # Replace TEXT placeholder with real vector(384) type
    op.execute(
        "ALTER TABLE postings ALTER COLUMN embedding TYPE vector(384) USING NULL"
    )


def downgrade() -> None:
    op.drop_table("postings")
    op.drop_table("companies")
