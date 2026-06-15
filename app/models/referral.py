from __future__ import annotations

import enum
import uuid

from sqlalchemy import Enum as PGEnum
from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class ReferralStatus(enum.StrEnum):
    suggested = "suggested"
    requested = "requested"
    accepted = "accepted"
    declined = "declined"
    no_response = "no_response"


class Referral(Base, TimestampMixin):
    """User-owned referral record — every query MUST be scoped to user_id."""

    __tablename__ = "referrals"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    posting_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("postings.id", ondelete="SET NULL"),
        nullable=True,
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("contacts_alumni.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[ReferralStatus] = mapped_column(
        PGEnum(ReferralStatus, name="referral_status_enum"),
        nullable=False,
        default=ReferralStatus.suggested,
        server_default=ReferralStatus.suggested.value,
    )
    intro_artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("artifacts.id", ondelete="SET NULL"),
        nullable=True,
    )
