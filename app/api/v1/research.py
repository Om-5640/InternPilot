"""Module 12 — Research Internships endpoints."""
from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.application import ArtifactSchema, coerce_artifact_schema
from app.schemas.research import (
    CreateOutreachRequest,
    PitchRequest,
    ResearchMatchSchema,
    ResearchOutreachSchema,
    UpdateOutreachRequest,
)
from app.services.profile_service import ProfileService
from app.services.research_aggregation_service import (
    ResearchAggregationService,
    make_research_fingerprint,
    refresh_research_background,
)
from app.services.research_service import ResearchService

router = APIRouter(tags=["research"])


# ---------------------------------------------------------------------------
# GET /api/research/opportunities — ranked feed
# ---------------------------------------------------------------------------


@router.get("/research/opportunities")
async def list_research_opportunities(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    # ── Live research refresh (same TTL-cache pattern as /matches) ───────────
    fetching = False
    try:
        profile = await ProfileService(db, current_user.id).get_or_create()
        if profile and profile.research_interests:
            fp = make_research_fingerprint(profile.skills, profile.research_interests)
            if await ResearchAggregationService(db).is_stale(fp):
                asyncio.create_task(
                    refresh_research_background(
                        fp, profile.skills, profile.research_interests
                    )
                )
                fetching = True
    except Exception:  # noqa: BLE001
        pass

    svc = ResearchService(db, current_user.id)
    matches, total = await svc.find_matches(page=page, limit=limit)
    return {
        "data": [m.model_dump() for m in matches],
        "page": page,
        "limit": limit,
        "total": total,
        "fetching": fetching,
    }


# ---------------------------------------------------------------------------
# GET /api/research/opportunities/{id} — single detail
# ---------------------------------------------------------------------------


@router.get("/research/opportunities/{opportunity_id}")
async def get_research_opportunity(
    opportunity_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ResearchMatchSchema:
    svc = ResearchService(db, current_user.id)
    return await svc.get_match(opportunity_id)


# ---------------------------------------------------------------------------
# POST /api/research/pitch — generate cold-email pitch → Artifact
# ---------------------------------------------------------------------------


@router.post("/research/pitch")
async def draft_research_pitch(
    body: PitchRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ArtifactSchema:
    svc = ResearchService(db, current_user.id)
    artifact = await svc.draft_pitch(body.opportunity_id)
    return coerce_artifact_schema(artifact)


# ---------------------------------------------------------------------------
# POST /api/research/outreach — create outreach record
# ---------------------------------------------------------------------------


@router.post("/research/outreach", status_code=201)
async def create_research_outreach(
    body: CreateOutreachRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ResearchOutreachSchema:
    svc = ResearchService(db, current_user.id)
    outreach = await svc.create_outreach(body.opportunity_id, body.pitch_artifact_id)
    return ResearchOutreachSchema.model_validate(outreach)


# ---------------------------------------------------------------------------
# GET /api/research/outreach — list user's outreach
# ---------------------------------------------------------------------------


@router.get("/research/outreach")
async def list_research_outreach(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    svc = ResearchService(db, current_user.id)
    outreach_list = await svc.list_outreach()
    return {"data": [o.model_dump() for o in outreach_list]}


# ---------------------------------------------------------------------------
# PUT /api/research/outreach/{id} — update status
# ---------------------------------------------------------------------------


@router.put("/research/outreach/{outreach_id}")
async def update_research_outreach(
    outreach_id: uuid.UUID,
    body: UpdateOutreachRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ResearchOutreachSchema:
    svc = ResearchService(db, current_user.id)
    outreach = await svc.update_status(outreach_id, body.status)
    return ResearchOutreachSchema.model_validate(outreach)
