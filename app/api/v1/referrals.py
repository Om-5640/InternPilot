"""Module 6 — Referral / Warm-Intro Finder endpoints."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import APIError
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.referral import (
    CreateReferralRequest,
    CreateReferralResponse,
    FindCandidatesResponse,
    ListReferralsResponse,
    UpdateReferralRequest,
    UpdateReferralResponse,
)
from app.services.referral_service import ReferralService

router = APIRouter(tags=["referrals"])


@router.get("/referrals/candidates", response_model=FindCandidatesResponse)
async def find_candidates(
    company_id: uuid.UUID | None = Query(default=None),
    posting_id: uuid.UUID | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FindCandidatesResponse:
    if company_id is None and posting_id is None:
        raise APIError(400, "MISSING_PARAMETER", "Provide company_id or posting_id")
    svc = ReferralService(db, current_user.id)
    candidates = await svc.find_candidates(company_id=company_id, posting_id=posting_id)
    return FindCandidatesResponse(data=candidates)


@router.post("/referrals", status_code=201, response_model=CreateReferralResponse)
async def create_referral(
    body: CreateReferralRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CreateReferralResponse:
    svc = ReferralService(db, current_user.id)
    referral = await svc.create_referral(
        company_id=body.company_id,
        contact_id=body.contact_id,
        posting_id=body.posting_id,
    )
    return CreateReferralResponse(referral=referral)


@router.get("/referrals", response_model=ListReferralsResponse)
async def list_referrals(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ListReferralsResponse:
    svc = ReferralService(db, current_user.id)
    referrals = await svc.list_referrals()
    return ListReferralsResponse(data=referrals)


@router.put("/referrals/{referral_id}", response_model=UpdateReferralResponse)
async def update_referral(
    referral_id: uuid.UUID,
    body: UpdateReferralRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UpdateReferralResponse:
    svc = ReferralService(db, current_user.id)
    referral = await svc.update_status(referral_id, body.status)
    return UpdateReferralResponse(referral=referral)
