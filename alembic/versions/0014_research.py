"""Module 12 — research_opportunities + research_outreach tables.

Revision ID: 0014
Revises: 0013
Create Date: 2026-06-15 00:00:00.000000

Limitation note (documented per spec): no live paper-fetch API; pitch specificity is
bounded by the seeded research description. In production, pull the professor's recent
publications to enrich the prompt.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from alembic import op
from app.llm.embeddings import EMBEDDING_DIM

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "research_opportunities",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("professor_name", sa.String(500), nullable=False),
        sa.Column("institution", sa.String(500), nullable=False),
        sa.Column("lab_name", sa.String(500), nullable=True),
        sa.Column("research_area", sa.String(500), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("desired_skills", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("program", sa.String(200), nullable=True),
        sa.Column("region", sa.String(200), nullable=True),
        sa.Column("contact_email", sa.String(500), nullable=True),
        sa.Column("url", sa.String(2000), nullable=True),
        sa.Column("source", sa.String(50), nullable=False, server_default="manual"),
        sa.Column("posted_at", sa.String(50), nullable=True),
        sa.Column("last_seen_at", sa.String(50), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "research_outreach",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "user_id",
            sa.UUID(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "research_opportunity_id",
            sa.UUID(),
            sa.ForeignKey("research_opportunities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(50), nullable=False, server_default="suggested"),
        sa.Column(
            "pitch_artifact_id",
            sa.UUID(),
            sa.ForeignKey("artifacts.id", ondelete="SET NULL"),
            nullable=True,
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_research_outreach_user_id", "research_outreach", ["user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_research_outreach_user_id", table_name="research_outreach")
    op.drop_table("research_outreach")
    op.drop_table("research_opportunities")
