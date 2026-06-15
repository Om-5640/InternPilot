"""Pydantic schemas for Module 9 — Interview Prep."""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_serializer

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class OpportunityType(enum.StrEnum):
    company = "company"
    research = "research"


class CompanyType(enum.StrEnum):
    product = "product"
    service = "service"
    research_lab = "research_lab"
    unknown = "unknown"


class QuestionCategory(enum.StrEnum):
    coding = "coding"
    cs_fundamentals = "cs_fundamentals"
    project = "project"
    behavioral = "behavioral"
    hr = "hr"
    gd = "gd"
    research_fit = "research_fit"
    domain_depth = "domain_depth"
    methods = "methods"


class Difficulty(enum.StrEnum):
    easy = "easy"
    medium = "medium"
    hard = "hard"


# ---------------------------------------------------------------------------
# Question item (in both LLM extraction and API response)
# ---------------------------------------------------------------------------

class PrepQuestion(BaseModel):
    q: str
    type: str = "technical"                  # "technical" | "behavioral" | "gd"
    category: str | None = None              # QuestionCategory value
    difficulty: str | None = None            # Difficulty value
    answer_guidance: str | None = None
    ideal_answer_outline: str | None = None


# ---------------------------------------------------------------------------
# LLM extraction schema (never returned in API responses)
# ---------------------------------------------------------------------------

class PrepExtract(BaseModel):
    questions: list[PrepQuestion] = Field(default_factory=list)
    weak_spots: list[str] = Field(default_factory=list)
    reverse_questions: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# API response schema
# ---------------------------------------------------------------------------

class InterviewPrepSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    application_id: uuid.UUID | None
    company_name: str
    role: str
    opportunity_type: str
    region: str | None
    company_type: str
    questions: list[PrepQuestion]
    weak_spots: list[str]
    reverse_questions: list[str]
    created_at: datetime
    updated_at: datetime

    @field_serializer("id", "user_id", "application_id")
    def _ser_uuid(self, v: uuid.UUID | None) -> str | None:
        return str(v) if v is not None else None

    @field_serializer("created_at", "updated_at")
    def _ser_ts(self, v: datetime) -> str:
        if v.tzinfo is None:
            return v.isoformat() + "Z"
        return v.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Request schema
# ---------------------------------------------------------------------------

class PrepRequest(BaseModel):
    application_id: uuid.UUID | None = None
    company_name: str
    role: str
    opportunity_type: OpportunityType = OpportunityType.company
    region: str | None = None
    research_area: str | None = None    # hint for research type


# ---------------------------------------------------------------------------
# Response wrappers
# ---------------------------------------------------------------------------

class PrepResponse(BaseModel):
    prep: InterviewPrepSchema


# ---------------------------------------------------------------------------
# Coercion helper
# ---------------------------------------------------------------------------

def coerce_prep_schema(prep: Any) -> InterviewPrepSchema:
    questions = [
        PrepQuestion(**q) if isinstance(q, dict) else q
        for q in (prep.questions or [])
    ]
    return InterviewPrepSchema(
        id=prep.id,
        user_id=prep.user_id,
        application_id=prep.application_id,
        company_name=prep.company_name,
        role=prep.role,
        opportunity_type=prep.opportunity_type,
        region=prep.region,
        company_type=prep.company_type,
        questions=questions,
        weak_spots=prep.weak_spots or [],
        reverse_questions=prep.reverse_questions or [],
        created_at=prep.created_at,
        updated_at=prep.updated_at,
    )
