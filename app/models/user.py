from __future__ import annotations

import enum

from sqlalchemy import JSON, String
from sqlalchemy import Enum as PGEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class UserRole(enum.StrEnum):
    student = "student"
    admin = "admin"


class AuthProvider(enum.StrEnum):
    password = "password"
    google = "google"


class User(Base, TimestampMixin):
    __tablename__ = "users"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    role: Mapped[UserRole] = mapped_column(
        PGEnum(UserRole, name="user_role"),
        nullable=False,
        default=UserRole.student,
        server_default=UserRole.student.value,
    )
    auth_provider: Mapped[AuthProvider] = mapped_column(
        PGEnum(AuthProvider, name="auth_provider_enum"),
        nullable=False,
        default=AuthProvider.password,
        server_default=AuthProvider.password.value,
    )
    # JSONB stored as JSON; default covers all three consent flags
    consent: Mapped[dict[str, bool]] = mapped_column(
        JSON,
        nullable=False,
        default=lambda: {"gmail": False, "github": False, "alumni_data": False},
        server_default='{"gmail": false, "github": false, "alumni_data": false}',
    )
