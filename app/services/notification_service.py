"""Module 11 — NotificationService.

All queries are scoped to self.user_id. generate() is idempotent:
it skips notifications whose (user_id, type, content) already exist.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import APIError
from app.models.application import Application
from app.models.company import Company
from app.models.interview_prep import InterviewPrep
from app.models.notification import Notification
from app.models.posting import Posting
from app.services.base import BaseService
from app.services.tracker_service import FOLLOWUP_DAYS

_POSITIVE_OUTCOME_TYPES = frozenset({"responded", "interview", "offer"})
_RECENT_DAYS: int = 7


class NotificationService(BaseService):
    def __init__(self, db: AsyncSession, user_id: uuid.UUID) -> None:
        super().__init__(db, user_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _existing_contents(self, ntype: str) -> set[str]:
        rows = list(
            (
                await self.db.execute(
                    select(Notification.content).where(
                        Notification.user_id == self.user_id,
                        Notification.type == ntype,
                    )
                )
            ).scalars()
        )
        return set(rows)

    async def _add(self, ntype: str, content: str, existing: set[str]) -> None:
        if content in existing:
            return
        self.db.add(
            Notification(user_id=self.user_id, type=ntype, content=content)
        )
        existing.add(content)

    # ------------------------------------------------------------------
    # generate — idempotent, creates missing notifications
    # ------------------------------------------------------------------

    async def generate(self) -> None:
        now = datetime.now(UTC)

        # Load user's apps with outcomes + posting+company
        apps = list(
            (
                await self.db.execute(
                    select(Application)
                    .where(Application.user_id == self.user_id)
                    .options(selectinload(Application.outcomes))
                )
            )
            .scalars()
            .all()
        )
        if not apps:
            return

        app_ids = [a.id for a in apps]

        # Resolve posting + company for each app in one query
        posting_rows = (
            await self.db.execute(
                select(Posting, Company)
                .join(Company, Posting.company_id == Company.id)
                .where(Posting.id.in_([a.posting_id for a in apps]))
            )
        ).all()
        posting_map: dict[uuid.UUID, tuple[str, str]] = {
            p.id: (p.title, c.name) for p, c in posting_rows
        }

        # Existing contents per type (deduplication)
        followup_existing = await self._existing_contents("followup_due")
        response_existing = await self._existing_contents("response")
        status_existing = await self._existing_contents("status_change")
        prep_existing = await self._existing_contents("prep_ready")

        cutoff_followup = now - timedelta(days=FOLLOWUP_DAYS)
        cutoff_recent = now - timedelta(days=_RECENT_DAYS)

        # Existing prep sessions for this user
        raw_prep_ids = (
            (
                await self.db.execute(
                    select(InterviewPrep.application_id).where(
                        InterviewPrep.user_id == self.user_id,
                        InterviewPrep.application_id.in_(app_ids),
                    )
                )
            )
            .scalars()
            .all()
        )
        prep_app_ids: set[uuid.UUID] = {aid for aid in raw_prep_ids if aid is not None}

        for app in apps:
            role, company = posting_map.get(app.posting_id, ("this role", "the company"))
            outcome_types = {o.outcome_type for o in app.outcomes}
            positive = outcome_types & _POSITIVE_OUTCOME_TYPES

            # followup_due
            if (
                app.status == "applied"
                and app.applied_at is not None
                and app.applied_at <= cutoff_followup
                and not positive
            ):
                content = (
                    f"Follow up on your {role} application at {company} — "
                    f"{FOLLOWUP_DAYS} days since you applied."
                )
                await self._add("followup_due", content, followup_existing)

            # response — recent positive outcome
            recent_positive = [
                o for o in app.outcomes
                if o.outcome_type in _POSITIVE_OUTCOME_TYPES
                and o.recorded_at >= cutoff_recent
            ]
            for outcome in recent_positive:
                label = outcome.outcome_type.replace("_", " ")
                content = f"{company} responded to your {role} application: {label}."
                await self._add("response", content, response_existing)

            # status_change — status recently flipped to interview/offer/rejected
            if (
                app.status in ("interview", "offer", "rejected")
                and app.last_status_at >= cutoff_recent
            ):
                content = (
                    f"Your {role} application at {company} moved to {app.status}."
                )
                await self._add("status_change", content, status_existing)

            # prep_ready — positive outcome and no prep session yet
            if positive and app.id not in prep_app_ids:
                content = (
                    f"You're advancing at {company}! Get AI interview prep for your {role} role."
                )
                await self._add("prep_ready", content, prep_existing)

        await self.db.commit()

    # ------------------------------------------------------------------
    # list_notifications — newest first, user-scoped
    # ------------------------------------------------------------------

    async def list_notifications(self) -> list[Notification]:
        return list(
            (
                await self.db.execute(
                    select(Notification)
                    .where(Notification.user_id == self.user_id)
                    .order_by(Notification.created_at.desc())
                )
            )
            .scalars()
            .all()
        )

    # ------------------------------------------------------------------
    # mark_read — 404 if not owned by current user
    # ------------------------------------------------------------------

    async def mark_read(self, notification_id: uuid.UUID) -> Notification:
        row = (
            await self.db.execute(
                select(Notification).where(
                    Notification.id == notification_id,
                    Notification.user_id == self.user_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise APIError(404, "NOTIFICATION_NOT_FOUND", "Notification not found")
        row.read = True
        self.db.add(row)
        await self.db.commit()
        await self.db.refresh(row)
        return row
