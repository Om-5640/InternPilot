"""Global platform refactor — remove DAU/India hardcoding.

Additive schema changes:
  profiles: add university, grad_year, research_interests columns
  contacts_alumni: rename dau_batch → grad_year (String → Integer), add university

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-15 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- profiles: add three new columns ---
    op.add_column("profiles", sa.Column("university", sa.String(500), nullable=True))
    op.add_column("profiles", sa.Column("grad_year", sa.Integer, nullable=True))
    op.add_column(
        "profiles",
        sa.Column(
            "research_interests",
            sa.JSON,
            nullable=False,
            server_default="[]",
        ),
    )

    # --- contacts_alumni: add grad_year (int) and university ---
    # Migrate dau_batch (String) → grad_year (Integer):
    # 1. Add the new integer column
    op.add_column("contacts_alumni", sa.Column("grad_year", sa.Integer, nullable=True))
    # 2. Copy parseable 4-digit years; leave others as NULL
    op.execute(
        "UPDATE contacts_alumni "
        "SET grad_year = dau_batch::INTEGER "
        "WHERE dau_batch ~ '^[0-9]{4}$'"
    )
    # 3. Drop the old string column
    op.drop_column("contacts_alumni", "dau_batch")
    # 4. Add university
    op.add_column(
        "contacts_alumni", sa.Column("university", sa.String(500), nullable=True)
    )


def downgrade() -> None:
    # contacts_alumni: restore dau_batch, drop new columns
    op.add_column("contacts_alumni", sa.Column("dau_batch", sa.String(50), nullable=True))
    op.execute(
        "UPDATE contacts_alumni "
        "SET dau_batch = grad_year::TEXT "
        "WHERE grad_year IS NOT NULL"
    )
    op.drop_column("contacts_alumni", "university")
    op.drop_column("contacts_alumni", "grad_year")

    # profiles: drop new columns
    op.drop_column("profiles", "research_interests")
    op.drop_column("profiles", "grad_year")
    op.drop_column("profiles", "university")
