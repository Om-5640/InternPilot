from __future__ import annotations

from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.llm.embeddings import EMBEDDING_DIM
from app.models.base import Base, TimestampMixin, UTCDateTime


class ResearchOpportunity(Base, TimestampMixin):
    """GLOBAL reference data — research labs / professors. Not user-scoped."""

    __tablename__ = "research_opportunities"

    professor_name: Mapped[str] = mapped_column(String(500), nullable=False)
    institution: Mapped[str] = mapped_column(String(500), nullable=False)
    lab_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    research_area: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    desired_skills: Mapped[list[Any]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    program: Mapped[str | None] = mapped_column(String(200), nullable=True)
    region: Mapped[str | None] = mapped_column(String(200), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(500), nullable=True)
    url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    source: Mapped[str] = mapped_column(
        String(50), nullable=False, default="manual", server_default="manual"
    )
    posted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    # Internal — excluded from API responses
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(EMBEDDING_DIM), nullable=True, default=None
    )
