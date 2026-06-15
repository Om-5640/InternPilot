"""Module 11 — Notification endpoints."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.notification import NotificationSchema
from app.services.notification_service import NotificationService

router = APIRouter(tags=["notifications"])


@router.get("/notifications", response_model=list[NotificationSchema])
async def list_notifications(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[NotificationSchema]:
    rows = await NotificationService(db, current_user.id).list_notifications()
    return [NotificationSchema.model_validate(r) for r in rows]


@router.put("/notifications/{notification_id}/read", response_model=NotificationSchema)
async def mark_notification_read(
    notification_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NotificationSchema:
    row = await NotificationService(db, current_user.id).mark_read(notification_id)
    return NotificationSchema.model_validate(row)
