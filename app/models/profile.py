from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.llm.embeddings import EMBEDDING_DIM
from app.models.base import Base


def _default_preferences() -> dict[str, Any]:
    return {
        "domains": [],
        "work_mode": "any",
        "stipend_min": None,
        "duration_months": None,
        "locations": [],
        "target_companies": [],
    }


class Profile(Base):
    __tablename__ = "profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    headline: Mapped[str | None] = mapped_column(String(500), nullable=True)
    skills: Mapped[list[Any]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    experience: Mapped[list[Any]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    education: Mapped[list[Any]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    projects: Mapped[list[Any]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    github_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    preferences: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=_default_preferences,
        server_default=(
            '{"domains":[],"work_mode":"any","stipend_min":null,'
            '"duration_months":null,"locations":[],"target_companies":[]}'
        ),
    )
    profile_strength: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    gaps: Mapped[list[Any]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    # Internal only — never returned in API responses.
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(EMBEDDING_DIM), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )
