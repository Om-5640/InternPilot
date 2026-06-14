from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.application import Application


class Artifact(Base, TimestampMixin):
    __tablename__ = "artifacts"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    application_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("applications.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    ats_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    missing_keywords: Mapped[list[Any]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    grounding_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    predicted_response: Mapped[float | None] = mapped_column(Float, nullable=True)
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )

    application: Mapped[Application | None] = relationship(
        "Application", back_populates="artifacts", lazy="noload"
    )
