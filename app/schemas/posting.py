"""Pydantic schemas for Module 2 — Postings / Aggregation.

`embedding` is deliberately absent from every response schema.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_serializer

from app.models.company import Company
from app.models.posting import Posting

# ---------------------------------------------------------------------------
# Company summary (nested in posting responses)
# ---------------------------------------------------------------------------

class CompanySummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    domain: str | None
    industry: str | None
    size: str | None

    @field_serializer("id")
    def _ser_id(self, v: uuid.UUID) -> str:
        return str(v)


# ---------------------------------------------------------------------------
# Posting response schema — embedding never included
# ---------------------------------------------------------------------------

class PostingSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company: CompanySummary
    title: str
    description: str
    requirements: list[str]
    location: str | None
    work_mode: str
    stipend: int | None
    source: str
    source_url: str
    posted_at: datetime | None
    last_seen_at: datetime
    status: str
    ghost_score: float
    is_ghost: bool
    created_at: datetime
    updated_at: datetime

    @field_serializer("id")
    def _ser_id(self, v: uuid.UUID) -> str:
        return str(v)

    @field_serializer("created_at", "updated_at", "last_seen_at")
    def _ser_ts(self, v: datetime) -> str:
        if v.tzinfo is None:
            return v.isoformat() + "Z"
        return v.strftime("%Y-%m-%dT%H:%M:%SZ")

    @field_serializer("posted_at")
    def _ser_posted_at(self, v: datetime | None) -> str | None:
        if v is None:
            return None
        if v.tzinfo is None:
            return v.isoformat() + "Z"
        return v.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Response wrappers
# ---------------------------------------------------------------------------

class PostingResponse(BaseModel):
    posting: PostingSchema


class PostingListResponse(BaseModel):
    data: list[PostingSchema]
    page: int
    limit: int
    total: int


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class ImportUrlRequest(BaseModel):
    url: str


class RefreshResponse(BaseModel):
    ingested: int
    deduped: int


# ---------------------------------------------------------------------------
# Coercion helper
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Ghost-detail schemas (Module 4) — endpoint: GET /postings/{id}/ghost
# ---------------------------------------------------------------------------


class CohortStats(BaseModel):
    applied: int = 0
    responded: int = 0


class PostingGhostDetail(BaseModel):
    ghost_score: float
    is_ghost: bool
    signals: list[str]
    cohort: CohortStats


def coerce_posting_schema(posting: Posting, company: Company) -> PostingSchema:
    company_data = CompanySummary(
        id=company.id,
        name=company.name,
        domain=company.domain,
        industry=company.industry,
        size=company.size,
    )
    reqs: list[str] = [str(r) for r in (posting.requirements or [])]
    return PostingSchema(
        id=posting.id,
        company=company_data,
        title=posting.title,
        description=posting.description,
        requirements=reqs,
        location=posting.location,
        work_mode=posting.work_mode,
        stipend=posting.stipend,
        source=posting.source,
        source_url=posting.source_url,
        posted_at=posting.posted_at,
        last_seen_at=posting.last_seen_at,
        status=posting.status,
        ghost_score=posting.ghost_score,
        is_ghost=posting.is_ghost,
        created_at=posting.created_at,
        updated_at=posting.updated_at,
    )
