"""Data-isolation base service.

Every feature service that touches user-owned rows MUST extend BaseService and
call ``self._scope(stmt)`` (or ``.where(Model.user_id == self.user_id)``) on
every SELECT / UPDATE / DELETE.  This ensures that Module N can never read
another user's rows — see CLAUDE.md §Data Isolation for the full rule.
"""
from __future__ import annotations

import uuid

from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession


class BaseService:
    def __init__(self, db: AsyncSession, user_id: uuid.UUID) -> None:
        self.db = db
        self.user_id = user_id

    def _scope(self, stmt: Select[tuple[object, ...]]) -> Select[tuple[object, ...]]:
        """Apply ``WHERE user_id = :self.user_id`` to *stmt*."""
        # Concrete services pass the correct column; this helper is a reminder
        # that every query MUST be scoped.  Call it and add your own .where() if
        # the model uses a different FK column name.
        raise NotImplementedError(
            "Call stmt.where(YourModel.user_id == self.user_id) in your service"
        )
