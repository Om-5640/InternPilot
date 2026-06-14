"""Pydantic request / response schemas for Module 0 — Auth.

Every field name and shape is dictated by API_CONTRACT.md §1 and §2 Module 0.
Do NOT rename or reorder fields without updating the contract first.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_serializer, field_validator

# ---------------------------------------------------------------------------
# Nested schemas
# ---------------------------------------------------------------------------

class ConsentSchema(BaseModel):
    gmail: bool = False
    github: bool = False
    alumni_data: bool = False


# ---------------------------------------------------------------------------
# User response object — matches contract §1 User interface exactly.
# password_hash is deliberately absent.
# ---------------------------------------------------------------------------

class UserSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    email: str
    role: str
    auth_provider: str
    consent: ConsentSchema
    created_at: datetime

    @field_validator("consent", mode="before")
    @classmethod
    def _coerce_consent(cls, v: Any) -> Any:
        if isinstance(v, dict):
            return v
        return {"gmail": False, "github": False, "alumni_data": False}

    @field_serializer("id")
    def _ser_id(self, v: uuid.UUID) -> str:
        return str(v)

    @field_serializer("created_at")
    def _ser_ts(self, v: datetime) -> str:
        if v.tzinfo is None:
            return v.isoformat() + "Z"
        return v.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class SignupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    password: str = Field(min_length=8)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class GoogleLoginRequest(BaseModel):
    id_token: str


class RefreshRequest(BaseModel):
    refresh_token: str


class ConsentUpdateRequest(BaseModel):
    gmail: bool | None = None
    github: bool | None = None
    alumni_data: bool | None = None


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class AuthResponse(BaseModel):
    user: UserSchema
    token: str
    refresh_token: str


class RefreshResponse(BaseModel):
    token: str


class MeResponse(BaseModel):
    user: UserSchema
