"""Tests for Module 7 — Application Assistant."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.artifact import Artifact
from app.models.company import Company
from app.models.posting import Posting
from app.services.application_service import _compute_ats, _kw_found

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_company(db: AsyncSession) -> Company:
    c = Company(
        name=f"TestCo-{uuid.uuid4().hex[:6]}",
        normalized_name=f"testco{uuid.uuid4().hex[:6]}",
        domain=None,
        industry=None,
        size=None,
        ghost_history_score=0.0,
        responsiveness_score=1.0,
    )
    db.add(c)
    return c


def _make_posting(company_id: uuid.UUID, *, requirements: list[str] | None = None) -> Posting:
    posted = (datetime.now(UTC) - timedelta(days=5)).isoformat().replace("+00:00", "Z")
    p = Posting(
        company_id=company_id,
        title="Software Engineering Intern",
        description="Build cool things with Python, FastAPI and React.",
        requirements=requirements or ["Python", "FastAPI", "React"],
        work_mode="remote",
        source="greenhouse",
        source_url=f"https://boards.greenhouse.io/{uuid.uuid4().hex}",
        dedup_key=uuid.uuid4().hex[:16],
        posted_at=posted,
        last_seen_at=posted,
    )
    return p


async def _seed_posting(
    db: AsyncSession, *, requirements: list[str] | None = None
) -> tuple[Company, Posting]:
    company = _make_company(db)
    await db.flush()
    posting = _make_posting(company.id, requirements=requirements)
    db.add(posting)
    await db.commit()
    await db.refresh(company)
    await db.refresh(posting)
    return company, posting


async def _create_artifact(
    db: AsyncSession, user_id: uuid.UUID, application_id: uuid.UUID | None = None
) -> Artifact:
    a = Artifact(
        user_id=user_id,
        application_id=application_id,
        type="cover_letter",
        content="I am excited to apply for this role.",
        ats_score=50,
        missing_keywords=[],
        grounding_score=1.0,
        version=1,
    )
    db.add(a)
    await db.commit()
    await db.refresh(a)
    return a


async def _get_user_id(client: AsyncClient, auth_headers: dict[str, str]) -> uuid.UUID:
    resp = await client.get("/api/auth/me", headers=auth_headers)
    assert resp.status_code == 200
    return uuid.UUID(resp.json()["user"]["id"])


# ---------------------------------------------------------------------------
# Unit tests — ATS scoring (pure, no DB)
# ---------------------------------------------------------------------------


def test_kw_found_direct_match() -> None:
    assert _kw_found("Python", "strong python skills required")


def test_kw_found_react_js_normalized() -> None:
    """React.js requirement matches when content contains 'React'."""
    assert _kw_found("React.js", "experience with react and typescript")


def test_kw_found_acronym_pmp() -> None:
    """Multi-word requirement matches via acronym in content."""
    assert _kw_found("Project Management Professional", "certified pmp with 3 years experience")


def test_kw_not_found() -> None:
    assert not _kw_found("Kubernetes", "experience with Docker and AWS")


def test_compute_ats_full_match() -> None:
    score, missing = _compute_ats(["Python", "FastAPI", "Docker"], "Python, FastAPI, Docker")
    assert score == 100
    assert missing == []


def test_compute_ats_no_match() -> None:
    score, missing = _compute_ats(["Python", "FastAPI"], "Java Spring Boot")
    assert score == 0
    assert set(missing) == {"Python", "FastAPI"}


def test_compute_ats_partial_match() -> None:
    score, missing = _compute_ats(["Python", "FastAPI", "Docker"], "Python and FastAPI")
    assert score == pytest.approx(67, abs=1)
    assert missing == ["Docker"]


def test_compute_ats_no_keywords() -> None:
    score, missing = _compute_ats([], "some content")
    assert score == 100
    assert missing == []


# ---------------------------------------------------------------------------
# 1. POST /api/applications/decode — LLM mocked
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_decode_returns_structure(
    client: AsyncClient,
    db: AsyncSession,
    auth_headers: dict[str, str],
) -> None:
    _, posting = await _seed_posting(db)

    with patch("app.services.application_service.ApplicationService.decode") as mock_decode:
        mock_decode.return_value = {
            "requirements": ["Python"],
            "keywords": ["FastAPI", "async"],
            "summary": "Backend role.",
        }
        resp = await client.post(
            "/api/applications/decode",
            json={"posting_id": str(posting.id)},
            headers=auth_headers,
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "requirements" in data
    assert "keywords" in data
    assert "summary" in data
    assert isinstance(data["requirements"], list)
    assert isinstance(data["keywords"], list)
    assert isinstance(data["summary"], str)


# ---------------------------------------------------------------------------
# 2. POST /api/applications/ats-score — deterministic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ats_score_full_match(
    client: AsyncClient,
    db: AsyncSession,
    auth_headers: dict[str, str],
) -> None:
    _, posting = await _seed_posting(db, requirements=["Python", "FastAPI", "React"])
    resp = await client.post(
        "/api/applications/ats-score",
        json={"posting_id": str(posting.id), "content": "Python FastAPI React experience"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ats_score"] == 100
    assert data["missing_keywords"] == []


@pytest.mark.asyncio
async def test_ats_score_no_match(
    client: AsyncClient,
    db: AsyncSession,
    auth_headers: dict[str, str],
) -> None:
    _, posting = await _seed_posting(db, requirements=["Python", "FastAPI"])
    resp = await client.post(
        "/api/applications/ats-score",
        json={"posting_id": str(posting.id), "content": "Java Spring Boot developer"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ats_score"] == 0
    assert set(data["missing_keywords"]) == {"Python", "FastAPI"}


@pytest.mark.asyncio
async def test_ats_score_reactjs_equivalence(
    client: AsyncClient,
    db: AsyncSession,
    auth_headers: dict[str, str],
) -> None:
    _, posting = await _seed_posting(db, requirements=["React.js"])
    resp = await client.post(
        "/api/applications/ats-score",
        json={"posting_id": str(posting.id), "content": "Built UIs in React and TypeScript"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["ats_score"] == 100
    assert resp.json()["missing_keywords"] == []


@pytest.mark.asyncio
async def test_ats_score_acronym_equivalence(
    client: AsyncClient,
    db: AsyncSession,
    auth_headers: dict[str, str],
) -> None:
    _, posting = await _seed_posting(
        db, requirements=["Project Management Professional"]
    )
    resp = await client.post(
        "/api/applications/ats-score",
        json={"posting_id": str(posting.id), "content": "Certified PMP holder with 5 years"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["ats_score"] == 100


# ---------------------------------------------------------------------------
# 3. POST /api/applications/draft — LLM mocked
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_draft_creates_artifact(
    client: AsyncClient,
    db: AsyncSession,
    auth_headers: dict[str, str],
) -> None:
    _, posting = await _seed_posting(db, requirements=["Python", "FastAPI"])
    draft_content = "Dear Hiring Manager, I have strong Python and FastAPI experience."

    with patch("app.llm.router.complete", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = draft_content
        resp = await client.post(
            "/api/applications/draft",
            json={
                "posting_id": str(posting.id),
                "type": "cover_letter",
                "channel": "portal",
            },
            headers=auth_headers,
        )

    assert resp.status_code == 200, resp.text
    artifact = resp.json()["artifact"]
    assert artifact["type"] == "cover_letter"
    assert artifact["content"] == draft_content
    assert artifact["version"] == 1
    assert artifact["ats_score"] is not None
    assert isinstance(artifact["missing_keywords"], list)
    assert artifact["grounding_score"] is not None
    assert artifact["application_id"] is None
    assert "generated_at" in artifact


@pytest.mark.asyncio
async def test_draft_guard_loop_retries_on_fabrication(
    client: AsyncClient,
    db: AsyncSession,
    auth_headers: dict[str, str],
) -> None:
    """Guard loop fires when first draft claims skills the profile doesn't have."""
    # Seed a profile with ONLY Python + FastAPI
    await client.get("/api/profile", headers=auth_headers)  # auto-create
    await client.put(
        "/api/profile",
        json={"skills": ["Python", "FastAPI"]},
        headers=auth_headers,
    )

    # Posting requires Python, FastAPI, AND Kubernetes (candidate lacks Kubernetes)
    _, posting = await _seed_posting(
        db, requirements=["Python", "FastAPI", "Kubernetes"]
    )

    # First call: fabricated Kubernetes → gs = 2/3 = 0.67 < 0.7 → retry triggers
    bad_draft = "Expert in Python, FastAPI, and Kubernetes infrastructure."
    # Second call (correction): clean draft without Kubernetes → gs = 2/2 = 1.0
    good_draft = "Strong Python and FastAPI developer with backend experience."

    with patch("app.llm.router.complete", new_callable=AsyncMock) as mock_llm:
        mock_llm.side_effect = [bad_draft, good_draft]
        resp = await client.post(
            "/api/applications/draft",
            json={"posting_id": str(posting.id), "type": "cover_letter", "channel": "portal"},
            headers=auth_headers,
        )

    assert resp.status_code == 200, resp.text
    assert mock_llm.call_count == 2  # retry was triggered
    artifact = resp.json()["artifact"]
    assert artifact["content"] == good_draft
    assert artifact["grounding_score"] >= 0.7
    # Kubernetes should not be in the corrected draft → not missing from ATS perspective only
    # but must not be falsely claimed
    assert "Kubernetes" not in artifact["content"]


