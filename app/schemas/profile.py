"""Pydantic schemas for Module 1 — Profile / Career Twin.

All field names and shapes are dictated by API_CONTRACT.md §Module 1.
`embedding` is deliberately absent from every response schema.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_serializer

# ---------------------------------------------------------------------------
# Shared enums
# ---------------------------------------------------------------------------

class WorkMode(enum.StrEnum):
    remote = "remote"
    onsite = "onsite"
    hybrid = "hybrid"
    any = "any"


# ---------------------------------------------------------------------------
# Nested item schemas (used in both response and request)
# ---------------------------------------------------------------------------

class ExperienceItem(BaseModel):
    title: str
    org: str
    start: str | None = None
    end: str | None = None
    description: str | None = None


class EducationItem(BaseModel):
    degree: str
    institution: str
    year: int | None = None
    gpa: float | None = None


class ProjectItem(BaseModel):
    name: str
    description: str | None = None
    tech: list[str] = Field(default_factory=list)
    url: str | None = None


# ---------------------------------------------------------------------------
# Preferences schemas
# ---------------------------------------------------------------------------

class PreferencesSchema(BaseModel):
    domains: list[str] = Field(default_factory=list)
    work_mode: str = "any"
    stipend_min: int | None = None
    duration_months: int | None = None
    locations: list[str] = Field(default_factory=list)
    target_companies: list[str] = Field(default_factory=list)


class PreferencesUpdateRequest(BaseModel):
    domains: list[str] | None = None
    work_mode: WorkMode | None = None
    stipend_min: int | None = None
    duration_months: int | None = None
    locations: list[str] | None = None
    target_companies: list[str] | None = None


# ---------------------------------------------------------------------------
# Profile response schema — embedding is never included
# ---------------------------------------------------------------------------

class ProfileSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: uuid.UUID
    headline: str | None
    university: str | None
    grad_year: int | None
    research_interests: list[str]
    skills: list[str]
    experience: list[ExperienceItem]
    education: list[EducationItem]
    projects: list[ProjectItem]
    github_url: str | None
    preferences: PreferencesSchema
    profile_strength: int
    gaps: list[str]
    created_at: datetime
    updated_at: datetime

    @field_serializer("user_id")
    def _ser_user_id(self, v: uuid.UUID) -> str:
        return str(v)

    @field_serializer("created_at", "updated_at")
    def _ser_ts(self, v: datetime) -> str:
        if v.tzinfo is None:
            return v.isoformat() + "Z"
        return v.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class GithubUrlRequest(BaseModel):
    github_url: str


class ProfileUpdateRequest(BaseModel):
    headline: str | None = None
    university: str | None = None
    grad_year: int | None = None
    research_interests: list[str] | None = None
    skills: list[str] | None = None
    experience: list[ExperienceItem] | None = None
    education: list[EducationItem] | None = None
    projects: list[ProjectItem] | None = None
    github_url: str | None = None


# ---------------------------------------------------------------------------
# Response wrappers
# ---------------------------------------------------------------------------

class ProfileResponse(BaseModel):
    profile: ProfileSchema


class StrengthResponse(BaseModel):
    profile_strength: int
    gaps: list[str]


# ---------------------------------------------------------------------------
# Internal — used only by extract_structured; never returned in responses
# ---------------------------------------------------------------------------

class ResumeExtract(BaseModel):
    headline: str | None = None
    university: str | None = None
    grad_year: int | None = None
    research_interests: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    experience: list[ExperienceItem] = Field(default_factory=list)
    education: list[EducationItem] = Field(default_factory=list)
    projects: list[ProjectItem] = Field(default_factory=list)
    github_url: str | None = None
    domains: list[str] = Field(default_factory=list)
    target_companies: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Coercion helpers used by ProfileSchema.model_validate(orm_obj)
# ---------------------------------------------------------------------------

def coerce_profile_schema(profile: Any) -> ProfileSchema:
    """Validate an ORM Profile → ProfileSchema, normalising JSON fields."""
    data: dict[str, Any] = {
        "user_id": profile.user_id,
        "headline": profile.headline,
        "university": profile.university,
        "grad_year": profile.grad_year,
        "research_interests": [
            str(i) for i in (profile.research_interests or []) if isinstance(i, str)
        ],
        # Filter to valid strings only so malformed JSON data never breaks Pydantic validation
        "skills": [s for s in (profile.skills or []) if isinstance(s, str) and s.strip()],
        "experience": profile.experience or [],
        "education": profile.education or [],
        "projects": profile.projects or [],
        "github_url": profile.github_url,
        "preferences": profile.preferences or {},
        "profile_strength": profile.profile_strength,
        "gaps": [str(g) for g in (profile.gaps or []) if g],
        "created_at": profile.created_at,
        "updated_at": profile.updated_at,
    }
    return ProfileSchema.model_validate(data)
