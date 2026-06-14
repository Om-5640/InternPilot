"""add_source_sightings — track cross-board repost count per posting.

Each time a different source_url maps to the same dedup_key during aggregation,
the existing posting's source_sightings counter is incremented. Used by the
REPOST FREQUENCY signal in GhostService.

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-14 00:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "postings",
        sa.Column(
            "source_sightings",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )


def downgrade() -> None:
    op.drop_column("postings", "source_sightings")