@pytest.mark.asyncio
async def test_draft_no_retry_when_no_profile_evidence(
    client: AsyncClient,
    db: AsyncSession,
    auth_headers: dict[str, str],
) -> None:
    """Guard loop must NOT fire when profile has no verified skills — nothing to verify against."""
    # Fresh user, no profile update → skills = [], project_techs = []
    _, posting = await _seed_posting(db, requirements=["Python", "Kubernetes"])
    any_draft = "I have experience with Python and Kubernetes."

    with patch("app.llm.router.complete", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = any_draft
        resp = await client.post(
            "/api/applications/draft",
            json={"posting_id": str(posting.id), "type": "email", "channel": "email"},
            headers=auth_headers,
        )

    assert resp.status_code == 200, resp.text
    assert mock_llm.call_count == 1  # no retry — no profile evidence to verify against


@pytest.mark.asyncio
async def test_draft_invalid_type_400(
    client: AsyncClient,
    db: AsyncSession,
    auth_headers: dict[str, str],
) -> None:
    _, posting = await _seed_posting(db)
    resp = await client.post(
        "/api/applications/draft",
        json={"posting_id": str(posting.id), "type": "unknown_type", "channel": "portal"},
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_ARTIFACT_TYPE"


# ---------------------------------------------------------------------------
# 4. POST /api/applications — create, snapshots predictions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_application_snapshots_predictions(
    client: AsyncClient,
    db: AsyncSession,
    auth_headers: dict[str, str],
) -> None:
    user_id = await _get_user_id(client, auth_headers)
    _, posting = await _seed_posting(db)
    artifact = await _create_artifact(db, user_id)

    resp = await client.post(
        "/api/applications",
        json={
            "posting_id": str(posting.id),
            "channel": "portal",
            "artifact_id": str(artifact.id),
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    app_data = resp.json()["application"]

    assert app_data["posting_id"] == str(posting.id)
    assert app_data["channel"] == "portal"
    assert app_data["status"] == "saved"
    assert 0 <= app_data["predicted_response_prob"] <= 1
    assert isinstance(app_data["predicted_ghost"], bool)
    assert app_data["outcome"] is None
    assert app_data["applied_at"] is None
    # posting summary shape
    assert app_data["posting"]["title"] == posting.title
    # artifact linked
    assert len(app_data["artifacts"]) == 1
    assert app_data["artifacts"][0]["id"] == str(artifact.id)


@pytest.mark.asyncio
async def test_create_application_links_artifact(
    client: AsyncClient,
    db: AsyncSession,
    auth_headers: dict[str, str],
) -> None:
    user_id = await _get_user_id(client, auth_headers)
    _, posting = await _seed_posting(db)
    artifact = await _create_artifact(db, user_id)

    resp = await client.post(
        "/api/applications",
        json={
            "posting_id": str(posting.id),
            "channel": "email",
            "artifact_id": str(artifact.id),
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    app_id = resp.json()["application"]["id"]

    # Artifact should now be linked to this application
    await db.refresh(artifact)
    assert str(artifact.application_id) == app_id


# ---------------------------------------------------------------------------
# 5. POST /api/applications/{id}/send
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_without_gmail_consent_returns_403(
    client: AsyncClient,
    db: AsyncSession,
    auth_headers: dict[str, str],
) -> None:
    user_id = await _get_user_id(client, auth_headers)
    _, posting = await _seed_posting(db)
    artifact = await _create_artifact(db, user_id)

    # Create application
    resp = await client.post(
        "/api/applications",
        json={
            "posting_id": str(posting.id),
            "channel": "portal",
            "artifact_id": str(artifact.id),
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    app_id = resp.json()["application"]["id"]

    # Send without gmail consent (default is False)
    resp = await client.post(
        f"/api/applications/{app_id}/send",
        json={"via": "gmail"},
        headers=auth_headers,
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "GMAIL_CONSENT_REQUIRED"


@pytest.mark.asyncio
async def test_send_with_gmail_consent_sets_applied(
    client: AsyncClient,
    db: AsyncSession,
    auth_headers: dict[str, str],
) -> None:
    user_id = await _get_user_id(client, auth_headers)
    _, posting = await _seed_posting(db)
    artifact = await _create_artifact(db, user_id)

    # Grant gmail consent
    consent_resp = await client.put(
        "/api/auth/consent", json={"gmail": True}, headers=auth_headers
    )
    assert consent_resp.status_code == 200

    # Create application
    resp = await client.post(
        "/api/applications",
        json={
            "posting_id": str(posting.id),
            "channel": "email",
            "artifact_id": str(artifact.id),
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    app_id = resp.json()["application"]["id"]

    # Send
    resp = await client.post(
        f"/api/applications/{app_id}/send",
        json={"via": "gmail"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    app_data = resp.json()["application"]
    assert app_data["status"] == "applied"
    assert app_data["applied_at"] is not None


# ---------------------------------------------------------------------------
# 6. GET /api/applications — list with pagination and status filter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_applications_pagination(
    client: AsyncClient,
    db: AsyncSession,
    auth_headers: dict[str, str],
) -> None:
    user_id = await _get_user_id(client, auth_headers)
    _, posting = await _seed_posting(db)

    for _ in range(3):
        artifact = await _create_artifact(db, user_id)
        await client.post(
            "/api/applications",
            json={
                "posting_id": str(posting.id),
                "channel": "portal",
                "artifact_id": str(artifact.id),
            },
            headers=auth_headers,
        )

    resp = await client.get("/api/applications?page=1&limit=2", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["page"] == 1
    assert data["limit"] == 2
    assert data["total"] >= 3
    assert len(data["data"]) == 2


@pytest.mark.asyncio
async def test_list_applications_status_filter(
    client: AsyncClient,
    db: AsyncSession,
    auth_headers: dict[str, str],
) -> None:
    user_id = await _get_user_id(client, auth_headers)
    _, posting = await _seed_posting(db)

    # Grant consent and create an applied application
    await client.put("/api/auth/consent", json={"gmail": True}, headers=auth_headers)
    artifact = await _create_artifact(db, user_id)
    resp = await client.post(
        "/api/applications",
        json={
            "posting_id": str(posting.id),
            "channel": "email",
            "artifact_id": str(artifact.id),
        },
        headers=auth_headers,
    )
    app_id = resp.json()["application"]["id"]
    await client.post(
        f"/api/applications/{app_id}/send",
        json={"via": "gmail"},
        headers=auth_headers,
    )

    # Also create a saved application
    artifact2 = await _create_artifact(db, user_id)
    await client.post(
        "/api/applications",
        json={
            "posting_id": str(posting.id),
            "channel": "portal",
            "artifact_id": str(artifact2.id),
        },
        headers=auth_headers,
    )

    # Filter by status=applied should return only 1
    resp_filtered = await client.get(
        "/api/applications?status=applied", headers=auth_headers
    )
    assert resp_filtered.status_code == 200
    assert all(a["status"] == "applied" for a in resp_filtered.json()["data"])


# ---------------------------------------------------------------------------
# 7. GET /api/applications/{id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_application_shape(
    client: AsyncClient,
    db: AsyncSession,
    auth_headers: dict[str, str],
) -> None:
    user_id = await _get_user_id(client, auth_headers)
    _, posting = await _seed_posting(db)
    artifact = await _create_artifact(db, user_id)

    create_resp = await client.post(
        "/api/applications",
        json={
            "posting_id": str(posting.id),
            "channel": "portal",
            "artifact_id": str(artifact.id),
        },
        headers=auth_headers,
    )
    app_id = create_resp.json()["application"]["id"]

    resp = await client.get(f"/api/applications/{app_id}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    app_data = resp.json()["application"]

    assert app_data["id"] == app_id
    assert "posting" in app_data
    assert "title" in app_data["posting"]
    assert "company_name" in app_data["posting"]
    assert isinstance(app_data["artifacts"], list)
    assert len(app_data["artifacts"]) == 1
    assert "predicted_response_prob" in app_data
    assert "predicted_ghost" in app_data
    assert "created_at" in app_data


@pytest.mark.asyncio
async def test_get_application_404(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    resp = await client.get(
        f"/api/applications/{uuid.uuid4()}", headers=auth_headers
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "APPLICATION_NOT_FOUND"


# ---------------------------------------------------------------------------
# 8. PUT /api/applications/{id} — update status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_application_status(
    client: AsyncClient,
    db: AsyncSession,
    auth_headers: dict[str, str],
) -> None:
    user_id = await _get_user_id(client, auth_headers)
    _, posting = await _seed_posting(db)
    artifact = await _create_artifact(db, user_id)

    create_resp = await client.post(
        "/api/applications",
        json={
            "posting_id": str(posting.id),
            "channel": "portal",
            "artifact_id": str(artifact.id),
        },
        headers=auth_headers,
    )
    app_id = create_resp.json()["application"]["id"]

    resp = await client.put(
        f"/api/applications/{app_id}",
        json={"status": "interview"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["application"]["status"] == "interview"


@pytest.mark.asyncio
async def test_update_application_invalid_status_400(
    client: AsyncClient,
    db: AsyncSession,
    auth_headers: dict[str, str],
) -> None:
    user_id = await _get_user_id(client, auth_headers)
    _, posting = await _seed_posting(db)
    artifact = await _create_artifact(db, user_id)

    create_resp = await client.post(
        "/api/applications",
        json={
            "posting_id": str(posting.id),
            "channel": "portal",
            "artifact_id": str(artifact.id),
        },
        headers=auth_headers,
    )
    app_id = create_resp.json()["application"]["id"]

    resp = await client.put(
        f"/api/applications/{app_id}",
        json={"status": "winning"},
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_STATUS"


# ---------------------------------------------------------------------------
# 9. PUT /api/artifacts/{id} — edit content, bump version
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_artifact_bumps_version(
    client: AsyncClient,
    db: AsyncSession,
    auth_headers: dict[str, str],
) -> None:
    user_id = await _get_user_id(client, auth_headers)
    artifact = await _create_artifact(db, user_id)
    assert artifact.version == 1

    resp = await client.put(
        f"/api/artifacts/{artifact.id}",
        json={"content": "Updated cover letter with Python and FastAPI."},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    updated = resp.json()["artifact"]
    assert updated["version"] == 2
    assert updated["content"] == "Updated cover letter with Python and FastAPI."


@pytest.mark.asyncio
async def test_update_artifact_404_other_user(
    client: AsyncClient,
    db: AsyncSession,
    auth_headers: dict[str, str],
) -> None:
    # Create a real second user so the FK on artifacts.user_id is satisfied
    signup_resp = await client.post(
        "/api/auth/signup",
        json={"name": "Other User", "email": "other_artifact@example.com", "password": "secret123"},
    )
    assert signup_resp.status_code == 201
    other_user_id = uuid.UUID(signup_resp.json()["user"]["id"])

    artifact = await _create_artifact(db, other_user_id)

    resp = await client.put(
        f"/api/artifacts/{artifact.id}",
        json={"content": "Trying to overwrite someone else's artifact"},
        headers=auth_headers,
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "ARTIFACT_NOT_FOUND"


# ---------------------------------------------------------------------------
# 10. Data isolation — user B cannot read user A's application
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_data_isolation_cross_user(
    client: AsyncClient,
    db: AsyncSession,
    auth_headers: dict[str, str],
) -> None:
    # User A (auth_headers) creates an application
    user_a_id = await _get_user_id(client, auth_headers)
    _, posting = await _seed_posting(db)
    artifact = await _create_artifact(db, user_a_id)

    create_resp = await client.post(
        "/api/applications",
        json={
            "posting_id": str(posting.id),
            "channel": "portal",
            "artifact_id": str(artifact.id),
        },
        headers=auth_headers,
    )
    assert create_resp.status_code == 201
    app_id = create_resp.json()["application"]["id"]

    # User B signs up and tries to access User A's application
    signup_resp = await client.post(
        "/api/auth/signup",
        json={"name": "User B", "email": "userb@example.com", "password": "secret123"},
    )
    assert signup_resp.status_code == 201
    token_b = signup_resp.json()["token"]
    headers_b = {"Authorization": f"Bearer {token_b}"}

    resp = await client.get(f"/api/applications/{app_id}", headers=headers_b)
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "APPLICATION_NOT_FOUND"
