"""match_index — HNSW index on postings.embedding for cosine-similarity search.

Requires pgvector >= 0.5.0.

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-14 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX ix_postings_embedding_hnsw "
        "ON postings USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_postings_embedding_hnsw")
