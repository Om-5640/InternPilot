"""Pydantic schemas for Module 7 — Application Assistant + Module 8 — Tracker."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

if TYPE_CHECKING:
    from app.models.application import Application
    from app.models.artifact import Artifact
    from app.models.outcome import Outcome


# ---------------------------------------------------------------------------
# Artifact
# ---------------------------------------------------------------------------


class ArtifactSchema(BaseModel):
    id: uuid.UUID
    application_id: uuid.UUID | None
    type: str
    content: str
    ats_score: int | None
    missing_keywords: list[str]
    grounding_score: float | None
    predicted_response: float | None
    version: int
    generated_at: datetime


def coerce_artifact_schema(a: Artifact) -> ArtifactSchema:
    return ArtifactSchema(
        id=a.id,
        application_id=a.application_id,
        type=a.type,
        content=a.content,
        ats_score=a.ats_score,
        missing_keywords=list(a.missing_keywords or []),
        grounding_score=a.grounding_score,
        predicted_response=a.predicted_response,
        version=a.version,
        generated_at=a.created_at,
    )


# ---------------------------------------------------------------------------
# Outcome
# ---------------------------------------------------------------------------


class OutcomeSchema(BaseModel):
    id: uuid.UUID
    application_id: uuid.UUID
    outcome_type: str
    responded: bool
    time_to_response_hours: float | None
    source: str
    recorded_at: datetime


def coerce_outcome_schema(o: Outcome) -> OutcomeSchema:
    return OutcomeSchema(
        id=o.id,
        application_id=o.application_id,
        outcome_type=o.outcome_type,
        responded=o.responded,
        time_to_response_hours=o.time_to_response_hours,
        source=o.source,
        recorded_at=o.recorded_at,
    )


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------


class PostingSummarySchema(BaseModel):
    id: uuid.UUID
    title: str
    company_name: str


class ApplicationSchema(BaseModel):
    id: uuid.UUID
    posting_id: uuid.UUID
    posting: PostingSummarySchema
    channel: str
    status: str
    artifacts: list[ArtifactSchema]
    predicted_response_prob: float
    predicted_ghost: bool
    applied_at: datetime | None
    last_status_at: datetime
    outcome: OutcomeSchema | None
    created_at: datetime


def coerce_application_schema(
    app: Application,
    posting_id: uuid.UUID,
    posting_title: str,
    company_name: str,
    artifacts: list[Artifact],
    outcome: Outcome | None = None,
) -> ApplicationSchema:
    return ApplicationSchema(
        id=app.id,
        posting_id=app.posting_id,
        posting=PostingSummarySchema(
            id=posting_id,
            title=posting_title,
            company_name=company_name,
        ),
        channel=app.channel,
        status=app.status,
        artifacts=[coerce_artifact_schema(a) for a in artifacts],
        predicted_response_prob=app.predicted_response_prob,
        predicted_ghost=app.predicted_ghost,
        applied_at=app.applied_at,
        last_status_at=app.last_status_at,
        outcome=coerce_outcome_schema(outcome) if outcome is not None else None,
        created_at=app.created_at,
    )


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------


class DecodeRequest(BaseModel):
    posting_id: uuid.UUID


class DecodeResponse(BaseModel):
    requirements: list[str]
    keywords: list[str]
    summary: str


class AtsScoreRequest(BaseModel):
    posting_id: uuid.UUID
    content: str


class AtsScoreResponse(BaseModel):
    ats_score: int
    missing_keywords: list[str]


class DraftRequest(BaseModel):
    posting_id: uuid.UUID
    type: str
    channel: str


class DraftResponse(BaseModel):
    artifact: ArtifactSchema


class CreateApplicationRequest(BaseModel):
    posting_id: uuid.UUID
    channel: str
    artifact_id: uuid.UUID


class CreateApplicationResponse(BaseModel):
    application: ApplicationSchema


class SendRequest(BaseModel):
    via: str


class ListApplicationsResponse(BaseModel):
    data: list[ApplicationSchema]
    page: int
    limit: int
    total: int


class GetApplicationResponse(BaseModel):
    application: ApplicationSchema


class UpdateApplicationRequest(BaseModel):
    status: str | None = None
    notes: str | None = None


class UpdateArtifactRequest(BaseModel):
    content: str


class UpdateArtifactResponse(BaseModel):
    artifact: ArtifactSchema


# Module 8 additions
class RecordOutcomeRequest(BaseModel):
    outcome_type: str
    responded: bool
    time_to_response_hours: float | None = None
    source: str = "manual"


class RecordOutcomeResponse(BaseModel):
    outcome: OutcomeSchema


class DraftFollowupResponse(BaseModel):
    draft: str


class GmailSyncResponse(BaseModel):
    detected: int


# ---------------------------------------------------------------------------
# Type aliases exposed to other modules
# ---------------------------------------------------------------------------

__all__: list[Any] = [
    "ArtifactSchema",
    "OutcomeSchema",
    "ApplicationSchema",
    "PostingSummarySchema",
    "coerce_artifact_schema",
    "coerce_outcome_schema",
    "coerce_application_schema",
    "DecodeRequest",
    "DecodeResponse",
    "AtsScoreRequest",
    "AtsScoreResponse",
    "DraftRequest",
    "DraftResponse",
    "CreateApplicationRequest",
    "CreateApplicationResponse",
    "SendRequest",
    "ListApplicationsResponse",
    "GetApplicationResponse",
    "UpdateApplicationRequest",
    "UpdateArtifactRequest",
    "UpdateArtifactResponse",
    "RecordOutcomeRequest",
    "RecordOutcomeResponse",
    "DraftFollowupResponse",
    "GmailSyncResponse",
]
