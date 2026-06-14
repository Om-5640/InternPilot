"""Module 3 — Matching & Ranking acceptance tests.

Covers:
- Auth requirement on all three endpoints
- Graceful empty result when profile has no embedding
- Ranked feed: match_score in [0,1]; matched/missing skills correct
- Hybrid score: skill-overlapping posting outranks semantic-only match
- Ranking is by expected_value DESC
- include_ghosts filter
- work_mode filter + pagination
- GET /matches/:id shape; optional LLM explanation path (mocked); 404 on unknown id
- GET /skill-gaps ranks missing skills by unlockable_roles
- Two users with different profiles get different match rankings
- expected_value == match_score * response_likelihood * (1 - ghost_score)
- ruff + mypy clean
"""
from __future__ import annotations

import math
import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.llm.embeddings import EMBEDDING_DIM
from app.models.company import Company
from app.models.posting import Posting
from app.models.profile import Profile
from app.models.user import AuthProvider, User, UserRole

MATCHES_URL = "/api/matches"
SKILL_GAPS_URL = "/api/skill-gaps"

# ---------------------------------------------------------------------------
# Deterministic unit vectors for embedding-controlled tests
# ---------------------------------------------------------------------------

def _vec(pos: int, val: float = 1.0) -> list[float]:
    """Return a 384-dim vector with `val` at `pos` and 0 elsewhere."""
    v = [0.0] * EMBEDDING_DIM
    v[pos] = val
    return v


# Profile 1: "Python / FastAPI developer" leaning
P1_EMBEDDING = _vec(0)
P1_SKILLS = ["Python", "FastAPI"]

# Profile 2: "Java / Spring developer" leaning
P2_EMBEDDING = _vec(1)
P2_SKILLS = ["Java", "Spring"]

# Posting A: strong semantic + skill match for Profile 1
PA_EMBEDDING = _vec(0)   # cosine_dist with P1 = 0.0, semantic_sim = 1.0
PA_REQS = ["Python", "SQL"]
PA_SOURCE_URL = "https://boards.greenhouse.io/testco/jobs/100"

# Posting B: no semantic or skill match for Profile 1
PB_EMBEDDING = _vec(1)   # cosine_dist with P1 = 1.0, semantic_sim = 0.0
PB_REQS = ["Java", "Spring"]
PB_SOURCE_URL = "https://boards.greenhouse.io/testco/jobs/200"

# Posting C: adds SQL + Docker requirements (for skill-gap test)
PC_EMBEDDING = _vec(0)
PC_REQS = ["Python", "SQL", "Docker"]
PC_SOURCE_URL = "https://boards.greenhouse.io/testco/jobs/300"

# Ghost posting
PG_EMBEDDING = _vec(0)
PG_REQS: list[str] = []
PG_SOURCE_URL = "https://boards.greenhouse.io/testco/jobs/999"


# ---------------------------------------------------------------------------
# autouse: mock embed so tests never call the real model
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def mock_embed(mocker: Any) -> None:
    mocker.patch(
        "app.services.aggregation_service.embed",
        new=AsyncMock(return_value=[_vec(0)]),
    )


# ---------------------------------------------------------------------------
# Auth fixtures: two independent users
# ---------------------------------------------------------------------------

async def _make_user(
    db: AsyncSession,
    *,
    name: str,
    email: str,
    skills: list[str],
    embedding: list[float] | None,
) -> tuple[User, dict[str, str]]:
    user = User(
        name=name,
        email=email,
        password_hash=hash_password("password123"),
        role=UserRole.student,
        auth_provider=AuthProvider.password,
        consent={"gmail": False, "github": False, "alumni_data": False},
    )
    db.add(user)
    await db.flush()

    profile = Profile(
        user_id=user.id,
        skills=skills,
        embedding=embedding,
    )
    db.add(profile)
    await db.commit()

    token = create_access_token({"sub": str(user.id)})
    headers = {"Authorization": f"Bearer {token}"}
    return user, headers


