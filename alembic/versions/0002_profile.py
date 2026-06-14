"""profile — profiles table with pgvector embedding

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-13 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PREFS_DEFAULT = (
    '{"domains":[],"work_mode":"any","stipend_min":null,'
    '"duration_months":null,"locations":[],"target_companies":[]}'
)


def upgrade() -> None:
    op.create_table(
        "profiles",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("headline", sa.String(500), nullable=True),
        sa.Column("skills", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("experience", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("education", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("projects", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("github_url", sa.String(500), nullable=True),
        sa.Column("preferences", sa.JSON, nullable=False, server_default=_PREFS_DEFAULT),
        sa.Column(
            "profile_strength", sa.Integer, nullable=False, server_default="0"
        ),
        sa.Column("gaps", sa.JSON, nullable=False, server_default="[]"),
        # pgvector column — autogenerate cannot produce this; written manually.
        sa.Column(
            "embedding",
            sa.Text,  # placeholder type; overridden by raw SQL below
            nullable=True,
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

    # Replace the TEXT placeholder with the real vector(384) type
    op.execute("ALTER TABLE profiles ALTER COLUMN embedding TYPE vector(384) USING NULL")


def downgrade() -> None:
    op.drop_table("profiles")
