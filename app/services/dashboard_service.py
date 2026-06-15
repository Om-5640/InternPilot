"""Module 11 — DashboardService.

Aggregates user-scoped pipeline metrics and GLOBAL platform IQ.
All application/outcome queries are scoped to self.user_id (BaseService rule).
Platform IQ and iq_trend are GLOBAL — same value for every user.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.application import Application
from app.models.artifact import Artifact
from app.models.outcome import Outcome
from app.models.posting import Posting
from app.schemas.dashboard import DashboardSummary, DigestResponse, PipelineCounts
from app.services.base import BaseService
from app.services.evaluation_service import EvaluationService
from app.services.tracker_service import FOLLOWUP_DAYS

HOURS_PER_WASTED_APP: float = 2.0
DRAFT_TIME_SAVED_HOURS: float = 1.5

_GHOST_OUTCOME_TYPES = frozenset({"no_response", "bounced"})
_POSITIVE_OUTCOME_TYPES = frozenset({"responded", "interview", "offer"})


class DashboardService(BaseService):
    def __init__(self, db: AsyncSession, user_id: uuid.UUID) -> None:
        super().__init__(db, user_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _load_apps(self) -> list[Application]:
        return list(
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

    def _pipeline_from_apps(self, apps: list[Application]) -> PipelineCounts:
        counts: dict[str, int] = {
            "saved": 0,
            "applied": 0,
            "viewed": 0,
            "responded": 0,
            "interview": 0,
            "offer": 0,
            "rejected": 0,
            "ghosted": 0,
        }
        for app in apps:
            if app.status == "applied":
                if any(o.outcome_type in _GHOST_OUTCOME_TYPES for o in app.outcomes):
                    counts["ghosted"] += 1
                else:
                    counts["applied"] += 1
            elif app.status in counts:
                counts[app.status] += 1
        return PipelineCounts(**counts)

    def _response_rate(self, pipeline: PipelineCounts) -> float:
        denominator = (
            pipeline.applied
            + pipeline.viewed
            + pipeline.responded
            + pipeline.interview
            + pipeline.offer
            + pipeline.rejected
            + pipeline.ghosted
        )
        if denominator == 0:
            return 0.0
        numerator = pipeline.responded + pipeline.interview + pipeline.offer
        return numerator / denominator

    async def _ghosts_avoided(self, apps: list[Application]) -> int:
        applied_posting_ids = {app.posting_id for app in apps}
        stmt = select(func.count()).select_from(Posting).where(Posting.is_ghost == True)  # noqa: E712
        if applied_posting_ids:
            stmt = stmt.where(Posting.id.not_in(list(applied_posting_ids)))
        result = await self.db.scalar(stmt)
        return int(result or 0)

    async def _draft_count(self) -> int:
        result = await self.db.scalar(
            select(func.count())
            .select_from(Artifact)
            .where(
                Artifact.user_id == self.user_id,
                Artifact.type == "cover_letter",
            )
        )
        return int(result or 0)

    async def _platform_iq_and_trend(self) -> tuple[float, list[float]]:
        eval_svc = EvaluationService(self.db)
        latest = await eval_svc.get_latest_formula()
        iq = latest.platform_iq if latest is not None else 0.0
        history = await eval_svc.get_history_rows()
        trend = [r.platform_iq for r in history]
        return iq, trend

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_summary(self) -> DashboardSummary:
        apps = await self._load_apps()
        pipeline = self._pipeline_from_apps(apps)
        response_rate = self._response_rate(pipeline)
        ghosts_avoided = await self._ghosts_avoided(apps)
        drafts = await self._draft_count()
        time_saved = (
            ghosts_avoided * HOURS_PER_WASTED_APP
            + drafts * DRAFT_TIME_SAVED_HOURS
        )
        platform_iq, iq_trend = await self._platform_iq_and_trend()
        return DashboardSummary(
            pipeline=pipeline,
            response_rate=response_rate,
            ghosts_avoided=ghosts_avoided,
            time_saved_hours=time_saved,
            platform_iq=platform_iq,
            iq_trend=iq_trend,
        )

    async def get_digest(self) -> DigestResponse:
        apps = await self._load_apps()

        # new_matches: active non-ghost postings user has not yet applied to
        applied_posting_ids = {app.posting_id for app in apps}
        match_stmt = (
            select(func.count())
            .select_from(Posting)
            .where(Posting.is_ghost == False, Posting.status == "active")  # noqa: E712
        )
        if applied_posting_ids:
            match_stmt = match_stmt.where(
                Posting.id.not_in(list(applied_posting_ids))
            )
        new_matches = int(await self.db.scalar(match_stmt) or 0)

        # followup_due: applied + no positive outcome + applied_at ≥ FOLLOWUP_DAYS ago
        cutoff = datetime.now(UTC) - timedelta(days=FOLLOWUP_DAYS)
        followup_count = 0
        for app in apps:
            if app.status != "applied":
                continue
            if app.applied_at is None or app.applied_at > cutoff:
                continue
            if any(o.outcome_type in _POSITIVE_OUTCOME_TYPES for o in app.outcomes):
                continue
            followup_count += 1

        # recent_responses: positive outcome in last 7 days for user's apps
        week_ago = datetime.now(UTC) - timedelta(days=7)
        app_ids = [app.id for app in apps]
        if app_ids:
            recent = await self.db.scalar(
                select(func.count())
                .select_from(Outcome)
                .where(
                    Outcome.application_id.in_(app_ids),
                    Outcome.outcome_type.in_(list(_POSITIVE_OUTCOME_TYPES)),
                    Outcome.recorded_at > week_ago,
                )
            )
            recent_responses = int(recent or 0)
        else:
            recent_responses = 0

        ghosts_avoided = await self._ghosts_avoided(apps)
        platform_iq, _ = await self._platform_iq_and_trend()

        return DigestResponse(
            new_matches=new_matches,
            followup_due=followup_count,
            recent_responses=recent_responses,
            ghosts_avoided=ghosts_avoided,
            platform_iq=platform_iq,
        )