@pytest_asyncio.fixture
async def user1(db: AsyncSession) -> tuple[User, dict[str, str]]:
    return await _make_user(db, name="Alice", email="alice@test.com", skills=P1_SKILLS, embedding=P1_EMBEDDING)


@pytest_asyncio.fixture
async def user2(db: AsyncSession) -> tuple[User, dict[str, str]]:
    return await _make_user(db, name="Bob", email="bob@test.com", skills=P2_SKILLS, embedding=P2_EMBEDDING)


@pytest_asyncio.fixture
async def user_no_embedding(db: AsyncSession) -> tuple[User, dict[str, str]]:
    return await _make_user(db, name="Empty", email="empty@test.com", skills=[], embedding=None)


# ---------------------------------------------------------------------------
# DB fixture: seed postings with controlled embeddings
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def seeded(db: AsyncSession) -> dict[str, Any]:
    """Insert company + postings A, B, C and a ghost posting G."""
    company = Company(
        name="TestCo Inc",
        normalized_name="testco",
        domain="testco.com",
    )
    db.add(company)
    await db.flush()

    now_str = "2026-01-01T00:00:00Z"

    def _posting(
        title: str,
        reqs: list[str],
        emb: list[float],
        url: str,
        work_mode: str = "remote",
        is_ghost: bool = False,
        ghost_score: float = 0.0,
    ) -> Posting:
        return Posting(
            company_id=company.id,
            title=title,
            description="",
            requirements=reqs,
            location="Remote",
            work_mode=work_mode,
            source="greenhouse",
            source_url=url,
            last_seen_at=now_str,
            posted_at=now_str,
            dedup_key=str(uuid.uuid4())[:16],
            status="active",
            ghost_score=ghost_score,
            is_ghost=is_ghost,
            embedding=emb,
        )

    pa = _posting("Python Backend Intern", PA_REQS, PA_EMBEDDING, PA_SOURCE_URL)
    pb = _posting("Java Developer Intern", PB_REQS, PB_EMBEDDING, PB_SOURCE_URL, work_mode="onsite")
    pc = _posting("Data Intern", PC_REQS, PC_EMBEDDING, PC_SOURCE_URL)
    pg = _posting("Ghost Posting Intern", PG_REQS, PG_EMBEDDING, PG_SOURCE_URL, is_ghost=True, ghost_score=0.9)

    for p in (pa, pb, pc, pg):
        db.add(p)
    await db.commit()

    return {"company": company, "pa": pa, "pb": pb, "pc": pc, "pg": pg}


