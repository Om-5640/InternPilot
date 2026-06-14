"""Profile router — Module 1. All logic lives in ProfileService."""
from __future__ import annotations

from fastapi import APIRouter, Depends, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.profile import (
    GithubUrlRequest,
    PreferencesUpdateRequest,
    ProfileResponse,
    ProfileUpdateRequest,
    StrengthResponse,
    coerce_profile_schema,
)
from app.services.profile_service import ProfileService

router = APIRouter(prefix="/profile")


def _svc(current_user: User, db: AsyncSession) -> ProfileService:
    return ProfileService(db=db, user_id=current_user.id)


@router.post("/resume", response_model=ProfileResponse)
async def upload_resume(
    file: UploadFile,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProfileResponse:
    profile = await _svc(current_user, db).parse_resume(file)
    return ProfileResponse(profile=coerce_profile_schema(profile))


@router.post("/github", response_model=ProfileResponse)
async def pull_github(
    body: GithubUrlRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProfileResponse:
    profile = await _svc(current_user, db).pull_github(body.github_url)
    return ProfileResponse(profile=coerce_profile_schema(profile))


@router.get("", response_model=ProfileResponse)
async def get_profile(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProfileResponse:
    profile = await _svc(current_user, db).get_or_create()
    return ProfileResponse(profile=coerce_profile_schema(profile))


@router.put("", response_model=ProfileResponse)
async def update_profile(
    body: ProfileUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProfileResponse:
    profile = await _svc(current_user, db).update_profile(body)
    return ProfileResponse(profile=coerce_profile_schema(profile))


@router.put("/preferences", response_model=ProfileResponse)
async def update_preferences(
    body: PreferencesUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProfileResponse:
    profile = await _svc(current_user, db).update_preferences(body)
    return ProfileResponse(profile=coerce_profile_schema(profile))


@router.get("/strength", response_model=StrengthResponse)
async def get_strength(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StrengthResponse:
    strength, gaps = await _svc(current_user, db).get_strength()
    return StrengthResponse(profile_strength=strength, gaps=gaps)
