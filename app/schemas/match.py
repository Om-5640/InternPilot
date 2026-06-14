"""Pydantic schemas for Module 3 — Matching & Ranking.

`embedding` is deliberately absent from every response schema.
"""
from __future__ import annotations

import uuid

from pydantic import BaseModel, field_serializer

from app.schemas.posting import PostingSchema


class MatchSchema(BaseModel):
    """Single match result — per-user, computed on-the-fly (no persistence)."""

    posting_id: uuid.UUID
    posting: PostingSchema
    match_score: float            # 0..1 hybrid score
    match_explanation: str        # templated (or LLM on detail endpoint)
    matched_skills: list[str]
    missing_skills: list[str]
    response_likelihood: float    # 0..1 placeholder until Module 5
    expected_value: float         # 0..1 ranking key
    ghost_score: float            # read from posting (Module 4 populates)
    is_ghost: bool
    created_at: str               # ISO-8601 UTC; time match was computed

    @field_serializer("posting_id")
    def _ser_posting_id(self, v: uuid.UUID) -> str:
        return str(v)


class MatchResponse(BaseModel):
    match: MatchSchema


class MatchListResponse(BaseModel):
    data: list[MatchSchema]
    page: int
    limit: int
    total: int


class SkillGapItem(BaseModel):
    skill: str
    unlockable_roles: int


class SkillGapsResponse(BaseModel):
    gaps: list[SkillGapItem]
