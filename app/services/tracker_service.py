"""TrackerService — Module 8: application list/get/update, follow-up drafting, outcome recording.

All queries are scoped to self.user_id. CohortService (global) is called after
recording an outcome to update the company's cross-user signal.
"""
from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import APIError
from app.models.application import Application
from app.models.company import Company
from app.models.outcome import Outcome
from app.models.posting import Posting
from app.schemas.application import ApplicationSchema, coerce_application_schema
from app.services.base import BaseService
from app.services.cohort_service import CohortService

logger = logging.getLogger(__name__)

FOLLOWUP_DAYS: int = 7

_VALID_OUTCOME_TYPES = frozenset(
    {"responded", "no_response", "bounced", "interview", "offer", "rejected"}
)


class TrackerService(BaseService):
    def __init__(self, db: AsyncSession, user_id: uuid.UUID) -> None:
        super().__init__(db, user_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_application_owned(self, application_id: uuid.UUID) -> Application:
        row = (
            await self.db.execute(
                select(Application)
                .where(
                    Application.id == application_id,
                    Application.user_id == self.user_id,
                )
                .options(
                    selectinload(Application.artifacts),
                    selectinload(Application.outcomes),
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise APIError(404, "APPLICATION_NOT_FOUND", "Application not found")
        return row

    async def _get_posting_and_company(
        self, posting_id: uuid.UUID
    ) -> tuple[Posting, Company]:
        row = (
            await self.db.execute(
                select(Posting, Company)
                .join(Company, Posting.company_id == Company.id)
                .where(Posting.id == posting_id)
            )
        ).first()
        if row is None:
            raise APIError(404, "POSTING_NOT_FOUND", "Posting not found")
        return row[0], row[1]

    def _latest_outcome(self, app: Application) -> Outcome | None:
        if not app.outcomes:
            return None
        return sorted(app.outcomes, key=lambda o: o.recorded_at, reverse=True)[0]

    async def _build_schema(self, app: Application) -> ApplicationSchema:
        posting, company = await self._get_posting_and_company(app.posting_id)
        return coerce_application_schema(
            app,
            posting.id,
            posting.title,
            company.name,
            list(app.artifacts),
            outcome=self._latest_outcome(app),
        )

    # ------------------------------------------------------------------
    # list_applications — paginated, optional status filter
    # ------------------------------------------------------------------

    async def list_applications(
        self,
        status: str | None,
        page: int,
        limit: int,
    ) -> dict[str, Any]:
        base_filter = [Application.user_id == self.user_id]
        if status:
            base_filter.append(Application.status == status)

        total = (
            await self.db.execute(
                select(func.count())
                .select_from(Application)
                .where(*base_filter)
            )
        ).scalar_one()

        apps = list(
            (
                await self.db.execute(
                    select(Application)
                    .where(*base_filter)
                    .options(
                        selectinload(Application.artifacts),
                        selectinload(Application.outcomes),
                    )
                    .order_by(Application.last_status_at.desc())
                    .limit(limit)
                    .offset((page - 1) * limit)
                )
            )
            .scalars()
            .all()
        )

        if not apps:
            return {"data": [], "page": page, "limit": limit, "total": int(total)}

        posting_ids = list({a.posting_id for a in apps})
        rows = (
            await self.db.execute(
                select(Posting, Company)
                .join(Company, Posting.company_id == Company.id)
                .where(Posting.id.in_(posting_ids))
            )
        ).all()
        posting_map = {p.id: (p, c) for p, c in rows}

        data = [
            coerce_application_schema(
                a,
                posting_map[a.posting_id][0].id,
                posting_map[a.posting_id][0].title,
                posting_map[a.posting_id][1].name,
                list(a.artifacts),
                outcome=self._latest_outcome(a),
            )
            for a in apps
            if a.posting_id in posting_map
        ]
        return {"data": data, "page": page, "limit": limit, "total": int(total)}

    # ------------------------------------------------------------------
    # get_application
    # ------------------------------------------------------------------

    async def get_application(self, application_id: uuid.UUID) -> ApplicationSchema:
        app = await self._get_application_owned(application_id)
        return await self._build_schema(app)

    # ------------------------------------------------------------------
    # update_application — status and/or notes
    # ------------------------------------------------------------------

    async def update_application(
        self,
        application_id: uuid.UUID,
        status: str | None,
        notes: str | None,
    ) -> ApplicationSchema:
        app = await self._get_application_owned(application_id)
        if status is not None:
            app.status = status
            app.last_status_at = datetime.now(UTC)
        if notes is not None:
            app.notes = notes
        self.db.add(app)
        await self.db.commit()
        app2 = await self._get_application_owned(application_id)
        return await self._build_schema(app2)

    # ------------------------------------------------------------------
    # draft_followup — LLM follow-up message generation
    # ------------------------------------------------------------------

    async def draft_followup(self, application_id: uuid.UUID) -> str:
        from app.llm.router import complete

        app = await self._get_application_owned(application_id)
        posting, company = await self._get_posting_and_company(app.posting_id)

        days_since_applied: int | None = None
        if app.applied_at is not None:
            days_since_applied = max(0, (datetime.now(UTC) - app.applied_at).days)

        system_msg = (
            "You are a career advisor helping an internship applicant write a brief, "
            "professional follow-up message. Be concise (3-5 sentences), friendly, and specific. "
            "Write a complete, ready-to-send email — no placeholder text like [Your Name]."
        )

        context_lines = [
            f"Company: {company.name}",
            f"Position: {posting.title}",
            f"Current status: {app.status}",
        ]
        if days_since_applied is not None:
            context_lines.append(f"Days since applied: {days_since_applied}")
        if app.notes:
            context_lines.append(f"Notes: {app.notes}")

        user_msg = (
            "\n".join(context_lines)
            + "\n\nWrite a follow-up email with a subject line and body. "
            "Reference the specific role and company. Keep it under 150 words."
        )

        return await complete([
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ])

    # ------------------------------------------------------------------
    # record_outcome — create Outcome + trigger cohort recompute
    # ------------------------------------------------------------------

    async def record_outcome(
        self,
        application_id: uuid.UUID,
        outcome_type: str,
        responded: bool,
        time_to_response_hours: float | None,
        source: str,
    ) -> Outcome:
        if outcome_type not in _VALID_OUTCOME_TYPES:
            raise APIError(
                400,
                "INVALID_OUTCOME_TYPE",
                f"outcome_type must be one of {sorted(_VALID_OUTCOME_TYPES)}",
            )

        app = await self._get_application_owned(application_id)

        outcome = Outcome(
            application_id=application_id,
            outcome_type=outcome_type,
            responded=responded,
            time_to_response_hours=time_to_response_hours,
            source=source,
        )
        self.db.add(outcome)

        if responded and app.status not in ("interview", "offer", "rejected"):
            app.status = "responded"
            app.last_status_at = datetime.now(UTC)
            self.db.add(app)

        await self.db.flush()

        posting = await self.db.get(Posting, app.posting_id)
        if posting is not None:
            cohort_svc = CohortService(self.db)
            await cohort_svc.recompute_company_response(posting.company_id)
        else:
            await self.db.commit()

        # Expire only the outcomes relationship so the next GET re-runs the
        # selectinload secondary query. (expire_on_commit=False means SQLAlchemy
        # would otherwise serve the cached empty list from the identity map.)
        self.db.expire(app, attribute_names=["outcomes"])

        return outcome
