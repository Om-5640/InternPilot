from __future__ import annotations

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Company(Base, TimestampMixin):
    __tablename__ = "companies"

    name: Mapped[str] = mapped_column(String(500), nullable=False)
    domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Lowercased, punctuation-stripped name — used for dedup / resolution
    normalized_name: Mapped[str] = mapped_column(String(500), nullable=False, unique=True, index=True)
    # Module 4 will populate these; default 0.0 until then
    responsiveness_score: Mapped[float] = mapped_column(
        nullable=False, default=0.0, server_default="0"
    )
    ghost_history_score: Mapped[float] = mapped_column(
        nullable=False, default=0.0, server_default="0"
    )
    cohort_applied_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