# ---------------------------------------------------------------------------
# Auth required
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_matches_requires_auth(client: AsyncClient) -> None:
    r = await client.get(MATCHES_URL)
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_skill_gaps_requires_auth(client: AsyncClient) -> None:
    r = await client.get(SKILL_GAPS_URL)
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_match_detail_requires_auth(client: AsyncClient, seeded: dict[str, Any]) -> None:
    pid = str(seeded["pa"].id)
    r = await client.get(f"{MATCHES_URL}/{pid}")
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Empty / no-embedding profile
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_matches_no_profile_returns_empty(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """User with no profile at all gets an empty result, not a 500."""
    u = User(
        name="Noprofile",
        email="noprofile@test.com",
        password_hash=hash_password("x"),
        role=UserRole.student,
        auth_provider=AuthProvider.password,
        consent={"gmail": False, "github": False, "alumni_data": False},
    )
    db.add(u)
    await db.commit()
    token = create_access_token({"sub": str(u.id)})

    r = await client.get(MATCHES_URL, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert body["data"] == []
    assert body["total"] == 0


@pytest.mark.asyncio
async def test_matches_no_embedding_returns_empty(
    client: AsyncClient,
    user_no_embedding: tuple[User, dict[str, str]],
    seeded: dict[str, Any],
) -> None:
    _, headers = user_no_embedding
    r = await client.get(MATCHES_URL, headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["data"] == []
    assert body["total"] == 0


# ---------------------------------------------------------------------------
# Feed shape and score correctness
# ---------------------------------------------------------------------------

def _assert_match_shape(m: dict[str, Any]) -> None:
    required = {
        "posting_id", "posting", "match_score", "match_explanation",
        "matched_skills", "missing_skills", "response_likelihood",
        "expected_value", "ghost_score", "is_ghost", "created_at",
    }
    assert required <= m.keys(), f"Missing fields: {required - m.keys()}"
    assert 0.0 <= m["match_score"] <= 1.0, "match_score out of range"
    assert 0.0 <= m["response_likelihood"] <= 1.0, "response_likelihood out of range"
    assert 0.0 <= m["expected_value"] <= 1.0, "expected_value out of range"
    assert isinstance(m["matched_skills"], list)
    assert isinstance(m["missing_skills"], list)
    assert "embedding" not in m
    assert "embedding" not in m["posting"]


@pytest.mark.asyncio
async def test_matches_shape(
    client: AsyncClient,
    user1: tuple[User, dict[str, str]],
    seeded: dict[str, Any],
) -> None:
    _, headers = user1
    r = await client.get(MATCHES_URL, headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert "data" in body
    assert "total" in body
    assert "page" in body
    assert "limit" in body
    for m in body["data"]:
        _assert_match_shape(m)


@pytest.mark.asyncio
async def test_matched_and_missing_skills_correct(
    client: AsyncClient,
    user1: tuple[User, dict[str, str]],
    seeded: dict[str, Any],
) -> None:
    """Profile skills = ["Python", "FastAPI"]; Posting A reqs = ["Python", "SQL"].

    Expected: matched=["Python"], missing=["SQL"].
    """
    _, headers = user1
    pa_id = str(seeded["pa"].id)
    r = await client.get(f"{MATCHES_URL}/{pa_id}", headers=headers)
    assert r.status_code == 200
    m = r.json()["match"]
    assert "Python" in m["matched_skills"]
    assert "SQL" in m["missing_skills"]
    assert "FastAPI" not in m["missing_skills"]  # FastAPI is a profile skill, not a req


# ---------------------------------------------------------------------------
# Hybrid ranking
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_hybrid_ranking_skill_overlap_boosts_score(
    client: AsyncClient,
    user1: tuple[User, dict[str, str]],
    seeded: dict[str, Any],
) -> None:
    """Posting A (same embedding + overlapping skills) must outrank Posting B
    (orthogonal embedding + no overlapping skills) for Profile 1."""
    _, headers = user1
    r = await client.get(MATCHES_URL, headers=headers)
    assert r.status_code == 200
    matches = r.json()["data"]

    # Exclude ghost posting from comparison
    non_ghost = [m for m in matches if not m["is_ghost"]]
    ids_in_order = [m["posting_id"] for m in non_ghost]

    pa_id = str(seeded["pa"].id)
    pb_id = str(seeded["pb"].id)
    assert pa_id in ids_in_order
    assert pb_id in ids_in_order
    assert ids_in_order.index(pa_id) < ids_in_order.index(pb_id), (
        "Posting A (skill overlap) should rank above Posting B (no overlap)"
    )


@pytest.mark.asyncio
async def test_ranked_by_expected_value(
    client: AsyncClient,
    user1: tuple[User, dict[str, str]],
    seeded: dict[str, Any],
) -> None:
    _, headers = user1
    r = await client.get(MATCHES_URL, headers=headers)
    evs = [m["expected_value"] for m in r.json()["data"]]
    assert evs == sorted(evs, reverse=True), "Feed is not sorted by expected_value DESC"


# ---------------------------------------------------------------------------
# expected_value formula
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_expected_value_formula(
    client: AsyncClient,
    user1: tuple[User, dict[str, str]],
    seeded: dict[str, Any],
) -> None:
    _, headers = user1
    r = await client.get(MATCHES_URL, headers=headers, params={"include_ghosts": "true"})
    for m in r.json()["data"]:
        computed = m["match_score"] * m["response_likelihood"] * (1.0 - m["ghost_score"])
        computed = max(0.0, min(1.0, computed))
        assert math.isclose(m["expected_value"], computed, abs_tol=1e-6), (
            f"EV mismatch: {m['expected_value']} != {computed}"
        )


# ---------------------------------------------------------------------------
# Ghost filter
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_include_ghosts_false_excludes_ghost(
    client: AsyncClient,
    user1: tuple[User, dict[str, str]],
    seeded: dict[str, Any],
) -> None:
    _, headers = user1
    r = await client.get(MATCHES_URL, headers=headers, params={"include_ghosts": "false"})
    ids = [m["posting_id"] for m in r.json()["data"]]
    assert str(seeded["pg"].id) not in ids


@pytest.mark.asyncio
async def test_include_ghosts_true_includes_ghost(
    client: AsyncClient,
    user1: tuple[User, dict[str, str]],
    seeded: dict[str, Any],
) -> None:
    _, headers = user1
    r = await client.get(MATCHES_URL, headers=headers, params={"include_ghosts": "true"})
    ids = [m["posting_id"] for m in r.json()["data"]]
    assert str(seeded["pg"].id) in ids


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_work_mode_filter(
    client: AsyncClient,
    user1: tuple[User, dict[str, str]],
    seeded: dict[str, Any],
) -> None:
    _, headers = user1
    r = await client.get(MATCHES_URL, headers=headers, params={"work_mode": "onsite"})
    assert r.status_code == 200
    data = r.json()["data"]
    assert all(m["posting"]["work_mode"] == "onsite" for m in data)
    # Only Posting B is onsite
    assert len(data) == 1
    assert data[0]["posting_id"] == str(seeded["pb"].id)


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pagination(
    client: AsyncClient,
    user1: tuple[User, dict[str, str]],
    seeded: dict[str, Any],
) -> None:
    _, headers = user1
    # Fetch all non-ghost matches in one page
    r_all = await client.get(MATCHES_URL, headers=headers, params={"limit": 100})
    total = r_all.json()["total"]
    assert total >= 3  # pa, pb, pc (ghost excluded)

    # Page 1 with limit=1
    r1 = await client.get(MATCHES_URL, headers=headers, params={"page": 1, "limit": 1})
    assert len(r1.json()["data"]) == 1
    assert r1.json()["total"] == total

    # Page 2 with limit=1
    r2 = await client.get(MATCHES_URL, headers=headers, params={"page": 2, "limit": 1})
    assert len(r2.json()["data"]) == 1
    # Different item on page 2
    assert r2.json()["data"][0]["posting_id"] != r1.json()["data"][0]["posting_id"]


# ---------------------------------------------------------------------------
# Detail endpoint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_match_detail_found(
    client: AsyncClient,
    user1: tuple[User, dict[str, str]],
    seeded: dict[str, Any],
) -> None:
    _, headers = user1
    pa_id = str(seeded["pa"].id)
    r = await client.get(f"{MATCHES_URL}/{pa_id}", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert "match" in body
    _assert_match_shape(body["match"])
    assert body["match"]["posting_id"] == pa_id


@pytest.mark.asyncio
async def test_match_detail_not_found(
    client: AsyncClient,
    user1: tuple[User, dict[str, str]],
) -> None:
    _, headers = user1
    r = await client.get(f"{MATCHES_URL}/{uuid.uuid4()}", headers=headers)
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "POSTING_NOT_FOUND"


@pytest.mark.asyncio
async def test_match_detail_llm_explanation(
    client: AsyncClient,
    user1: tuple[User, dict[str, str]],
    seeded: dict[str, Any],
) -> None:
    """Requesting ?enrich=true calls complete(); mock verifies the path."""
    _, headers = user1
    pa_id = str(seeded["pa"].id)
    with patch(
        "app.services.matching_service._llm_explanation_for_detail",
        new=AsyncMock(return_value="Great fit for your Python background."),
    ):
        r = await client.get(
            f"{MATCHES_URL}/{pa_id}", headers=headers, params={"enrich": "true"}
        )
    assert r.status_code == 200
    assert r.json()["match"]["match_explanation"] == "Great fit for your Python background."


# ---------------------------------------------------------------------------
# Skill gaps
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_skill_gaps_shape_and_ranking(
    client: AsyncClient,
    user1: tuple[User, dict[str, str]],
    seeded: dict[str, Any],
) -> None:
    """Profile skills = ["Python", "FastAPI"].

    Postings in DB (non-ghost, active):
      A: ["Python", "SQL"]         → missing: SQL
      B: ["Java", "Spring"]         → missing: Java, Spring
      C: ["Python", "SQL", "Docker"] → missing: SQL, Docker

    Missing skill counts:
      SQL:    2 (A, C)
      Java:   1 (B)
      Spring: 1 (B)
      Docker: 1 (C)

    SQL should rank first (2 unlockable_roles).
    """
    _, headers = user1
    r = await client.get(SKILL_GAPS_URL, headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert "gaps" in body

    gaps = body["gaps"]
    assert len(gaps) >= 1

    # Verify descending order
    counts = [g["unlockable_roles"] for g in gaps]
    assert counts == sorted(counts, reverse=True)

    # SQL must be first (count=2)
    skills_in_order = [g["skill"] for g in gaps]
    assert "sql" in skills_in_order[0].lower(), (
        f"SQL should be top gap; got {skills_in_order[0]!r}"
    )
    assert gaps[0]["unlockable_roles"] == 2


@pytest.mark.asyncio
async def test_skill_gaps_no_embedding_returns_empty(
    client: AsyncClient,
    user_no_embedding: tuple[User, dict[str, str]],
    seeded: dict[str, Any],
) -> None:
    _, headers = user_no_embedding
    r = await client.get(SKILL_GAPS_URL, headers=headers)
    assert r.status_code == 200
    assert r.json()["gaps"] == []


# ---------------------------------------------------------------------------
# Per-user correctness (two users → different rankings)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_two_users_get_different_rankings(
    client: AsyncClient,
    user1: tuple[User, dict[str, str]],
    user2: tuple[User, dict[str, str]],
    seeded: dict[str, Any],
) -> None:
    """User1 (P1_EMBEDDING ~ Posting A) should rank A first.
    User2 (P2_EMBEDDING ~ Posting B) should rank B first."""
    _, headers1 = user1
    _, headers2 = user2

    r1 = await client.get(MATCHES_URL, headers=headers1)
    r2 = await client.get(MATCHES_URL, headers=headers2)

    ids1 = [m["posting_id"] for m in r1.json()["data"] if not m["is_ghost"]]
    ids2 = [m["posting_id"] for m in r2.json()["data"] if not m["is_ghost"]]

    pa_id = str(seeded["pa"].id)
    pb_id = str(seeded["pb"].id)

    assert ids1.index(pa_id) < ids1.index(pb_id), "User1 should rank A before B"
    assert ids2.index(pb_id) < ids2.index(pa_id), "User2 should rank B before A"


# ---------------------------------------------------------------------------
# match_detail for user with no embedding still returns a response (no crash)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_match_detail_no_embedding_returns_zero_match(
    client: AsyncClient,
    user_no_embedding: tuple[User, dict[str, str]],
    seeded: dict[str, Any],
) -> None:
    _, headers = user_no_embedding
    pa_id = str(seeded["pa"].id)
    r = await client.get(f"{MATCHES_URL}/{pa_id}", headers=headers)
    assert r.status_code == 200
    m = r.json()["match"]
    assert m["match_score"] == 0.0
    assert m["expected_value"] == 0.0
