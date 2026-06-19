"""Add unique index on research_opportunities.url to prevent duplicate upserts.

Revision ID: 0020
Revises: 0019
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Deduplicate first — keep the row with the lowest created_at for each url
    op.execute("""
        DELETE FROM research_opportunities a
        USING research_opportunities b
        WHERE a.url = b.url
          AND a.url IS NOT NULL
          AND a.id > b.id
    """)
    op.create_index(
        "ix_research_opportunities_url",
        "research_opportunities",
        ["url"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_research_opportunities_url", table_name="research_opportunities")
