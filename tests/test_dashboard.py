"""Tests for Module 11 — Dashboard."""
from __future__ import annotations

import base64
import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.application import Application
from app.models.artifact import Artifact
from app.models.company import Company
from app.models.outcome import Outcome
from app.models.posting import Posting

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _company(db: AsyncSession) -> Company:
    name = f"Co-{uuid.uuid4().hex[:8]}"
    c = Company(
        name=name,
        normalized_name=name.lower(),
        domain=None,
        industry=None,
        size=None,
        ghost_history_score=0.0,
        responsiveness_score=1.0,
    )
    db.add(c)
    return c


def _posting(db: AsyncSession, company_id: uuid.UUID, *, is_ghost: bool = False) -> Posting:
    p = Posting(
        company_id=company_id,
        title="Intern",
        description="desc",
        requirements=[],
        work_mode="remote",
        source="manual",
        source_url=f"https://example.com/{uuid.uuid4().hex}",
        dedup_key=uuid.uuid4().hex[:16],
        posted_at=datetime.now(UTC).isoformat(),
        last_seen_at=datetime.now(UTC).isoformat(),
        is_ghost=is_ghost,
        status="active",
    )
    db.add(p)
    return p


def _application(
    db: AsyncSession,
    user_id: uuid.UUID,
    posting_id: uuid.UUID,
    *,
    status: str = "applied",
    applied_at: datetime | None = None,
) -> Application:
    a = Application(
        user_id=user_id,
        posting_id=posting_id,
        channel="direct",
        status=status,
        applied_at=applied_at or datetime.now(UTC),
    )
    db.add(a)
    return a


def _outcome(
    db: AsyncSession,
    application_id: uuid.UUID,
    outcome_type: str,
    *,
    responded: bool = False,
) -> Outcome:
    o = Outcome(
        application_id=application_id,
        outcome_type=outcome_type,
        responded=responded,
        source="manual",
    )
    db.add(o)
    return o


async def _signup_and_token(client: AsyncClient, email: str) -> str:
    resp = await client.post(
        "/api/auth/signup",
        json={"name": "User", "email": email, "password": "secret123"},
    )
    assert resp.status_code == 201
    return resp.json()["token"]


def _user_id_from_token(token: str) -> uuid.UUID:
    payload_b64 = token.split(".")[1]
    payload_b64 += "=" * (-len(payload_b64) % 4)
    payload = json.loads(base64.b64decode(payload_b64))
    return uuid.UUID(payload["sub"])


# ---------------------------------------------------------------------------
# Pipeline counts
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pipeline_counts(client: AsyncClient, auth_headers: dict, db: AsyncSession):
    token = auth_headers["Authorization"].split(" ")[1]
    user_id = _user_id_from_token(token)

    c = _company(db)
    await db.flush()

    p = _posting(db, c.id)
    await db.flush()

    # saved app
    _application(db, user_id, p.id, status="saved", applied_at=None)
    # applied app with no outcome
    _application(db, user_id, p.id, status="applied")
    # ghosted: applied + no_response outcome
    a_ghost = _application(db, user_id, p.id, status="applied")
    # responded
    _application(db, user_id, p.id, status="responded")
    await db.flush()

    _outcome(db, a_ghost.id, "no_response", responded=False)
    await db.commit()

    resp = await client.get("/api/dashboard", headers=auth_headers)
    assert resp.status_code == 200
    pl = resp.json()["pipeline"]
    assert pl["saved"] == 1
    assert pl["applied"] == 1
    assert pl["ghosted"] == 1
    assert pl["responded"] == 1


