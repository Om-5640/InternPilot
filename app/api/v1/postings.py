"""Postings & aggregation endpoints — Module 2."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import APIError
from app.core.security import get_current_user
from app.models.user import User, UserRole
from app.schemas.posting import (
    ImportUrlRequest,
    PostingGhostDetail,
    PostingListResponse,
    PostingResponse,
    RefreshResponse,
)
from app.services.aggregation_service import AggregationService
from app.services.ghost_service import GhostService

router = APIRouter(tags=["postings"])


# ---------------------------------------------------------------------------
# Dependency: admin-only gate
# ---------------------------------------------------------------------------

async def get_admin_user(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != UserRole.admin:
        raise APIError(403, "FORBIDDEN", "Admin access required")
    return current_user


# ---------------------------------------------------------------------------
# POST /aggregation/refresh — ADMIN ONLY
# ---------------------------------------------------------------------------

@router.post("/aggregation/refresh", status_code=202)
async def refresh_postings(
    _: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
) -> RefreshResponse:
    svc = AggregationService(db)
    counts = await svc.refresh()
    return RefreshResponse(**counts)


# ---------------------------------------------------------------------------
# POST /postings/import — authenticated; must come before /{posting_id}
# ---------------------------------------------------------------------------

@router.post("/postings/import", status_code=201)
async def import_posting(
    body: ImportUrlRequest,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PostingResponse:
    svc = AggregationService(db)
    schema = await svc.import_from_url(body.url)
    return PostingResponse(posting=schema)


# ---------------------------------------------------------------------------
# GET /postings — auth-required, not user-scoped
# ---------------------------------------------------------------------------

@router.get("/postings")
async def list_postings(
    work_mode: str | None = Query(default=None),
    company: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PostingListResponse:
    svc = AggregationService(db)
    schemas, total = await svc.list_postings(
        work_mode=work_mode,
        company=company,
        page=page,
        limit=limit,
    )
    return PostingListResponse(data=schemas, page=page, limit=limit, total=total)


# ---------------------------------------------------------------------------
# GET /postings/{posting_id}/ghost — ghost detail; must come before /{posting_id}
# ---------------------------------------------------------------------------


@router.get("/postings/{posting_id}/ghost")
async def get_posting_ghost(
    posting_id: uuid.UUID,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PostingGhostDetail:
    svc = GhostService(db)
    detail = await svc.rescore_posting(posting_id)
    if detail is None:
        raise APIError(404, "POSTING_NOT_FOUND", "Posting not found")
    return detail


# ---------------------------------------------------------------------------
# GET /postings/{posting_id} — auth-required, not user-scoped
# ---------------------------------------------------------------------------

@router.get("/postings/{posting_id}")
async def get_posting(
    posting_id: uuid.UUID,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PostingResponse:
    svc = AggregationService(db)
    schema = await svc.get_posting(posting_id)
    if schema is None:
        raise APIError(404, "POSTING_NOT_FOUND", "Posting not found")
    return PostingResponse(posting=schema)
