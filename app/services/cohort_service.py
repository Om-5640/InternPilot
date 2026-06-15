"""CohortService — Module 8: cross-user company response-rate aggregation.

PRIVACY MODEL:
  - Operates on aggregate COUNTS only — never surfaces one user's rows to another.
  - Counts every application across all users (no user_id filter).
  - Updates company.cohort_applied_count and company.responsiveness_score.
"""
from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.application import Application
from app.models.company import Company
from app.models.outcome import Outcome
from app.models.posting import Posting

MIN_APPS: int = 5


class CohortService:
    """Not a BaseService — operates globally across all users."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def recompute_company_response(self, company_id: uuid.UUID) -> None:
        """Recompute cohort response rate for a company.

        Counts applied = all applications to any posting from this company.
        Counts responded = applications with at least one Outcome where responded=True.
        When applied >= MIN_APPS, sets responsiveness_score = responded / applied.
        Always updates cohort_applied_count.
        """
        company = await self.db.get(Company, company_id)
        if company is None:
            return

        applied_count_result = await self.db.execute(
            select(func.count(Application.id))
            .join(Posting, Application.posting_id == Posting.id)
            .where(Posting.company_id == company_id)
        )
        applied_count: int = applied_count_result.scalar_one() or 0

        responded_count_result = await self.db.execute(
            select(func.count(Application.id.distinct()))
            .join(Posting, Application.posting_id == Posting.id)
            .join(Outcome, Outcome.application_id == Application.id)
            .where(Posting.company_id == company_id)
            .where(Outcome.responded.is_(True))
        )
        responded_count: int = responded_count_result.scalar_one() or 0

        company.cohort_applied_count = applied_count
        if applied_count >= MIN_APPS:
            company.responsiveness_score = (
                responded_count / applied_count if applied_count > 0 else 1.0
            )
        self.db.add(company)
        await self.db.commit()
