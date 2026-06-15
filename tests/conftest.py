"""Shared pytest fixtures.

Requires a live PostgreSQL instance with pgvector.
Set TEST_DATABASE_URL env var, or use the default.

Run:  pytest
      TEST_DATABASE_URL=postgresql+asyncpg://... pytest
"""
from __future__ import annotations

import os

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
from app.models.interview_prep import (
    InterviewPrep,  # noqa: F401 — register model with Base.metadata
)
from app.models.outcome import Outcome  # noqa: F401 — register model with Base.metadata
from app.models.posting import Posting  # noqa: F401 — register model with Base.metadata
from app.models.profile import Profile  # noqa: F401 — register model with Base.metadata
from app.models.referral import Referral  # noqa: F401 — register model with Base.metadata
from app.models.user import User  # noqa: F401 — register model with Base.metadata

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/internpilot_test",
)


# ---------------------------------------------------------------------------
# Session-scoped engine: create tables once per test run
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(scope="session")
async def test_engine():
    eng = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with eng.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.execute(text(
            "DO $$ BEGIN "
            "CREATE TYPE user_role AS ENUM ('student', 'admin'); "
            "EXCEPTION WHEN duplicate_object THEN null; END $$"
        ))
        await conn.execute(text(
            "DO $$ BEGIN "
            "CREATE TYPE auth_provider_enum AS ENUM ('password', 'google'); "
            "EXCEPTION WHEN duplicate_object THEN null; END $$"
        ))
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
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
                "TRUNCATE TABLE referrals, contacts_alumni, outcomes, artifacts, "
                "applications, postings, profiles, companies, users "
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
