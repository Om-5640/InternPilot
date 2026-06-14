"""Module 2 — Postings / Aggregation acceptance tests.

Covers:
- Each source adapter parses mocked HTTP responses into RawPosting shape
- refresh() ingests new postings and returns {ingested, deduped}
- Deduplication: same source_url → deduped; cross-source same role → deduped
- Company resolution: same name from different postings → single company row
- One failing source does not abort the full refresh
- GET /api/postings shape; GET /api/postings/:id; 404 on missing
- Two users see the same global postings (no user isolation)
- POST /api/aggregation/refresh requires admin role
- POST /api/postings/import works for Greenhouse; 422 for unknown ATS
- embedding is never present in any API response
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.models.company import Company
from app.models.user import AuthProvider, User, UserRole
from app.sources.base import RawPosting

POSTINGS_URL = "/api/postings"
IMPORT_URL = "/api/postings/import"
REFRESH_URL = "/api/aggregation/refresh"
SIGNUP_URL = "/api/auth/signup"

POSTING_FIELDS = {
    "id", "company", "title", "description", "requirements",
    "location", "work_mode", "stipend", "source", "source_url",
    "posted_at", "last_seen_at", "status", "ghost_score", "is_ghost",
    "created_at", "updated_at",
}
COMPANY_FIELDS = {"id", "name", "domain", "industry", "size"}

# ---------------------------------------------------------------------------
# Sample raw postings
# ---------------------------------------------------------------------------

GH_RAW: RawPosting = {
    "title": "Software Engineering Intern",
    "company_name": "TestCorp",
    "description": "Requirements:\n- Python\n- FastAPI experience",
    "source": "greenhouse",
    "source_url": "https://boards.greenhouse.io/testcorp/jobs/1",
    "location": "Remote",
    "work_mode": "remote",
    "stipend": None,
    "posted_at": "2026-06-05T00:00:00Z",
    "requirements": ["Python", "FastAPI"],
}

LEVER_RAW: RawPosting = {
    "title": "Backend Engineering Intern",
    "company_name": "TestCorp",
    "description": "Requirements:\n- Node.js\n- TypeScript",
    "source": "lever",
    "source_url": "https://jobs.lever.co/testcorp/abc-123",
    "location": "San Francisco, CA",
    "work_mode": None,
    "stipend": 5000,
    "posted_at": "2026-06-06T00:00:00Z",
    "requirements": ["Node.js", "TypeScript"],
}

# Two different URLs but same company/title/location → cross-source dedup
CROSS_A: RawPosting = {
    "title": "Data Engineering Intern",
    "company_name": "DedupeCoRP",
    "description": "SQL and Python",
    "source": "greenhouse",
    "source_url": "https://boards.greenhouse.io/dedupe/jobs/100",
    "location": "Remote",
    "work_mode": "remote",
    "stipend": None,
    "posted_at": None,
    "requirements": [],
}
CROSS_B: RawPosting = {
    "title": "Data Engineering Intern",
    "company_name": "DedupeCoRP",
    "description": "SQL and Python",
    "source": "lever",
    "source_url": "https://jobs.lever.co/dedupe/xyz-456",
    "location": "Remote",
    "work_mode": "remote",
    "stipend": None,
    "posted_at": None,
    "requirements": [],
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def mock_embed(mocker: Any) -> None:
    mocker.patch(
        "app.services.aggregation_service.embed",
        new=AsyncMock(return_value=[[0.0] * 384]),
    )


@pytest_asyncio.fixture
async def admin_headers(db: AsyncSession) -> dict[str, str]:
    user = User(
        name="Admin",
        email="admin@postings.test",
        password_hash=hash_password("admin123"),
        role=UserRole.admin,
        auth_provider=AuthProvider.password,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    token = create_access_token({"sub": str(user.id)})
    return {"Authorization": f"Bearer {token}"}


def _assert_posting_shape(p: dict[str, Any]) -> None:
    assert set(p.keys()) == POSTING_FIELDS, f"Unexpected fields: {set(p.keys())}"
    assert "embedding" not in p
    assert set(p["company"].keys()) == COMPANY_FIELDS


def _mock_http(mocker: Any, module: str, response_json: Any, status_code: int = 200) -> Any:
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = response_json

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(return_value=mock_resp)

    mocker.patch(f"{module}.httpx.AsyncClient", return_value=mock_client)
    return mock_client


def _patch_all_sources_empty(mocker: Any) -> None:
    """Silence all adapters except the one under test."""
    for name in ("greenhouse", "lever", "ashby", "remoteok", "remotive"):
        mocker.patch(
            f"app.sources.{name}.{name.capitalize() if name not in ('remoteok', 'remotive') else name.title().replace('ok', 'OK') if name == 'remoteok' else 'Remotive'}Source.fetch",
            new=AsyncMock(return_value=[]),
        )


# ---------------------------------------------------------------------------
# Adapter unit tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_greenhouse_adapter(mocker: Any) -> None:
    mocker.patch("app.sources.greenhouse.GREENHOUSE_SLUGS", ["testcorp"])
    _mock_http(mocker, "app.sources.greenhouse", {
        "jobs": [{
            "id": 1,
            "title": "SWE Intern",
            "absolute_url": "https://boards.greenhouse.io/testcorp/jobs/1",
            "location": {"name": "Remote"},
            "content": "<p>Requirements: Python</p>",
            "updated_at": "2024-01-01T00:00:00Z",
        }]
    })
    from app.sources.greenhouse import GreenhouseSource
    results = await GreenhouseSource().fetch()
    assert len(results) == 1
    assert results[0]["title"] == "SWE Intern"
    assert results[0]["source"] == "greenhouse"
    assert results[0]["location"] == "Remote"


@pytest.mark.asyncio
async def test_lever_adapter(mocker: Any) -> None:
    mocker.patch("app.sources.lever.LEVER_SLUGS", ["testcorp"])
    _mock_http(mocker, "app.sources.lever", [{
        "id": "abc-123",
        "text": "Backend Intern",
        "categories": {"location": "San Francisco, CA"},
        "descriptionPlain": "Requirements:\n- Node.js",
        "hostedUrl": "https://jobs.lever.co/testcorp/abc-123",
        "createdAt": 1704067200000,
    }])
    from app.sources.lever import LeverSource
    results = await LeverSource().fetch()
    assert len(results) == 1
    assert results[0]["title"] == "Backend Intern"
    assert results[0]["source"] == "lever"
    assert results[0]["location"] == "San Francisco, CA"


@pytest.mark.asyncio
async def test_ashby_adapter(mocker: Any) -> None:
    mocker.patch("app.sources.ashby.ASHBY_SLUGS", ["testcorp"])
    _mock_http(mocker, "app.sources.ashby", {
        "jobs": [{
            "id": "def-456",
            "title": "ML Engineering Intern",
            "locationName": "Hybrid",
            "descriptionHtml": "<p>Requirements: Python, PyTorch</p>",
            "jobUrl": "https://jobs.ashbyhq.com/testcorp/def-456",
            "publishedAt": "2024-01-15T00:00:00Z",
        }]
    })
    from app.sources.ashby import AshbySource
    results = await AshbySource().fetch()
    assert len(results) == 1
    assert results[0]["title"] == "ML Engineering Intern"
    assert results[0]["source"] == "ashby"


@pytest.mark.asyncio
async def test_remoteok_adapter(mocker: Any) -> None:
    _mock_http(mocker, "app.sources.remoteok", [
        {"legal": "RemoteOK"},
        {
            "id": "789",
            "position": "Frontend Intern",
            "company": "RemoteCo",
            "description": "Build cool UIs",
            "url": "https://remoteok.com/remote-jobs/789",
            "date": "2024-01-20T00:00:00Z",
            "salary_min": 1000,
        },
    ])
    from app.sources.remoteok import RemoteOKSource
    results = await RemoteOKSource().fetch()
    assert len(results) == 1
    assert results[0]["title"] == "Frontend Intern"
    assert results[0]["work_mode"] == "remote"
    assert results[0]["stipend"] == 1000


@pytest.mark.asyncio
async def test_remotive_adapter(mocker: Any) -> None:
    _mock_http(mocker, "app.sources.remotive", {
        "jobs": [{
            "id": 42,
            "title": "Data Engineering Intern",
            "company_name": "DataCo",
            "description": "SQL and Python",
            "url": "https://remotive.com/remote-jobs/42",
            "publication_date": "2024-01-25T00:00:00Z",
        }]
    })
    from app.sources.remotive import RemotiveSource
    results = await RemotiveSource().fetch()
    assert len(results) == 1
    assert results[0]["title"] == "Data Engineering Intern"
    assert results[0]["company_name"] == "DataCo"
    assert results[0]["source"] == "remotive"


# ---------------------------------------------------------------------------
# refresh() — ingestion + deduplication
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_refresh_ingests_and_response_shape(
    client: AsyncClient,
    admin_headers: dict[str, str],
    mocker: Any,
) -> None:
    # LeverSource is no longer in the active sources list (Lever v0 API deprecated).
    # Deliver the second test posting via RemoteOKSource instead.
    mocker.patch("app.sources.greenhouse.GreenhouseSource.fetch", new=AsyncMock(return_value=[GH_RAW]))
    mocker.patch("app.sources.ashby.AshbySource.fetch", new=AsyncMock(return_value=[]))
    mocker.patch("app.sources.remoteok.RemoteOKSource.fetch", new=AsyncMock(return_value=[LEVER_RAW]))
    mocker.patch("app.sources.remotive.RemotiveSource.fetch", new=AsyncMock(return_value=[]))

    resp = await client.post(REFRESH_URL, headers=admin_headers)
    assert resp.status_code == 202
    body = resp.json()
    assert body["ingested"] == 2
    assert body["deduped"] == 0

    list_resp = await client.get(POSTINGS_URL, headers=admin_headers)
    assert list_resp.status_code == 200
    data = list_resp.json()
    assert data["total"] == 2
    assert data["page"] == 1
    assert data["limit"] == 20
    assert len(data["data"]) == 2
    for posting in data["data"]:
        _assert_posting_shape(posting)


@pytest.mark.asyncio
async def test_refresh_deduplication_same_url(
    client: AsyncClient,
    admin_headers: dict[str, str],
    mocker: Any,
) -> None:
    mocker.patch("app.sources.greenhouse.GreenhouseSource.fetch", new=AsyncMock(return_value=[GH_RAW]))
    mocker.patch("app.sources.lever.LeverSource.fetch", new=AsyncMock(return_value=[]))
    mocker.patch("app.sources.ashby.AshbySource.fetch", new=AsyncMock(return_value=[]))
    mocker.patch("app.sources.remoteok.RemoteOKSource.fetch", new=AsyncMock(return_value=[]))
    mocker.patch("app.sources.remotive.RemotiveSource.fetch", new=AsyncMock(return_value=[]))

    r1 = await client.post(REFRESH_URL, headers=admin_headers)
    assert r1.json()["ingested"] == 1

    r2 = await client.post(REFRESH_URL, headers=admin_headers)
    assert r2.json()["ingested"] == 0
    assert r2.json()["deduped"] == 1


@pytest.mark.asyncio
async def test_refresh_cross_source_dedup(
    client: AsyncClient,
    admin_headers: dict[str, str],
    mocker: Any,
) -> None:
    # Same role, different URLs from two sources → one ingested, one deduped
    # (Lever source removed; use RemoteOK to deliver the second variant)
    mocker.patch("app.sources.greenhouse.GreenhouseSource.fetch", new=AsyncMock(return_value=[CROSS_A]))
    mocker.patch("app.sources.ashby.AshbySource.fetch", new=AsyncMock(return_value=[]))
    mocker.patch("app.sources.remoteok.RemoteOKSource.fetch", new=AsyncMock(return_value=[CROSS_B]))
    mocker.patch("app.sources.remotive.RemotiveSource.fetch", new=AsyncMock(return_value=[]))

    resp = await client.post(REFRESH_URL, headers=admin_headers)
    body = resp.json()
    assert body["ingested"] == 1
    assert body["deduped"] == 1


@pytest.mark.asyncio
async def test_company_resolution_single_row(
    client: AsyncClient,
    admin_headers: dict[str, str],
    db: AsyncSession,
    mocker: Any,
) -> None:
    # GH_RAW and LEVER_RAW both have company_name="TestCorp" → must create only 1 Company row
    # (Lever source removed; deliver second posting via RemoteOK)
    mocker.patch("app.sources.greenhouse.GreenhouseSource.fetch", new=AsyncMock(return_value=[GH_RAW]))
    mocker.patch("app.sources.ashby.AshbySource.fetch", new=AsyncMock(return_value=[]))
    mocker.patch("app.sources.remoteok.RemoteOKSource.fetch", new=AsyncMock(return_value=[LEVER_RAW]))
    mocker.patch("app.sources.remotive.RemotiveSource.fetch", new=AsyncMock(return_value=[]))

    await client.post(REFRESH_URL, headers=admin_headers)

    result = await db.execute(select(Company))
    companies = result.scalars().all()
    testcorp_rows = [c for c in companies if c.normalized_name == "testcorp"]
    assert len(testcorp_rows) == 1


@pytest.mark.asyncio
async def test_source_failure_does_not_abort_run(
    client: AsyncClient,
    admin_headers: dict[str, str],
    mocker: Any,
) -> None:
    # Greenhouse raises; RemoteOK returns valid data → posting still ingested
    # (Lever source removed; RemoteOK is the second active source here)
    mocker.patch(
        "app.sources.greenhouse.GreenhouseSource.fetch",
        new=AsyncMock(side_effect=RuntimeError("connection refused")),
    )
    mocker.patch("app.sources.ashby.AshbySource.fetch", new=AsyncMock(return_value=[]))
    mocker.patch("app.sources.remoteok.RemoteOKSource.fetch", new=AsyncMock(return_value=[LEVER_RAW]))
    mocker.patch("app.sources.remotive.RemotiveSource.fetch", new=AsyncMock(return_value=[]))

    resp = await client.post(REFRESH_URL, headers=admin_headers)
    assert resp.status_code == 202
    assert resp.json()["ingested"] == 1


# ---------------------------------------------------------------------------
# GET /api/postings + GET /api/postings/:id
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def seeded_posting(
    client: AsyncClient,
    admin_headers: dict[str, str],
    mocker: Any,
) -> dict[str, Any]:
    mocker.patch("app.sources.greenhouse.GreenhouseSource.fetch", new=AsyncMock(return_value=[GH_RAW]))
    mocker.patch("app.sources.lever.LeverSource.fetch", new=AsyncMock(return_value=[]))
    mocker.patch("app.sources.ashby.AshbySource.fetch", new=AsyncMock(return_value=[]))
    mocker.patch("app.sources.remoteok.RemoteOKSource.fetch", new=AsyncMock(return_value=[]))
    mocker.patch("app.sources.remotive.RemotiveSource.fetch", new=AsyncMock(return_value=[]))
    await client.post(REFRESH_URL, headers=admin_headers)
    resp = await client.get(POSTINGS_URL, headers=admin_headers)
    return resp.json()["data"][0]  # type: ignore[no-any-return]


@pytest.mark.asyncio
async def test_get_posting_by_id(
    client: AsyncClient,
    admin_headers: dict[str, str],
    seeded_posting: dict[str, Any],
) -> None:
    posting_id = seeded_posting["id"]
    resp = await client.get(f"{POSTINGS_URL}/{posting_id}", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "posting" in body
    _assert_posting_shape(body["posting"])
    assert body["posting"]["id"] == posting_id


@pytest.mark.asyncio
async def test_get_posting_not_found(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    fake_id = "00000000-0000-0000-0000-000000000000"
    resp = await client.get(f"{POSTINGS_URL}/{fake_id}", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "POSTING_NOT_FOUND"


@pytest.mark.asyncio
async def test_get_postings_requires_auth(client: AsyncClient) -> None:
    resp = await client.get(POSTINGS_URL)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_embedding_not_in_response(
    client: AsyncClient,
    admin_headers: dict[str, str],
    seeded_posting: dict[str, Any],
) -> None:
    posting_id = seeded_posting["id"]

    list_resp = await client.get(POSTINGS_URL, headers=admin_headers)
    for p in list_resp.json()["data"]:
        assert "embedding" not in p

    detail_resp = await client.get(f"{POSTINGS_URL}/{posting_id}", headers=admin_headers)
    assert "embedding" not in detail_resp.json()["posting"]


# ---------------------------------------------------------------------------
# Global visibility — no user isolation for postings
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_postings_global_visibility_two_users(
    client: AsyncClient,
    seeded_posting: dict[str, Any],
) -> None:
    r_a = await client.post(
        SIGNUP_URL,
        json={"name": "Alice", "email": "alice.p@example.com", "password": "pass1234"},
    )
    r_b = await client.post(
        SIGNUP_URL,
        json={"name": "Bob", "email": "bob.p@example.com", "password": "pass1234"},
    )
    headers_a = {"Authorization": f"Bearer {r_a.json()['token']}"}
    headers_b = {"Authorization": f"Bearer {r_b.json()['token']}"}

    resp_a = await client.get(POSTINGS_URL, headers=headers_a)
    resp_b = await client.get(POSTINGS_URL, headers=headers_b)

    assert resp_a.json()["total"] == resp_b.json()["total"] == 1
    assert resp_a.json()["data"][0]["id"] == resp_b.json()["data"][0]["id"]


# ---------------------------------------------------------------------------
# Admin gate
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_refresh_requires_admin(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    resp = await client.post(REFRESH_URL, headers=auth_headers)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_refresh_requires_auth(client: AsyncClient) -> None:
    resp = await client.post(REFRESH_URL)
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /api/postings/import
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_import_from_url_greenhouse(
    client: AsyncClient,
    auth_headers: dict[str, str],
    mocker: Any,
) -> None:
    mocker.patch(
        "app.sources.greenhouse.fetch_greenhouse_single",
        new=AsyncMock(return_value=GH_RAW),
    )
    resp = await client.post(
        IMPORT_URL,
        json={"url": "https://boards.greenhouse.io/testcorp/jobs/1"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert "posting" in body
    _assert_posting_shape(body["posting"])
    assert body["posting"]["title"] == GH_RAW["title"]


@pytest.mark.asyncio
async def test_import_from_url_unsupported_ats(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    resp = await client.post(
        IMPORT_URL,
        json={"url": "https://jobs.unknown-ats.com/company/role-123"},
        headers=auth_headers,
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "UNSUPPORTED_ATS"


@pytest.mark.asyncio
async def test_list_postings_filter_work_mode(
    client: AsyncClient,
    admin_headers: dict[str, str],
    mocker: Any,
) -> None:
    onsite_raw: RawPosting = {
        "title": "Onsite Engineering Intern",
        "company_name": "OnsiteCorp",
        "description": "In-office role",
        "source": "greenhouse",
        "source_url": "https://boards.greenhouse.io/onsite/jobs/2",
        "location": "New York, NY",
        "work_mode": "onsite",
        "stipend": None,
        "posted_at": None,
        "requirements": [],
    }
    mocker.patch("app.sources.greenhouse.GreenhouseSource.fetch", new=AsyncMock(return_value=[GH_RAW, onsite_raw]))
    mocker.patch("app.sources.lever.LeverSource.fetch", new=AsyncMock(return_value=[]))
    mocker.patch("app.sources.ashby.AshbySource.fetch", new=AsyncMock(return_value=[]))
    mocker.patch("app.sources.remoteok.RemoteOKSource.fetch", new=AsyncMock(return_value=[]))
    mocker.patch("app.sources.remotive.RemotiveSource.fetch", new=AsyncMock(return_value=[]))
    await client.post(REFRESH_URL, headers=admin_headers)

    remote_resp = await client.get(POSTINGS_URL, params={"work_mode": "remote"}, headers=admin_headers)
    onsite_resp = await client.get(POSTINGS_URL, params={"work_mode": "onsite"}, headers=admin_headers)

    assert remote_resp.json()["total"] == 1
    assert remote_resp.json()["data"][0]["work_mode"] == "remote"
    assert onsite_resp.json()["total"] == 1
    assert onsite_resp.json()["data"][0]["work_mode"] == "onsite"
