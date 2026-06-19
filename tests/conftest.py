"""Shared pytest fixtures.

Requires a live PostgreSQL instance with pgvector.
Set TEST_DATABASE_URL env var, or use the default.

Run:  pytest
      TEST_DATABASE_URL=postgresql+asyncpg://... pytest
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import subprocess
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.database import get_db
from app.main import app
from app.models.application import Application  # noqa: F401 — register model with Base.metadata
from app.models.artifact import Artifact  # noqa: F401 — register model with Base.metadata
from app.models.base import Base
from app.models.company import Company  # noqa: F401 — register model with Base.metadata
from app.models.contact import Contact  # noqa: F401 — register model with Base.metadata
from app.models.evaluation import Evaluation  # noqa: F401 — register model with Base.metadata
from app.models.notification import Notification  # noqa: F401 — register model with Base.metadata
from app.models.outcome import Outcome  # noqa: F401 — register model with Base.metadata
from app.models.posting import Posting  # noqa: F401 — register model with Base.metadata
from app.models.profile import Profile  # noqa: F401 — register model with Base.metadata
from app.models.referral import Referral  # noqa: F401 — register model with Base.metadata
from app.models.research_opportunity import (
    ResearchOpportunity,  # noqa: F401 — register model with Base.metadata
)
from app.models.research_outreach import (
    ResearchOutreach,  # noqa: F401 — register model with Base.metadata
)
from app.models.user import User  # noqa: F401 — register model with Base.metadata

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:testpass@localhost:5433/internpilot_test",
)

# ---------------------------------------------------------------------------
# Silence external HTTP sources — prevent real Firecrawl / USAJobs / Adzuna
# calls from firing during tests. Every test that exercises refresh() already
# mocks the sources it cares about; the rest must return [] by default.
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _mock_external_sources():
    """Return empty lists from sources that make real HTTP calls.

    Tests that specifically want to exercise one of these sources override
    the mock themselves (the last patch wins, so per-test mocks still work).
    """
    with (
        patch(
            "app.sources.firecrawl_india.IndiaFirecrawlSource.fetch",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "app.sources.usajobs.USAJobsSource.fetch",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "app.sources.adzuna.AdzunaSource.fetch",
            new=AsyncMock(return_value=[]),
        ),
    ):
        yield


# ---------------------------------------------------------------------------
# Session-scoped engine: run Alembic migrations once per test run
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(scope="session")
async def test_engine():
    # Export URL so alembic/env.py picks it up via os.environ
    os.environ["TEST_DATABASE_URL"] = TEST_DATABASE_URL

    eng = create_async_engine(TEST_DATABASE_URL, echo=False)

    # Tear down any leftover schema from a previous run.
    # Drop user tables first, then alembic_version so the next upgrade runs clean.
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.execute(text("DROP TABLE IF EXISTS alembic_version"))

    # Bootstrap via Alembic CLI (catches migration drift vs. plain create_all).
    # subprocess avoids the alembic/ dir shadowing the installed package.
    result = await asyncio.to_thread(
        subprocess.run,
        ["uv", "run", "alembic", "upgrade", "head"],
        capture_output=True,
        text=True,
        env={**os.environ, "TEST_DATABASE_URL": TEST_DATABASE_URL},
        cwd=str(pathlib.Path(__file__).parent.parent),
    )
    if result.returncode != 0:
        raise RuntimeError(f"Alembic upgrade failed:\n{result.stderr}")

    yield eng

    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    await eng.dispose()


# ---------------------------------------------------------------------------
# Function-scoped DB session.
# Cleanup uses a separate connection so session state can't block it.
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def db(test_engine):
    session_factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    # Separate connection for teardown — immune to test session state
    async with test_engine.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE TABLE research_outreach, research_opportunities, notifications, "
                "evaluations, referrals, contacts_alumni, outcomes, "
                "artifacts, applications, postings, profiles, companies, users "
                "RESTART IDENTITY CASCADE"
            )
        )


# ---------------------------------------------------------------------------
# HTTP test client with DB dependency overridden to use the test session
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def client(db: AsyncSession):
    async def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Convenience — signed-up user + auth headers
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def auth_headers(client: AsyncClient) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/signup",
        json={"name": "Test User", "email": "test@example.com", "password": "secret123"},
    )
    assert resp.status_code == 201
    token = resp.json()["token"]
    return {"Authorization": f"Bearer {token}"}