# ---------------------------------------------------------------------------
# Response rate zero-guard
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_response_rate_zero_guard(client: AsyncClient, auth_headers: dict):
    resp = await client.get("/api/dashboard", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["response_rate"] == 0.0


# ---------------------------------------------------------------------------
# Response rate calculation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_response_rate(client: AsyncClient, auth_headers: dict, db: AsyncSession):
    token = auth_headers["Authorization"].split(" ")[1]
    user_id = _user_id_from_token(token)

    c = _company(db)
    await db.flush()
    p = _posting(db, c.id)
    await db.flush()

    # 2 applied, 1 responded → denominator=3, numerator=1
    _application(db, user_id, p.id, status="applied")
    _application(db, user_id, p.id, status="applied")
    _application(db, user_id, p.id, status="responded")
    await db.commit()

    resp = await client.get("/api/dashboard", headers=auth_headers)
    assert resp.status_code == 200
    rate = resp.json()["response_rate"]
    assert abs(rate - 1 / 3) < 1e-6


# ---------------------------------------------------------------------------
# Ghosts avoided + time_saved_hours
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ghosts_avoided_and_time_saved(
    client: AsyncClient, auth_headers: dict, db: AsyncSession
):
    token = auth_headers["Authorization"].split(" ")[1]
    user_id = _user_id_from_token(token)

    c = _company(db)
    await db.flush()

    # 2 ghost postings the user never applied to
    _posting(db, c.id, is_ghost=True)
    _posting(db, c.id, is_ghost=True)
    # 1 ghost posting the user DID apply to (should NOT count as avoided)
    ghost_applied = _posting(db, c.id, is_ghost=True)
    await db.flush()

    _application(db, user_id, ghost_applied.id, status="applied")
    await db.commit()

    resp = await client.get("/api/dashboard", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ghosts_avoided"] == 2
    # 2 ghosts × 2.0 + 0 drafts × 1.5 = 4.0
    assert abs(data["time_saved_hours"] - 4.0) < 1e-6


@pytest.mark.asyncio
async def test_time_saved_includes_drafts(
    client: AsyncClient, auth_headers: dict, db: AsyncSession
):
    token = auth_headers["Authorization"].split(" ")[1]
    user_id = _user_id_from_token(token)

    c = _company(db)
    await db.flush()
    p = _posting(db, c.id)
    await db.flush()
    app = _application(db, user_id, p.id, status="applied")
    await db.flush()

    # 2 cover_letter drafts
    db.add(Artifact(user_id=user_id, application_id=app.id, type="cover_letter", content="draft"))
    db.add(Artifact(user_id=user_id, application_id=app.id, type="cover_letter", content="draft2"))
    await db.commit()

    resp = await client.get("/api/dashboard", headers=auth_headers)
    assert resp.status_code == 200
    # 0 ghosts × 2.0 + 2 drafts × 1.5 = 3.0
    assert abs(resp.json()["time_saved_hours"] - 3.0) < 1e-6


# ---------------------------------------------------------------------------
# Platform IQ is GLOBAL — same for all users
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_platform_iq_is_global(client: AsyncClient, db: AsyncSession):
    token_a = await _signup_and_token(client, "user_a_dash@example.com")
    token_b = await _signup_and_token(client, "user_b_dash@example.com")

    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    resp_a = await client.get("/api/dashboard", headers=headers_a)
    resp_b = await client.get("/api/dashboard", headers=headers_b)

    assert resp_a.status_code == 200
    assert resp_b.status_code == 200
    assert resp_a.json()["platform_iq"] == resp_b.json()["platform_iq"]
    assert resp_a.json()["iq_trend"] == resp_b.json()["iq_trend"]


# ---------------------------------------------------------------------------
# User-scoped pipeline differs between users
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pipeline_is_user_scoped(client: AsyncClient, db: AsyncSession):
    token_a = await _signup_and_token(client, "user_a_scope@example.com")
    token_b = await _signup_and_token(client, "user_b_scope@example.com")

    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    user_a_id = _user_id_from_token(token_a)

    c = _company(db)
    await db.flush()
    p = _posting(db, c.id)
    await db.flush()

    # Only user A has an application
    _application(db, user_a_id, p.id, status="applied")
    await db.commit()

    resp_a = await client.get("/api/dashboard", headers=headers_a)
    resp_b = await client.get("/api/dashboard", headers=headers_b)

    assert resp_a.status_code == 200
    assert resp_b.status_code == 200
    # User A has 1 applied; user B has 0
    assert resp_a.json()["pipeline"]["applied"] == 1
    assert resp_b.json()["pipeline"]["applied"] == 0


# ---------------------------------------------------------------------------
# Digest
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_digest_followup_due(client: AsyncClient, auth_headers: dict, db: AsyncSession):
    token = auth_headers["Authorization"].split(" ")[1]
    user_id = _user_id_from_token(token)

    c = _company(db)
    await db.flush()
    p = _posting(db, c.id)
    await db.flush()

    old_applied_at = datetime.now(UTC) - timedelta(days=10)
    _application(db, user_id, p.id, status="applied", applied_at=old_applied_at)
    await db.commit()

    resp = await client.get("/api/digest", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["followup_due"] == 1


@pytest.mark.asyncio
async def test_digest_recent_responses(client: AsyncClient, auth_headers: dict, db: AsyncSession):
    token = auth_headers["Authorization"].split(" ")[1]
    user_id = _user_id_from_token(token)

    c = _company(db)
    await db.flush()
    p = _posting(db, c.id)
    await db.flush()
    app = _application(db, user_id, p.id, status="responded")
    await db.flush()
    _outcome(db, app.id, "responded", responded=True)
    await db.commit()

    resp = await client.get("/api/digest", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["recent_responses"] >= 1
