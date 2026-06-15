"""contacts_alumni and referrals tables.

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-14 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE relationship_enum AS ENUM ('alumni', 'second_degree', 'unknown'); "
        "EXCEPTION WHEN duplicate_object THEN null; END $$"
    )
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE referral_status_enum AS ENUM "
        "('suggested', 'requested', 'accepted', 'declined', 'no_response'); "
        "EXCEPTION WHEN duplicate_object THEN null; END $$"
    )

    op.create_table(
        "contacts_alumni",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(255), nullable=True),
        sa.Column("dau_batch", sa.String(50), nullable=True),
        sa.Column("linkedin", sa.String(500), nullable=True),
        sa.Column(
            "relationship",
            postgresql.ENUM(
                "alumni",
                "second_degree",
                "unknown",
                name="relationship_enum",
                create_type=False,
            ),
            nullable=False,
            server_default="alumni",
        ),
        sa.Column(
            "source",
            sa.String(100),
            nullable=False,
            server_default="seed",
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
    )
    op.create_index("ix_contacts_alumni_company_id", "contacts_alumni", ["company_id"])

    op.create_table(
        "referrals",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "posting_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("postings.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "contact_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("contacts_alumni.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "status",
            postgresql.ENUM(
                "suggested",
                "requested",
                "accepted",
                "declined",
                "no_response",
                name="referral_status_enum",
                create_type=False,
            ),
            nullable=False,
            server_default="suggested",
        ),
        sa.Column(
            "intro_artifact_id",
            postgresql.UUID(as_uuid=True),
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
    )
    op.create_index("ix_referrals_user_id", "referrals", ["user_id"])
    op.create_index("ix_referrals_company_id", "referrals", ["company_id"])


def downgrade() -> None:
    op.drop_index("ix_referrals_company_id", table_name="referrals")
    op.drop_index("ix_referrals_user_id", table_name="referrals")
    op.drop_table("referrals")
    op.drop_index("ix_contacts_alumni_company_id", table_name="contacts_alumni")
    op.drop_table("contacts_alumni")
    op.execute("DROP TYPE IF EXISTS referral_status_enum")
    op.execute("DROP TYPE IF EXISTS relationship_enum")
