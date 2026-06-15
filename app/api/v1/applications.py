"""Module 7 + 8 — Application Assistant + Tracker endpoints."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import APIError
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.application import (
    AtsScoreRequest,
    AtsScoreResponse,
    CreateApplicationRequest,
    CreateApplicationResponse,
    DecodeRequest,
    DecodeResponse,
    DraftFollowupResponse,
    DraftRequest,
    DraftResponse,
    GetApplicationResponse,
    ListApplicationsResponse,
    RecordOutcomeRequest,
    RecordOutcomeResponse,
    SendRequest,
    UpdateApplicationRequest,
    UpdateArtifactRequest,
    UpdateArtifactResponse,
    coerce_outcome_schema,
)
from app.services.application_service import ApplicationService
from app.services.tracker_service import TrackerService

router = APIRouter(tags=["applications"])

_APP_STATUS_VALUES = {
    "saved", "applied", "viewed", "responded",
    "interview", "offer", "rejected", "ghosted",
}
_ARTIFACT_TYPE_VALUES = {
    "resume", "cover_letter", "email", "followup", "referral_intro",
}
_CHANNEL_VALUES = {"portal", "email", "referral"}


# ---------------------------------------------------------------------------
# Utility endpoints (no application record yet) — ApplicationService
# ---------------------------------------------------------------------------


@router.post("/applications/decode", response_model=DecodeResponse)
async def decode_posting(
    body: DecodeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DecodeResponse:
    svc = ApplicationService(db, current_user.id)
    result = await svc.decode(body.posting_id)
    return DecodeResponse(**result)


@router.post("/applications/ats-score", response_model=AtsScoreResponse)
async def ats_score(
    body: AtsScoreRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AtsScoreResponse:
    svc = ApplicationService(db, current_user.id)
    result = await svc.ats_score(body.posting_id, body.content)
    return AtsScoreResponse(**result)


@router.post("/applications/draft", response_model=DraftResponse)
async def draft_artifact(
    body: DraftRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DraftResponse:
    if body.type not in _ARTIFACT_TYPE_VALUES:
        raise APIError(400, "INVALID_ARTIFACT_TYPE", f"type must be one of {sorted(_ARTIFACT_TYPE_VALUES)}")
    if body.channel not in _CHANNEL_VALUES:
        raise APIError(400, "INVALID_CHANNEL", f"channel must be one of {sorted(_CHANNEL_VALUES)}")
    svc = ApplicationService(db, current_user.id)
    artifact = await svc.draft(body.posting_id, body.type, body.channel)
    return DraftResponse(artifact=artifact)


# ---------------------------------------------------------------------------
# Application CRUD — create/send via ApplicationService
# ---------------------------------------------------------------------------


@router.post("/applications", status_code=201, response_model=CreateApplicationResponse)
async def create_application(
    body: CreateApplicationRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CreateApplicationResponse:
    if body.channel not in _CHANNEL_VALUES:
        raise APIError(400, "INVALID_CHANNEL", f"channel must be one of {sorted(_CHANNEL_VALUES)}")
    svc = ApplicationService(db, current_user.id)
    application = await svc.create_application(body.posting_id, body.channel, body.artifact_id)
    return CreateApplicationResponse(application=application)


@router.post("/applications/{application_id}/send", response_model=GetApplicationResponse)
async def send_application(
    application_id: uuid.UUID,
    body: SendRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GetApplicationResponse:
    if body.via != "gmail":
        raise APIError(400, "UNSUPPORTED_SEND_METHOD", "Only via='gmail' is supported")
    svc = ApplicationService(db, current_user.id)
    application = await svc.send(application_id, body.via)
    return GetApplicationResponse(application=application)


# ---------------------------------------------------------------------------
# Application list/get/update — TrackerService (Module 8)
# ---------------------------------------------------------------------------


@router.get("/applications", response_model=ListApplicationsResponse)
async def list_applications(
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ListApplicationsResponse:
    if status is not None and status not in _APP_STATUS_VALUES:
        raise APIError(400, "INVALID_STATUS", f"status must be one of {sorted(_APP_STATUS_VALUES)}")
    svc = TrackerService(db, current_user.id)
    result = await svc.list_applications(status, page, limit)
    return ListApplicationsResponse(**result)


@router.get("/applications/{application_id}", response_model=GetApplicationResponse)
async def get_application(
    application_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GetApplicationResponse:
    svc = TrackerService(db, current_user.id)
    application = await svc.get_application(application_id)
    return GetApplicationResponse(application=application)


@router.put("/applications/{application_id}", response_model=GetApplicationResponse)
async def update_application(
    application_id: uuid.UUID,
    body: UpdateApplicationRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GetApplicationResponse:
    if body.status is not None and body.status not in _APP_STATUS_VALUES:
        raise APIError(400, "INVALID_STATUS", f"status must be one of {sorted(_APP_STATUS_VALUES)}")
    svc = TrackerService(db, current_user.id)
    application = await svc.update_application(application_id, body.status, body.notes)
    return GetApplicationResponse(application=application)


# ---------------------------------------------------------------------------
# Module 8 additions — follow-up + outcome
# ---------------------------------------------------------------------------


@router.post(
    "/applications/{application_id}/followup",
    response_model=DraftFollowupResponse,
)
async def draft_followup(
    application_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DraftFollowupResponse:
    svc = TrackerService(db, current_user.id)
    draft = await svc.draft_followup(application_id)
    return DraftFollowupResponse(draft=draft)


@router.post(
    "/applications/{application_id}/outcome",
    status_code=201,
    response_model=RecordOutcomeResponse,
)
async def record_outcome(
    application_id: uuid.UUID,
    body: RecordOutcomeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RecordOutcomeResponse:
    svc = TrackerService(db, current_user.id)
    outcome = await svc.record_outcome(
        application_id,
        body.outcome_type,
        body.responded,
        body.time_to_response_hours,
        body.source,
    )
    return RecordOutcomeResponse(outcome=coerce_outcome_schema(outcome))


# ---------------------------------------------------------------------------
# Artifact editing
# ---------------------------------------------------------------------------


@router.put("/artifacts/{artifact_id}", response_model=UpdateArtifactResponse)
async def update_artifact(
    artifact_id: uuid.UUID,
    body: UpdateArtifactRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UpdateArtifactResponse:
    svc = ApplicationService(db, current_user.id)
    artifact = await svc.update_artifact(artifact_id, body.content)
    return UpdateArtifactResponse(artifact=artifact)
