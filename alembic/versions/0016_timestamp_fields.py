"""Convert posted_at and last_seen_at from VARCHAR(50) to TIMESTAMPTZ.

Revision ID: 0016
Revises: 0015
"""
from __future__ import annotations

from alembic import op

revision: str = "0016"
down_revision: str = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE postings
          ALTER COLUMN posted_at TYPE TIMESTAMPTZ
            USING CASE
              WHEN posted_at IS NULL OR posted_at = '' THEN NULL
              ELSE posted_at::TIMESTAMPTZ
            END,
          ALTER COLUMN last_seen_at TYPE TIMESTAMPTZ
            USING CASE
              WHEN last_seen_at = '' THEN NOW()
              ELSE last_seen_at::TIMESTAMPTZ
            END
    """)
    op.execute("""
        ALTER TABLE research_opportunities
          ALTER COLUMN posted_at TYPE TIMESTAMPTZ
            USING CASE
              WHEN posted_at IS NULL OR posted_at = '' THEN NULL
              ELSE posted_at::TIMESTAMPTZ
            END,
          ALTER COLUMN last_seen_at TYPE TIMESTAMPTZ
            USING CASE
              WHEN last_seen_at = '' THEN NOW()
              ELSE last_seen_at::TIMESTAMPTZ
            END
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE postings
          ALTER COLUMN posted_at TYPE VARCHAR(50)
            USING CASE
              WHEN posted_at IS NULL THEN NULL
              ELSE TO_CHAR(posted_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
            END,
          ALTER COLUMN last_seen_at TYPE VARCHAR(50)
            USING TO_CHAR(last_seen_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
    """)
    op.execute("""
        ALTER TABLE research_opportunities
          ALTER COLUMN posted_at TYPE VARCHAR(50)
            USING CASE
              WHEN posted_at IS NULL THEN NULL
              ELSE TO_CHAR(posted_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
            END,
          ALTER COLUMN last_seen_at TYPE VARCHAR(50)
            USING TO_CHAR(last_seen_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
    """)
