from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.artifact import Artifact
    from app.models.outcome import Outcome


class Application(Base, TimestampMixin):
    __tablename__ = "applications"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    posting_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("postings.id", ondelete="CASCADE"),
        nullable=False,
    )
    channel: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="saved", server_default="saved"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    predicted_response_prob: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0.0"
    )
    predicted_ghost: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    applied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_status_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    artifacts: Mapped[list[Artifact]] = relationship(
        "Artifact", back_populates="application", lazy="noload"
    )
    outcomes: Mapped[list[Outcome]] = relationship(
        "Outcome", back_populates="application", lazy="noload"
    )
