"""Smoke test: run /replay on the live DB and print the IQ trend curve."""
from __future__ import annotations

import asyncio
import os

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Import ALL models so SQLAlchemy's registry can resolve relationships
import app.models.application  # noqa: F401
import app.models.artifact  # noqa: F401
import app.models.company  # noqa: F401
import app.models.contact  # noqa: F401
import app.models.evaluation  # noqa: F401
import app.models.interview_prep  # noqa: F401
import app.models.outcome  # noqa: F401
import app.models.posting  # noqa: F401
import app.models.profile  # noqa: F401
import app.models.referral  # noqa: F401
import app.models.user  # noqa: F401
from app.services.evaluation_service import EvaluationService

DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:testpass@localhost:5433/internpilot",
)


async def main() -> None:
    engine = create_async_engine(DB_URL, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as session:
        svc = EvaluationService(session)

        # How many outcomes exist?
        now_row = await svc.evaluate_now()
        print(f"evaluate_now: n_outcomes={now_row.n_outcomes} iq={now_row.platform_iq:.2f} "
              f"brier={now_row.response_brier:.4f} ghost_f1={now_row.ghost_f1:.4f} "
              f"model={now_row.model_version}")

    async with factory() as session:
        svc = EvaluationService(session)
        rows = await svc.build_history()
        print(f"\nbuild_history: {len(rows)} checkpoint(s)")
        for i, r in enumerate(rows, 1):
            print(
                f"  [{i}] date={r.run_at.date()}  n={r.n_outcomes}  "
                f"iq={r.platform_iq:.2f}  brier={r.response_brier:.4f}  "
                f"ghost_f1={r.ghost_f1:.4f}  model={r.model_version}"
            )

        if not rows:
            print("  (not enough outcomes for a checkpoint — need at least 15)")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
