"""initial — pgvector extension + users table

Revision ID: 0001
Revises:
Create Date: 2026-06-13 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # pgvector — required for future embedding columns; harmless if already installed
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Enums must be created before the table that uses them
    op.execute("DO $$ BEGIN CREATE TYPE user_role AS ENUM ('student', 'admin'); EXCEPTION WHEN duplicate_object THEN null; END $$")
    op.execute("DO $$ BEGIN CREATE TYPE auth_provider_enum AS ENUM ('password', 'google'); EXCEPTION WHEN duplicate_object THEN null; END $$")

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String, nullable=True),
        sa.Column(
            "role",
            postgresql.ENUM("student", "admin", name="user_role", create_type=False),
            nullable=False,
            server_default="student",
        ),
        sa.Column(
            "auth_provider",
            postgresql.ENUM("password", "google", name="auth_provider_enum", create_type=False),
            nullable=False,
            server_default="password",
        ),
        sa.Column(
            "consent",
            sa.JSON,
            nullable=False,
            server_default='{"gmail": false, "github": false, "alumni_data": false}',
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

    op.create_index("ix_users_email", "users", ["email"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
    op.execute("DROP TYPE IF EXISTS user_role")
    op.execute("DROP TYPE IF EXISTS auth_provider_enum")
