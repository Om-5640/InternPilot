"""Module 9 — Interview Prep endpoints."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.interview_prep import PrepRequest, PrepResponse
from app.services.interview_prep_service import InterviewPrepService

router = APIRouter(tags=["interview-prep"])


@router.post("/interview-prep", status_code=201, response_model=PrepResponse)
async def create_prep(
    body: PrepRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PrepResponse:
    svc = InterviewPrepService(db, current_user.id)
    prep = await svc.generate(body)
    return PrepResponse(prep=prep)


@router.get("/interview-prep/{prep_id}", response_model=PrepResponse)
async def get_prep(
    prep_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PrepResponse:
    svc = InterviewPrepService(db, current_user.id)
    prep = await svc.get(prep_id)
    return PrepResponse(prep=prep)
