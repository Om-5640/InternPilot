"""Module 1 — Profile acceptance tests.

Covers:
- GET /profile auto-creates empty profile; shape matches contract; no embedding field
- POST /profile/resume: extracts skills+experience; unsupported type → 422; scanned PDF → 422
- POST /profile/github: valid user → projects+skills; invalid user → 404
- PUT /profile partial merge; PUT /profile/preferences bad work_mode → 422
- GET /profile/strength returns 0-100 + gaps; strength rises after adding data
- Data isolation: user A cannot see or affect user B's profile
- extract_structured: handles ```json fences; retries once on invalid JSON
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

PROFILE_URL = "/api/profile"
RESUME_URL = "/api/profile/resume"
GITHUB_URL_EP = "/api/profile/github"
PREFS_URL = "/api/profile/preferences"
STRENGTH_URL = "/api/profile/strength"
SIGNUP_URL = "/api/auth/signup"

PROFILE_FIELDS = {
    "user_id", "headline", "skills", "experience", "education",
    "projects", "github_url", "preferences", "profile_strength",
    "gaps", "created_at", "updated_at",
}
PREFS_FIELDS = {
    "domains", "work_mode", "stipend_min", "duration_months",
    "locations", "target_companies",
}

_LLM_RESUME_JSON = (
    '{"headline":"Software Engineer","skills":["Python","FastAPI","PostgreSQL"],'
    '"experience":[{"title":"SWE Intern","org":"Tech Corp","start":"2024-01",'
    '"end":"2024-06","description":"Built APIs"}],'
    '"education":[{"degree":"B.S. Computer Science","institution":"MIT",'
    '"year":2024,"gpa":3.9}],'
    '"projects":[{"name":"MyApp","description":"A web app","tech":["Python"],"url":null}],'
    '"github_url":"https://github.com/testuser",'
    '"domains":["software engineering","backend development"],'
    '"target_companies":["Google","Stripe","Figma"]}'
)


def _assert_profile_shape(profile: dict[str, Any]) -> None:
    assert set(profile.keys()) == PROFILE_FIELDS, f"Unexpected fields: {set(profile.keys())}"
    assert "embedding" not in profile
    assert set(profile["preferences"].keys()) == PREFS_FIELDS
    assert isinstance(profile["skills"], list)
    assert isinstance(profile["experience"], list)
    assert isinstance(profile["education"], list)
    assert isinstance(profile["projects"], list)
    assert isinstance(profile["gaps"], list)
    assert 0 <= profile["profile_strength"] <= 100


# ---------------------------------------------------------------------------
# Auto-use: mock embed so profile tests don't load sentence-transformers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def mock_embed(mocker: Any) -> None:
    mocker.patch(
        "app.services.profile_service.embed",
        new=AsyncMock(return_value=[[0.1] * 384]),
    )


# ---------------------------------------------------------------------------
# GET /profile — auto-creates
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_profile_autocreates(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    resp = await client.get(PROFILE_URL, headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "profile" in body
    _assert_profile_shape(body["profile"])
    assert body["profile"]["headline"] is None
    assert body["profile"]["skills"] == []


@pytest.mark.asyncio
async def test_get_profile_twice_same_row(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    r1 = await client.get(PROFILE_URL, headers=auth_headers)
    r2 = await client.get(PROFILE_URL, headers=auth_headers)
    assert r1.json()["profile"]["user_id"] == r2.json()["profile"]["user_id"]


# ---------------------------------------------------------------------------
# POST /profile/resume
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upload_resume_populates_profile(
    client: AsyncClient, auth_headers: dict[str, str], mocker: Any
) -> None:
    mocker.patch(
        "app.services.profile_service._extract_pdf_text",
        return_value="John Doe\nSoftware Engineer\nPython FastAPI PostgreSQL\n" * 10,
    )
    mocker.patch("app.llm.extract.complete", new=AsyncMock(return_value=_LLM_RESUME_JSON))

    resp = await client.post(
        RESUME_URL,
        files={"file": ("resume.pdf", b"%PDF-1.4 fake", "application/pdf")},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    profile = resp.json()["profile"]
    _assert_profile_shape(profile)
    assert len(profile["skills"]) > 0
    assert len(profile["experience"]) > 0
    assert profile["github_url"] == "https://github.com/testuser"
    assert len(profile["preferences"]["domains"]) > 0
    assert len(profile["preferences"]["target_companies"]) > 0
    assert "embedding" not in profile


@pytest.mark.asyncio
async def test_upload_unsupported_type_returns_422(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    resp = await client.post(
        RESUME_URL,
        files={"file": ("resume.txt", b"some text content", "text/plain")},
        headers=auth_headers,
    )
    assert resp.status_code == 415
    assert resp.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"


@pytest.mark.asyncio
async def test_upload_scanned_pdf_returns_422(
    client: AsyncClient, auth_headers: dict[str, str], mocker: Any
) -> None:
    mocker.patch("app.services.profile_service._extract_pdf_text", return_value="")

    resp = await client.post(
        RESUME_URL,
        files={"file": ("scan.pdf", b"%PDF-1.4 scanned", "application/pdf")},
        headers=auth_headers,
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "unparseable_resume"


# ---------------------------------------------------------------------------
# POST /profile/github
# ---------------------------------------------------------------------------

def _make_github_mocks(mocker: Any, *, username: str = "testuser") -> None:
    mock_http = AsyncMock()
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=None)

    repos_resp = MagicMock()
    repos_resp.status_code = 200
    repos_resp.raise_for_status = MagicMock()
    repos_resp.json.return_value = [
        {
            "name": "my-repo",
            "description": "A cool repo",
            "stargazers_count": 42,
            "html_url": f"https://github.com/{username}/my-repo",
        }
    ]

    langs_resp = MagicMock()
    langs_resp.status_code = 200
    langs_resp.json.return_value = {"Python": 8000, "TypeScript": 2000}

    mock_http.get = AsyncMock(side_effect=[repos_resp, langs_resp])
    mocker.patch("httpx.AsyncClient", return_value=mock_http)


@pytest.mark.asyncio
async def test_github_pull_valid_user(
    client: AsyncClient, auth_headers: dict[str, str], mocker: Any
) -> None:
    _make_github_mocks(mocker)

    resp = await client.post(
        GITHUB_URL_EP,
        json={"github_url": "https://github.com/testuser"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    profile = resp.json()["profile"]
    _assert_profile_shape(profile)
    assert len(profile["projects"]) > 0
    assert profile["projects"][0]["name"] == "my-repo"
    assert "Python" in profile["skills"] or "TypeScript" in profile["skills"]
    assert profile["github_url"] == "https://github.com/testuser"


@pytest.mark.asyncio
async def test_github_pull_invalid_user_404(
    client: AsyncClient, auth_headers: dict[str, str], mocker: Any
) -> None:
    mock_http = AsyncMock()
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=None)

    not_found_resp = MagicMock()
    not_found_resp.status_code = 404
    mock_http.get = AsyncMock(return_value=not_found_resp)
    mocker.patch("httpx.AsyncClient", return_value=mock_http)

    resp = await client.post(
        GITHUB_URL_EP,
        json={"github_url": "https://github.com/no-such-user-xyz999"},
        headers=auth_headers,
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "GITHUB_USER_NOT_FOUND"


# ---------------------------------------------------------------------------
# PUT /profile partial merge
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_put_profile_partial_merge(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    # First set headline + skills
    r1 = await client.put(
        PROFILE_URL,
        json={"headline": "Backend Engineer", "skills": ["Python", "Go"]},
        headers=auth_headers,
    )
    assert r1.status_code == 200
    assert r1.json()["profile"]["headline"] == "Backend Engineer"

    # Second update: only change headline; skills should be preserved
    r2 = await client.put(
        PROFILE_URL,
        json={"headline": "Senior Backend Engineer"},
        headers=auth_headers,
    )
    assert r2.status_code == 200
    profile = r2.json()["profile"]
    assert profile["headline"] == "Senior Backend Engineer"
    assert set(profile["skills"]) == {"Python", "Go"}


@pytest.mark.asyncio
async def test_put_preferences_valid(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    resp = await client.put(
        PREFS_URL,
        json={"work_mode": "remote", "domains": ["software engineering"]},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    prefs = resp.json()["profile"]["preferences"]
    assert prefs["work_mode"] == "remote"
    assert "software engineering" in prefs["domains"]


@pytest.mark.asyncio
async def test_put_preferences_bad_work_mode_returns_422(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    resp = await client.put(
        PREFS_URL,
        json={"work_mode": "in-space"},
        headers=auth_headers,
    )
    assert resp.status_code == 422
    assert "error" in resp.json()


# ---------------------------------------------------------------------------
# GET /profile/strength
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_strength_shape(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    resp = await client.get(STRENGTH_URL, headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "profile_strength" in body
    assert "gaps" in body
    assert 0 <= body["profile_strength"] <= 100
    assert isinstance(body["gaps"], list)


@pytest.mark.asyncio
async def test_strength_rises_after_adding_data(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    r0 = await client.get(STRENGTH_URL, headers=auth_headers)
    initial = r0.json()["profile_strength"]

    await client.put(
        PROFILE_URL,
        json={
            "headline": "ML Engineer",
            "skills": ["Python", "TensorFlow", "PyTorch", "SQL", "Docker"],
        },
        headers=auth_headers,
    )

    r1 = await client.get(STRENGTH_URL, headers=auth_headers)
    assert r1.json()["profile_strength"] > initial


# ---------------------------------------------------------------------------
# Data isolation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_data_isolation(client: AsyncClient) -> None:
    resp_a = await client.post(
        SIGNUP_URL,
        json={"name": "Alice Iso", "email": "alice.iso@example.com", "password": "password123"},
    )
    assert resp_a.status_code == 201
    headers_a = {"Authorization": f"Bearer {resp_a.json()['token']}"}

    resp_b = await client.post(
        SIGNUP_URL,
        json={"name": "Bob Iso", "email": "bob.iso@example.com", "password": "password123"},
    )
    assert resp_b.status_code == 201
    headers_b = {"Authorization": f"Bearer {resp_b.json()['token']}"}

    # A sets their headline
    await client.put(PROFILE_URL, json={"headline": "Alice's headline"}, headers=headers_a)

    # B's profile should not reflect A's headline
    resp = await client.get(PROFILE_URL, headers=headers_b)
    assert resp.status_code == 200
    assert resp.json()["profile"]["headline"] is None

    # A's profile still has their headline
    resp = await client.get(PROFILE_URL, headers=headers_a)
    assert resp.json()["profile"]["headline"] == "Alice's headline"


# ---------------------------------------------------------------------------
# extract_structured unit tests (no DB, no HTTP)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_extract_structured_handles_fenced_json(mocker: Any) -> None:
    from app.llm.extract import extract_structured
    from app.schemas.profile import ResumeExtract

    fenced = '```json\n{"headline":"Dev","skills":["Python"],"experience":[],"education":[],"projects":[]}\n```'
    mocker.patch("app.llm.extract.complete", new=AsyncMock(return_value=fenced))

    result = await extract_structured("some resume text", ResumeExtract, "Extract info.")
    assert result.headline == "Dev"
    assert "Python" in result.skills


@pytest.mark.asyncio
async def test_extract_structured_retries_on_invalid_json(mocker: Any) -> None:
    from app.llm.extract import extract_structured
    from app.schemas.profile import ResumeExtract

    valid_json = '{"headline":null,"skills":["Go"],"experience":[],"education":[],"projects":[]}'
    mock_complete = mocker.patch(
        "app.llm.extract.complete",
        new=AsyncMock(side_effect=["not-valid-json-at-all", valid_json]),
    )

    result = await extract_structured("some text", ResumeExtract, "Extract info.")
    assert mock_complete.call_count == 2
    assert "Go" in result.skills
