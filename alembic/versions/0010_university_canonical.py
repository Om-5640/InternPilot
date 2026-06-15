"""Add university_canonical column to profiles and contacts_alumni; backfill existing rows.

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-15 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "profiles",
        sa.Column("university_canonical", sa.String(500), nullable=True),
    )
    op.create_index("ix_profiles_university_canonical", "profiles", ["university_canonical"])

    op.add_column(
        "contacts_alumni",
        sa.Column("university_canonical", sa.String(500), nullable=True),
    )
    op.create_index(
        "ix_contacts_alumni_university_canonical", "contacts_alumni", ["university_canonical"]
    )

    # Backfill existing rows using the normalizer
    from app.services.university_normalizer import canonicalize

    conn = op.get_bind()

    profiles = conn.execute(
        sa.text("SELECT user_id, university FROM profiles WHERE university IS NOT NULL")
    ).fetchall()
    for row in profiles:
        canonical = canonicalize(row.university)
        if canonical:
            conn.execute(
                sa.text(
                    "UPDATE profiles SET university_canonical = :c WHERE user_id = :uid"
                ),
                {"c": canonical, "uid": str(row.user_id)},
            )

    contacts = conn.execute(
        sa.text(
            "SELECT id, university FROM contacts_alumni WHERE university IS NOT NULL"
        )
    ).fetchall()
    for row in contacts:
        canonical = canonicalize(row.university)
        if canonical:
            conn.execute(
                sa.text(
                    "UPDATE contacts_alumni SET university_canonical = :c WHERE id = :id"
                ),
                {"c": canonical, "id": str(row.id)},
            )


def downgrade() -> None:
    op.drop_index("ix_contacts_alumni_university_canonical", table_name="contacts_alumni")
    op.drop_column("contacts_alumni", "university_canonical")
    op.drop_index("ix_profiles_university_canonical", table_name="profiles")
    op.drop_column("profiles", "university_canonical")
