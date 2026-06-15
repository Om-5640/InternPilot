"""Tests for Module 11 — Notifications."""
from __future__ import annotations

import base64
import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.application import Application
from app.models.company import Company
from app.models.outcome import Outcome
from app.models.posting import Posting
from app.services.notification_service import NotificationService

# ---------------------------------------------------------------------------
# Helpers (mirrors test_dashboard helpers)
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


def _posting(db: AsyncSession, company_id: uuid.UUID) -> Posting:
    p = Posting(
        company_id=company_id,
        title="Test Role",
        description="desc",
        requirements=[],
        work_mode="remote",
        source="manual",
        source_url=f"https://example.com/{uuid.uuid4().hex}",
        dedup_key=uuid.uuid4().hex[:16],
        posted_at=datetime.now(UTC).isoformat(),
        last_seen_at=datetime.now(UTC).isoformat(),
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
    recorded_at: datetime | None = None,
) -> Outcome:
    o = Outcome(
        application_id=application_id,
        outcome_type=outcome_type,
        responded=responded,
        source="manual",
    )
    if recorded_at is not None:
        o.recorded_at = recorded_at
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
# generate() creates followup_due notifications
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generate_followup_due(db: AsyncSession, auth_headers: dict, client: AsyncClient):
    token = auth_headers["Authorization"].split(" ")[1]
    user_id = _user_id_from_token(token)

    c = _company(db)
    await db.flush()
    p = _posting(db, c.id)
    await db.flush()

    old_date = datetime.now(UTC) - timedelta(days=10)
    _application(db, user_id, p.id, status="applied", applied_at=old_date)
    await db.commit()

    svc = NotificationService(db, user_id)
    await svc.generate()

    notes = await svc.list_notifications()
    assert any(n.type == "followup_due" for n in notes)


# ---------------------------------------------------------------------------
# generate() creates response notifications for recent positive outcomes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generate_response_notification(
    db: AsyncSession, auth_headers: dict, client: AsyncClient
):
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

    svc = NotificationService(db, user_id)
    await svc.generate()

    notes = await svc.list_notifications()
    assert any(n.type == "response" for n in notes)


# ---------------------------------------------------------------------------
# generate() is idempotent — calling twice doesn't duplicate
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generate_is_idempotent(
    db: AsyncSession, auth_headers: dict, client: AsyncClient
):
    token = auth_headers["Authorization"].split(" ")[1]
    user_id = _user_id_from_token(token)

    c = _company(db)
    await db.flush()
    p = _posting(db, c.id)
    await db.flush()

    old_date = datetime.now(UTC) - timedelta(days=10)
    _application(db, user_id, p.id, status="applied", applied_at=old_date)
    await db.commit()

    svc = NotificationService(db, user_id)
    await svc.generate()
    await svc.generate()

    notes = await svc.list_notifications()
    followup_notes = [n for n in notes if n.type == "followup_due"]
    assert len(followup_notes) == 1


# ---------------------------------------------------------------------------
# list_notifications is user-scoped
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_is_user_scoped(client: AsyncClient, db: AsyncSession):
    token_a = await _signup_and_token(client, "notif_a@example.com")
    token_b = await _signup_and_token(client, "notif_b@example.com")

    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    user_a_id = _user_id_from_token(token_a)

    c = _company(db)
    await db.flush()
    p = _posting(db, c.id)
    await db.flush()
    old_date = datetime.now(UTC) - timedelta(days=10)
    _application(db, user_a_id, p.id, status="applied", applied_at=old_date)
    await db.commit()

    # generate for user A only
    svc_a = NotificationService(db, user_a_id)
    await svc_a.generate()

    # user A should see notifications; user B should see none
    resp_a = await client.get("/api/notifications", headers=headers_a)
    resp_b = await client.get("/api/notifications", headers=headers_b)

    assert resp_a.status_code == 200
    assert resp_b.status_code == 200
    assert len(resp_a.json()) >= 1
    assert len(resp_b.json()) == 0


# ---------------------------------------------------------------------------
# mark_read works; user A cannot mark_read user B's notification (404)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mark_read(client: AsyncClient, auth_headers: dict, db: AsyncSession):
    token = auth_headers["Authorization"].split(" ")[1]
    user_id = _user_id_from_token(token)

    c = _company(db)
    await db.flush()
    p = _posting(db, c.id)
    await db.flush()
    old_date = datetime.now(UTC) - timedelta(days=10)
    _application(db, user_id, p.id, status="applied", applied_at=old_date)
    await db.commit()

    svc = NotificationService(db, user_id)
    await svc.generate()

    notes = await svc.list_notifications()
    assert notes
    target = notes[0]
    assert target.read is False

    resp = await client.put(
        f"/api/notifications/{target.id}/read", headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json()["read"] is True


@pytest.mark.asyncio
async def test_mark_read_cross_user_forbidden(client: AsyncClient, db: AsyncSession):
    token_a = await _signup_and_token(client, "read_a@example.com")
    token_b = await _signup_and_token(client, "read_b@example.com")

    headers_b = {"Authorization": f"Bearer {token_b}"}

    user_a_id = _user_id_from_token(token_a)

    c = _company(db)
    await db.flush()
    p = _posting(db, c.id)
    await db.flush()
    old_date = datetime.now(UTC) - timedelta(days=10)
    _application(db, user_a_id, p.id, status="applied", applied_at=old_date)
    await db.commit()

    svc_a = NotificationService(db, user_a_id)
    await svc_a.generate()

    notes_a = await svc_a.list_notifications()
    assert notes_a
    notif_id = notes_a[0].id

    # User B tries to mark user A's notification as read → 404
    resp = await client.put(
        f"/api/notifications/{notif_id}/read", headers=headers_b
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Digest — user-scoped values, followup_due count
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_digest_user_scoped(client: AsyncClient, db: AsyncSession):
    token_a = await _signup_and_token(client, "digest_a@example.com")
    token_b = await _signup_and_token(client, "digest_b@example.com")

    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    user_a_id = _user_id_from_token(token_a)

    c = _company(db)
    await db.flush()
    p = _posting(db, c.id)
    await db.flush()

    # Only user A has an old application
    old_date = datetime.now(UTC) - timedelta(days=10)
    _application(db, user_a_id, p.id, status="applied", applied_at=old_date)
    await db.commit()

    resp_a = await client.get("/api/digest", headers=headers_a)
    resp_b = await client.get("/api/digest", headers=headers_b)

    assert resp_a.status_code == 200
    assert resp_b.status_code == 200
    assert resp_a.json()["followup_due"] == 1
    assert resp_b.json()["followup_due"] == 0
