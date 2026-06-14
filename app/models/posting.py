from __future__ import annotations

import enum
import uuid
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.llm.embeddings import EMBEDDING_DIM
from app.models.base import Base, TimestampMixin


class PostingWorkMode(enum.StrEnum):
    remote = "remote"
    onsite = "onsite"
    hybrid = "hybrid"
    any = "any"


class PostingSource(enum.StrEnum):
    greenhouse = "greenhouse"
    lever = "lever"
    ashby = "ashby"
    remoteok = "remoteok"
    remotive = "remotive"
    manual = "manual"


class PostingStatus(enum.StrEnum):
    active = "active"
    stale = "stale"


class Posting(Base, TimestampMixin):
    __tablename__ = "postings"

    company_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    requirements: Mapped[list[Any]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    work_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, default="any", server_default="any"
    )
    stipend: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    source_url: Mapped[str] = mapped_column(String(2000), nullable=False, unique=True, index=True)
    posted_at: Mapped[str | None] = mapped_column(String(50), nullable=True)
    last_seen_at: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active"
    )
    # Module 4 populates these; defaults until then
    ghost_score: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0"
    )
    is_ghost: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    dedup_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # Incremented each time a different source_url maps to the same dedup_key (cross-board sightings)
    source_sightings: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    # Internal only — never in API responses
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(EMBEDDING_DIM), nullable=True, default=None
    )
