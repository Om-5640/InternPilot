"""Tests for Module 8 — Tracker, Follow-up & Outcomes."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.application import Application
from app.models.company import Company
from app.models.outcome import Outcome
from app.models.posting import Posting
from app.models.user import User

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_company(db: AsyncSession, name: str | None = None) -> Company:
    n = name or f"Co-{uuid.uuid4().hex[:8]}"
    company = Company(
        name=n,
        normalized_name=n.lower().replace(" ", ""),
        domain=f"{n.lower().replace(' ', '')}.com",
        ghost_history_score=0.0,
        responsiveness_score=1.0,
    )
    db.add(company)
    await db.flush()
    return company


async def _make_posting(db: AsyncSession, company_id: uuid.UUID) -> Posting:
    posting = Posting(
        company_id=company_id,
        title="Software Intern",
        description="Build great things.",
        requirements=["Python", "FastAPI"],
        work_mode="remote",
        source="greenhouse",
        source_url=f"https://example.com/{uuid.uuid4().hex}",
        dedup_key=uuid.uuid4().hex[:16],
        posted_at="2026-01-01T00:00:00Z",
        last_seen_at="2026-01-01T00:00:00Z",
    )
    db.add(posting)
    await db.flush()
    return posting


async def _make_application(
    db: AsyncSession,
    user_id: uuid.UUID,
    posting_id: uuid.UUID,
    status: str = "saved",
) -> Application:
    app = Application(
        user_id=user_id,
        posting_id=posting_id,
        channel="portal",
        status=status,
    )
    db.add(app)
    await db.flush()
    return app


async def _get_user_id(client: AsyncClient, email: str = "test@example.com") -> uuid.UUID:
    resp = await client.post(
        "/api/auth/signup",
        json={"name": "Test User", "email": email, "password": "secret123"},
    )
    assert resp.status_code == 201
    return uuid.UUID(resp.json()["user"]["id"])


async def _auth_headers(client: AsyncClient, email: str = "test@example.com") -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login",
        json={"email": email, "password": "secret123"},
    )
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['token']}"}


# ---------------------------------------------------------------------------
# 1. list_applications — empty
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_applications_empty(client: AsyncClient, auth_headers: dict) -> None:
    resp = await client.get("/api/applications", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"] == []
    assert body["total"] == 0


# ---------------------------------------------------------------------------
# 2. list_applications — only returns own
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_applications_isolation(
    client: AsyncClient, auth_headers: dict, db: AsyncSession
) -> None:
    # main user: sign up already done by auth_headers fixture
    user_result = await db.execute(select(User).where(User.email == "test@example.com"))
    user = user_result.scalar_one()

    company = await _make_company(db)
    posting = await _make_posting(db, company.id)
    await _make_application(db, user.id, posting.id)

    # second user
    other_resp = await client.post(
        "/api/auth/signup",
        json={"name": "Other", "email": "other@example.com", "password": "pass1234"},
    )
    assert other_resp.status_code == 201
    other_id = uuid.UUID(other_resp.json()["user"]["id"])
    await _make_application(db, other_id, posting.id)
    await db.commit()

    resp = await client.get("/api/applications", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


# ---------------------------------------------------------------------------
# 3. list_applications — status filter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_applications_status_filter(
    client: AsyncClient, auth_headers: dict, db: AsyncSession
) -> None:
    user_result = await db.execute(select(User).where(User.email == "test@example.com"))
    user = user_result.scalar_one()

    company = await _make_company(db)
    posting = await _make_posting(db, company.id)
    await _make_application(db, user.id, posting.id, status="applied")
    await _make_application(db, user.id, posting.id, status="saved")
    await db.commit()

    resp = await client.get("/api/applications?status=applied", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["data"][0]["status"] == "applied"


# ---------------------------------------------------------------------------
# 4. list_applications — pagination
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_applications_pagination(
    client: AsyncClient, auth_headers: dict, db: AsyncSession
) -> None:
    user_result = await db.execute(select(User).where(User.email == "test@example.com"))
    user = user_result.scalar_one()

    company = await _make_company(db)
    posting = await _make_posting(db, company.id)
    for _ in range(5):
        await _make_application(db, user.id, posting.id)
    await db.commit()

    resp = await client.get("/api/applications?page=2&limit=2", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 5
    assert body["page"] == 2
    assert len(body["data"]) == 2


# ---------------------------------------------------------------------------
# 5. get_application — returns detail with outcome=null initially
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_application_no_outcome(
    client: AsyncClient, auth_headers: dict, db: AsyncSession
) -> None:
    user_result = await db.execute(select(User).where(User.email == "test@example.com"))
    user = user_result.scalar_one()

    company = await _make_company(db)
    posting = await _make_posting(db, company.id)
    app = await _make_application(db, user.id, posting.id)
    await db.commit()

    resp = await client.get(f"/api/applications/{app.id}", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()["application"]
    assert body["id"] == str(app.id)
    assert body["outcome"] is None


# ---------------------------------------------------------------------------
# 6. get_application — 404 for nonexistent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_application_not_found(
    client: AsyncClient, auth_headers: dict
) -> None:
    resp = await client.get(f"/api/applications/{uuid.uuid4()}", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "APPLICATION_NOT_FOUND"


# ---------------------------------------------------------------------------
# 7. get_application — isolation (can't see other user's)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_application_isolation(
    client: AsyncClient, auth_headers: dict, db: AsyncSession
) -> None:
    other_resp = await client.post(
        "/api/auth/signup",
        json={"name": "Other", "email": "other2@example.com", "password": "pass1234"},
    )
    assert other_resp.status_code == 201
    other_id = uuid.UUID(other_resp.json()["user"]["id"])

    company = await _make_company(db)
    posting = await _make_posting(db, company.id)
    other_app = await _make_application(db, other_id, posting.id)
    await db.commit()

    resp = await client.get(f"/api/applications/{other_app.id}", headers=auth_headers)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 8. update_application — status change
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_application_status(
    client: AsyncClient, auth_headers: dict, db: AsyncSession
) -> None:
    user_result = await db.execute(select(User).where(User.email == "test@example.com"))
    user = user_result.scalar_one()

    company = await _make_company(db)
    posting = await _make_posting(db, company.id)
    app = await _make_application(db, user.id, posting.id, status="saved")
    await db.commit()

    resp = await client.put(
        f"/api/applications/{app.id}",
        json={"status": "applied"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["application"]["status"] == "applied"


# ---------------------------------------------------------------------------
# 9. update_application — invalid status → 400
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_application_invalid_status(
    client: AsyncClient, auth_headers: dict, db: AsyncSession
) -> None:
    user_result = await db.execute(select(User).where(User.email == "test@example.com"))
    user = user_result.scalar_one()

    company = await _make_company(db)
    posting = await _make_posting(db, company.id)
    app = await _make_application(db, user.id, posting.id)
    await db.commit()

    resp = await client.put(
        f"/api/applications/{app.id}",
        json={"status": "flying_to_mars"},
        headers=auth_headers,
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# 10. update_application — notes field
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_application_notes(
    client: AsyncClient, auth_headers: dict, db: AsyncSession
) -> None:
    user_result = await db.execute(select(User).where(User.email == "test@example.com"))
    user = user_result.scalar_one()

    company = await _make_company(db)
    posting = await _make_posting(db, company.id)
    app = await _make_application(db, user.id, posting.id)
    await db.commit()

    resp = await client.put(
        f"/api/applications/{app.id}",
        json={"notes": "HR contact: Jane"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["application"]["status"] == "saved"


# ---------------------------------------------------------------------------
# 11. record_outcome — creates outcome, status auto-updated to "responded"
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_outcome_creates_outcome(
    client: AsyncClient, auth_headers: dict, db: AsyncSession
) -> None:
    user_result = await db.execute(select(User).where(User.email == "test@example.com"))
    user = user_result.scalar_one()

    company = await _make_company(db)
    posting = await _make_posting(db, company.id)
    app = await _make_application(db, user.id, posting.id, status="applied")
    await db.commit()

    resp = await client.post(
        f"/api/applications/{app.id}/outcome",
        json={
            "outcome_type": "responded",
            "responded": True,
            "time_to_response_hours": 48.0,
            "source": "manual",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    body = resp.json()["outcome"]
    assert body["outcome_type"] == "responded"
    assert body["responded"] is True
    assert body["time_to_response_hours"] == 48.0
    assert body["source"] == "manual"


# ---------------------------------------------------------------------------
# 12. record_outcome — responded=True auto-sets status to "responded"
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_outcome_updates_status(
    client: AsyncClient, auth_headers: dict, db: AsyncSession
) -> None:
    user_result = await db.execute(select(User).where(User.email == "test@example.com"))
    user = user_result.scalar_one()

    company = await _make_company(db)
    posting = await _make_posting(db, company.id)
    app = await _make_application(db, user.id, posting.id, status="applied")
    await db.commit()

    await client.post(
        f"/api/applications/{app.id}/outcome",
        json={"outcome_type": "responded", "responded": True},
        headers=auth_headers,
    )

    get_resp = await client.get(f"/api/applications/{app.id}", headers=auth_headers)
    assert get_resp.json()["application"]["status"] == "responded"


# ---------------------------------------------------------------------------
# 13. record_outcome — isolation (can't record on other user's app)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_outcome_isolation(
    client: AsyncClient, auth_headers: dict, db: AsyncSession
) -> None:
    other_resp = await client.post(
        "/api/auth/signup",
        json={"name": "Other", "email": "other3@example.com", "password": "pass1234"},
    )
    assert other_resp.status_code == 201
    other_id = uuid.UUID(other_resp.json()["user"]["id"])

    company = await _make_company(db)
    posting = await _make_posting(db, company.id)
    other_app = await _make_application(db, other_id, posting.id)
    await db.commit()

    resp = await client.post(
        f"/api/applications/{other_app.id}/outcome",
        json={"outcome_type": "responded", "responded": True},
        headers=auth_headers,
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 14. record_outcome — invalid outcome_type → 400
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_outcome_invalid_type(
    client: AsyncClient, auth_headers: dict, db: AsyncSession
) -> None:
    user_result = await db.execute(select(User).where(User.email == "test@example.com"))
    user = user_result.scalar_one()

    company = await _make_company(db)
    posting = await _make_posting(db, company.id)
    app = await _make_application(db, user.id, posting.id)
    await db.commit()

    resp = await client.post(
        f"/api/applications/{app.id}/outcome",
        json={"outcome_type": "BLOOP", "responded": False},
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_OUTCOME_TYPE"


# ---------------------------------------------------------------------------
# 15. get_application — outcome appears after recording
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_application_shows_outcome(
    client: AsyncClient, auth_headers: dict, db: AsyncSession
) -> None:
    user_result = await db.execute(select(User).where(User.email == "test@example.com"))
    user = user_result.scalar_one()

    company = await _make_company(db)
    posting = await _make_posting(db, company.id)
    app = await _make_application(db, user.id, posting.id, status="applied")
    await db.commit()

    await client.post(
        f"/api/applications/{app.id}/outcome",
        json={"outcome_type": "no_response", "responded": False},
        headers=auth_headers,
    )

    get_resp = await client.get(f"/api/applications/{app.id}", headers=auth_headers)
    assert get_resp.status_code == 200
    outcome = get_resp.json()["application"]["outcome"]
    assert outcome is not None
    assert outcome["outcome_type"] == "no_response"
    assert outcome["responded"] is False


# ---------------------------------------------------------------------------
# 16. cohort recomputed after outcome — company.cohort_applied_count updates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cohort_applied_count_updates(
    client: AsyncClient, auth_headers: dict, db: AsyncSession
) -> None:
    user_result = await db.execute(select(User).where(User.email == "test@example.com"))
    user = user_result.scalar_one()

    company = await _make_company(db)
    posting = await _make_posting(db, company.id)
    app = await _make_application(db, user.id, posting.id, status="applied")
    await db.commit()

    resp = await client.post(
        f"/api/applications/{app.id}/outcome",
        json={"outcome_type": "responded", "responded": True},
        headers=auth_headers,
    )
    assert resp.status_code == 201

    await db.refresh(company)
    assert company.cohort_applied_count == 1


# ---------------------------------------------------------------------------
# 17. cohort responsiveness set once MIN_APPS reached
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cohort_responsiveness_score_after_min_apps(
    client: AsyncClient, auth_headers: dict, db: AsyncSession
) -> None:
    """After 5 applications with known outcomes, responsiveness_score is data-driven."""
    # Create 5 different users and record outcomes
    company = await _make_company(db, name="BigCorp")
    posting = await _make_posting(db, company.id)
    await db.commit()

    emails = [
        "u1@example.com", "u2@example.com", "u3@example.com",
        "u4@example.com", "u5@example.com",
    ]
    for i, email in enumerate(emails):
        sign_resp = await client.post(
            "/api/auth/signup",
            json={"name": f"User {i}", "email": email, "password": "pass1234"},
        )
        assert sign_resp.status_code == 201
        uid = uuid.UUID(sign_resp.json()["user"]["id"])
        headers = {"Authorization": f"Bearer {sign_resp.json()['token']}"}
        app_obj = await _make_application(db, uid, posting.id, status="applied")
        await db.commit()
        responded = i < 3  # 3 of 5 respond
        await client.post(
            f"/api/applications/{app_obj.id}/outcome",
            json={"outcome_type": "responded" if responded else "no_response", "responded": responded},
            headers=headers,
        )

    await db.refresh(company)
    assert company.cohort_applied_count == 5
    # 3/5 responded → responsiveness_score = 0.6
    assert abs(company.responsiveness_score - 0.6) < 1e-6


# ---------------------------------------------------------------------------
# 18. draft_followup — returns a string (LLM mocked)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_draft_followup_returns_text(
    client: AsyncClient, auth_headers: dict, db: AsyncSession
) -> None:
    user_result = await db.execute(select(User).where(User.email == "test@example.com"))
    user = user_result.scalar_one()

    company = await _make_company(db)
    posting = await _make_posting(db, company.id)
    app = await _make_application(db, user.id, posting.id, status="applied")
    await db.commit()

    with patch(
        "app.llm.router.complete",
        new_callable=AsyncMock,
        return_value="Dear Hiring Manager, I wanted to follow up on my application...",
    ):
        resp = await client.post(
            f"/api/applications/{app.id}/followup",
            headers=auth_headers,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert "draft" in body
    assert len(body["draft"]) > 0


# ---------------------------------------------------------------------------
# 19. draft_followup — 404 for nonexistent application
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_draft_followup_not_found(
    client: AsyncClient, auth_headers: dict
) -> None:
    resp = await client.post(
        f"/api/applications/{uuid.uuid4()}/followup",
        headers=auth_headers,
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "APPLICATION_NOT_FOUND"


# ---------------------------------------------------------------------------
# 20. gmail/sync — no consent → detected=0
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gmail_sync_no_consent(
    client: AsyncClient, auth_headers: dict
) -> None:
    resp = await client.post("/api/integrations/gmail/sync", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["detected"] == 0


# ---------------------------------------------------------------------------
# 21. gmail/sync — consent set but no token → detected=0
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gmail_sync_no_token(
    client: AsyncClient, auth_headers: dict, db: AsyncSession
) -> None:
    user_result = await db.execute(select(User).where(User.email == "test@example.com"))
    user = user_result.scalar_one()
    user.consent = {"gmail": True, "github": False, "alumni_data": False}
    user.gmail_token = None
    await db.commit()

    resp = await client.post("/api/integrations/gmail/sync", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["detected"] == 0


# ---------------------------------------------------------------------------
# 22. gmail/sync — with mocked Gmail API → detects reply
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gmail_sync_detects_reply(
    client: AsyncClient, auth_headers: dict, db: AsyncSession
) -> None:
    user_result = await db.execute(select(User).where(User.email == "test@example.com"))
    user = user_result.scalar_one()
    user.consent = {"gmail": True, "github": False, "alumni_data": False}
    user.gmail_token = {"access_token": "fake-token-xyz"}

    company = await _make_company(db, name="Acme Corp")
    company.domain = "acmecorp.com"
    posting = await _make_posting(db, company.id)
    app = await _make_application(db, user.id, posting.id, status="applied")
    await db.commit()

    # Mock the Gmail HTTP responses
    search_response = MagicMock()
    search_response.status_code = 200
    search_response.json.return_value = {"messages": [{"id": "msg-001", "threadId": "thread-001"}]}

    detail_response = MagicMock()
    detail_response.status_code = 200
    detail_response.json.return_value = {
        "payload": {
            "headers": [
                {"name": "From", "value": "recruiter@acmecorp.com"},
                {"name": "Subject", "value": "Re: Software Intern Application"},
            ]
        }
    }

    mock_client_instance = AsyncMock()
    mock_client_instance.get = AsyncMock(side_effect=[search_response, detail_response])
    mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
    mock_client_instance.__aexit__ = AsyncMock(return_value=False)

    with patch("app.api.v1.integrations.httpx.AsyncClient", return_value=mock_client_instance):
        resp = await client.post("/api/integrations/gmail/sync", headers=auth_headers)

    assert resp.status_code == 200
    assert resp.json()["detected"] == 1

    outcome_result = await db.execute(
        select(Outcome).where(
            Outcome.application_id == app.id,
            Outcome.source == "gmail",
        )
    )
    assert outcome_result.scalar_one_or_none() is not None
