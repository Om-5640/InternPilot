from __future__ import annotations

import enum

from sqlalchemy import Enum as PGEnum
from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class RelationshipType(enum.StrEnum):
    alumni = "alumni"
    second_degree = "second_degree"
    unknown = "unknown"


class Contact(Base, TimestampMixin):
    """Alumni / referral contacts — GLOBAL reference data (not user-scoped)."""

    __tablename__ = "contacts_alumni"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    company_id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str | None] = mapped_column(String(255), nullable=True)
    grad_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    university: Mapped[str | None] = mapped_column(String(500), nullable=True)
    university_canonical: Mapped[str | None] = mapped_column(String(500), nullable=True, index=True)
    linkedin: Mapped[str | None] = mapped_column(String(500), nullable=True)
    relationship: Mapped[RelationshipType] = mapped_column(
        PGEnum(RelationshipType, name="relationship_enum"),
        nullable=False,
        default=RelationshipType.alumni,
        server_default=RelationshipType.alumni.value,
    )
    source: Mapped[str] = mapped_column(
        String(100), nullable=False, default="seed", server_default="seed"
    )
