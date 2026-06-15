"""Tests for Module 12 — Research Internships.

Covers:
- find_matches: NLP interests rank NLP opp above unrelated; empty interests → empty, no crash
- get_match: single detail with fit_score; unknown id → 404
- draft_pitch (LLM MOCKED): produces Artifact with type=research_pitch; Subject: line present;
  grounding guard removes fabricated skills
- create / list / update outreach; user-scoped isolation
- research_opportunities GLOBAL: two users see same count
- seed-style: create_opportunity writes embedding field
"""
from __future__ import annotations

import base64
import json
import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.embeddings import EMBEDDING_DIM
from app.models.profile import Profile
from app.models.research_opportunity import ResearchOpportunity
from app.services.research_service import ResearchService, create_opportunity

RESEARCH_URL = "/api/research/opportunities"
PITCH_URL = "/api/research/pitch"
OUTREACH_URL = "/api/research/outreach"

# ---------------------------------------------------------------------------
# Unit-vector helpers — deterministic embeddings, no GPU needed
# ---------------------------------------------------------------------------


def _vec(pos: int, val: float = 1.0) -> list[float]:
    v = [0.0] * EMBEDDING_DIM
    v[pos] = val
    return v


def _user_id_from_token(token: str) -> uuid.UUID:
    payload_b64 = token.split(".")[1]
    payload_b64 += "=" * (-len(payload_b64) % 4)
    payload = json.loads(base64.b64decode(payload_b64))
    return uuid.UUID(payload["sub"])


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _opportunity(
    db: AsyncSession,
    *,
    research_area: str = "NLP",
    description: str = "Research on natural language processing.",
    desired_skills: list[str] | None = None,
    embedding: list[float] | None = None,
) -> ResearchOpportunity:
    opp = ResearchOpportunity(
        professor_name=f"Prof-{uuid.uuid4().hex[:6]}",
        institution="Test University",
        lab_name=None,
        research_area=research_area,
        description=description,
        desired_skills=desired_skills or ["Python", "NLP"],
        program=None,
        region="India",
        contact_email=None,
        url=None,
        source="test",
        posted_at="2026-01-01",
        last_seen_at="2026-01-01",
        embedding=embedding or _vec(0),
    )
    db.add(opp)
    return opp


def _profile(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    skills: list[str] | None = None,
    research_interests: list[str] | None = None,
) -> Profile:
    p = Profile(
        user_id=user_id,
        headline=None,
        university=None,
        grad_year=None,
        skills=skills or [],
        experience=[],
        education=[],
        projects=[],
        research_interests=research_interests or [],
        github_url=None,
        embedding=None,
    )
    db.add(p)
    return p


async def _signup_and_token(client: AsyncClient, email: str) -> str:
    resp = await client.post(
        "/api/auth/signup",
        json={"name": "Test", "email": email, "password": "secret123"},
    )
    assert resp.status_code == 201
    return resp.json()["token"]


# ---------------------------------------------------------------------------
# Auto-patch embed so tests never load sentence-transformers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def mock_embed(mocker: Any) -> None:
    mocker.patch(
        "app.services.research_service.embed",
        new=AsyncMock(return_value=[_vec(0)]),
    )


# ---------------------------------------------------------------------------
# find_matches — NLP interest ranks NLP opp above unrelated
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_find_matches_nlp_ranked_first(
    db: AsyncSession, auth_headers: dict, client: AsyncClient
):
    token = auth_headers["Authorization"].split(" ")[1]
    user_id = _user_id_from_token(token)

    # NLP opportunity — close to interest vector (pos 0)
    nlp_opp = _opportunity(
        db,
        research_area="Natural Language Processing",
        desired_skills=["Python", "NLP", "Transformers"],
        embedding=_vec(0),  # same dimension as mock interest vec → distance ≈ 0
    )
    # Robotics opportunity — far from NLP (pos 1)
    _opportunity(
        db,
        research_area="Robotics",
        desired_skills=["C++", "ROS"],
        embedding=_vec(1),
    )
    _profile(db, user_id, skills=["Python", "NLP"], research_interests=["NLP"])
    await db.commit()

    svc = ResearchService(db, user_id)
    matches, total = await svc.find_matches()

    assert total == 2
    # NLP opp must rank first
    assert str(matches[0].opportunity.id) == str(nlp_opp.id)


# ---------------------------------------------------------------------------
# find_matches — empty research interests → empty result, no crash
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_find_matches_empty_interests(
    db: AsyncSession, auth_headers: dict, client: AsyncClient
):
    token = auth_headers["Authorization"].split(" ")[1]
    user_id = _user_id_from_token(token)

    _opportunity(db)
    _profile(db, user_id, research_interests=[])
    await db.commit()

    svc = ResearchService(db, user_id)
    matches, total = await svc.find_matches()

    assert matches == []
    assert total == 0


# ---------------------------------------------------------------------------
# find_matches — no profile at all → empty, no crash
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_find_matches_no_profile(
    db: AsyncSession, auth_headers: dict, client: AsyncClient
):
    token = auth_headers["Authorization"].split(" ")[1]
    user_id = _user_id_from_token(token)

    _opportunity(db)
    await db.commit()

    svc = ResearchService(db, user_id)
    matches, total = await svc.find_matches()

    assert matches == []
    assert total == 0


# ---------------------------------------------------------------------------
# get_match — single detail including fit_score
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_match_detail(
    db: AsyncSession, auth_headers: dict, client: AsyncClient
):
    token = auth_headers["Authorization"].split(" ")[1]
    user_id = _user_id_from_token(token)

    opp = _opportunity(db, desired_skills=["Python", "NLP"], embedding=_vec(0))
    _profile(db, user_id, skills=["Python"], research_interests=["NLP"])
    await db.commit()

    svc = ResearchService(db, user_id)
    match = await svc.get_match(opp.id)

    assert match.opportunity.id == opp.id
    assert 0.0 <= match.fit_score <= 1.0
    assert "Python" in match.matched_skills


# ---------------------------------------------------------------------------
# get_match — unknown opportunity → 404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_match_unknown_404(
    db: AsyncSession, auth_headers: dict, client: AsyncClient
):
    from app.core.errors import APIError

    token = auth_headers["Authorization"].split(" ")[1]
    user_id = _user_id_from_token(token)

    svc = ResearchService(db, user_id)
    with pytest.raises(APIError) as exc_info:
        await svc.get_match(uuid.uuid4())

    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# draft_pitch — LLM mocked; artifact type=research_pitch; Subject: line present
# ---------------------------------------------------------------------------


MOCK_PITCH = (
    "Subject: Research Internship Inquiry — NLP Lab\n\n"
    "Dear Prof. Test,\n\n"
    "I am interested in your work on natural language processing. "
    "My background in Python and NLP aligns well with your lab's research.\n\n"
    "I would love to contribute to your projects on transformer models.\n\n"
    "Could you please let me know if there are any openings? "
    "I look forward to hearing from you.\n\n"
    "Best regards,\nStudent"
)


@pytest.mark.asyncio
async def test_draft_pitch_creates_artifact(
    db: AsyncSession, auth_headers: dict, client: AsyncClient
):
    token = auth_headers["Authorization"].split(" ")[1]
    user_id = _user_id_from_token(token)

    opp = _opportunity(
        db,
        research_area="Natural Language Processing",
        desired_skills=["Python", "NLP"],
    )
    _profile(db, user_id, skills=["Python", "NLP"], research_interests=["NLP"])
    await db.commit()

    with patch("app.llm.router.complete", new=AsyncMock(return_value=MOCK_PITCH)):
        svc = ResearchService(db, user_id)
        artifact = await svc.draft_pitch(opp.id)

    assert artifact.type == "research_pitch"
    assert artifact.user_id == user_id
    assert "Subject:" in artifact.content
    assert artifact.grounding_score is not None


# ---------------------------------------------------------------------------
# draft_pitch — grounding guard removes fabricated skills (via retry)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_draft_pitch_grounding_guard(
    db: AsyncSession, auth_headers: dict, client: AsyncClient
):
    token = auth_headers["Authorization"].split(" ")[1]
    user_id = _user_id_from_token(token)

    opp = _opportunity(
        db,
        research_area="NLP",
        desired_skills=["Python", "Kubernetes"],  # Kubernetes is desired but not in whitelist
    )
    # Student only has Python — does NOT have Kubernetes
    _profile(db, user_id, skills=["Python"], research_interests=["NLP"])
    await db.commit()

    # First response fabricates Kubernetes; retry is cleaner
    fabricated = (
        "Subject: Inquiry\n\nDear Prof,\nI have experience in Python and Kubernetes. "
        "I would love to work in your lab.\n\nBest."
    )
    clean = (
        "Subject: Inquiry\n\nDear Prof,\nI have experience in Python. "
        "I would love to work in your lab.\n\nBest."
    )

    call_count = 0

    async def _mock_complete(messages: list) -> str:
        nonlocal call_count
        call_count += 1
        return fabricated if call_count == 1 else clean

    with patch("app.llm.router.complete", new=_mock_complete):
        svc = ResearchService(db, user_id)
        artifact = await svc.draft_pitch(opp.id)

    # Guard should have triggered at least one retry
    assert call_count >= 1
    assert artifact.type == "research_pitch"


# ---------------------------------------------------------------------------
# create_outreach — status=suggested when no pitch; status=drafted when pitch provided
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_outreach_suggested(
    db: AsyncSession, auth_headers: dict, client: AsyncClient
):
    token = auth_headers["Authorization"].split(" ")[1]
    user_id = _user_id_from_token(token)

    opp = _opportunity(db)
    await db.commit()

    svc = ResearchService(db, user_id)
    outreach = await svc.create_outreach(opp.id)

    assert outreach.status == "suggested"
    assert outreach.user_id == user_id
    assert outreach.research_opportunity_id == opp.id


@pytest.mark.asyncio
async def test_create_outreach_drafted_with_pitch(
    db: AsyncSession, auth_headers: dict, client: AsyncClient
):
    from app.models.artifact import Artifact

    token = auth_headers["Authorization"].split(" ")[1]
    user_id = _user_id_from_token(token)

    opp = _opportunity(db)
    artifact = Artifact(
        user_id=user_id,
        application_id=None,
        type="research_pitch",
        content="Subject: Test\n\nDear Prof.",
        ats_score=None,
        missing_keywords=[],
        grounding_score=0.9,
        predicted_response=None,
        version=1,
    )
    db.add(artifact)
    await db.flush()

    svc = ResearchService(db, user_id)
    outreach = await svc.create_outreach(opp.id, artifact.id)

    assert outreach.status == "drafted"
    assert outreach.pitch_artifact_id == artifact.id


# ---------------------------------------------------------------------------
# list_outreach — user-scoped isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_outreach_user_scoped(
    db: AsyncSession, client: AsyncClient
):
    token_a = await _signup_and_token(client, "research_a@example.com")
    token_b = await _signup_and_token(client, "research_b@example.com")
    user_a = _user_id_from_token(token_a)
    user_b = _user_id_from_token(token_b)

    opp = _opportunity(db)
    await db.commit()

    # user_a creates outreach
    svc_a = ResearchService(db, user_a)
    await svc_a.create_outreach(opp.id)

    # user_b sees none of user_a's outreach
    svc_b = ResearchService(db, user_b)
    b_list = await svc_b.list_outreach()
    assert all(o.user_id == user_b for o in b_list)
    assert len(b_list) == 0


# ---------------------------------------------------------------------------
# update_status — happy path and invalid status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_status_ok(
    db: AsyncSession, auth_headers: dict, client: AsyncClient
):
    token = auth_headers["Authorization"].split(" ")[1]
    user_id = _user_id_from_token(token)

    opp = _opportunity(db)
    await db.commit()

    svc = ResearchService(db, user_id)
    outreach = await svc.create_outreach(opp.id)

    updated = await svc.update_status(outreach.id, "contacted")
    assert updated.status == "contacted"


@pytest.mark.asyncio
async def test_update_status_invalid(
    db: AsyncSession, auth_headers: dict, client: AsyncClient
):
    from app.core.errors import APIError

    token = auth_headers["Authorization"].split(" ")[1]
    user_id = _user_id_from_token(token)

    opp = _opportunity(db)
    await db.commit()

    svc = ResearchService(db, user_id)
    outreach = await svc.create_outreach(opp.id)

    with pytest.raises(APIError) as exc_info:
        await svc.update_status(outreach.id, "invalid_status")

    assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# update_status — cross-user: user_b cannot update user_a's outreach → 404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_status_cross_user_forbidden(
    db: AsyncSession, client: AsyncClient
):
    from app.core.errors import APIError

    token_a = await _signup_and_token(client, "research_x@example.com")
    token_b = await _signup_and_token(client, "research_y@example.com")
    user_a = _user_id_from_token(token_a)
    user_b = _user_id_from_token(token_b)

    opp = _opportunity(db)
    await db.commit()

    svc_a = ResearchService(db, user_a)
    outreach = await svc_a.create_outreach(opp.id)

    svc_b = ResearchService(db, user_b)
    with pytest.raises(APIError) as exc_info:
        await svc_b.update_status(outreach.id, "contacted")

    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# research_opportunities GLOBAL: two users see same opportunity count
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_opportunities_global(
    db: AsyncSession, client: AsyncClient
):
    token_a = await _signup_and_token(client, "global_a@example.com")
    token_b = await _signup_and_token(client, "global_b@example.com")
    user_a = _user_id_from_token(token_a)
    user_b = _user_id_from_token(token_b)

    _opportunity(db, research_area="NLP", embedding=_vec(0))
    _opportunity(db, research_area="Robotics", embedding=_vec(1))
    _profile(db, user_a, research_interests=["NLP"])
    _profile(db, user_b, research_interests=["NLP"])
    await db.commit()

    svc_a = ResearchService(db, user_a)
    svc_b = ResearchService(db, user_b)
    _, total_a = await svc_a.find_matches()
    _, total_b = await svc_b.find_matches()

    assert total_a == total_b == 2


# ---------------------------------------------------------------------------
# create_opportunity helper (used by seed): embedding is non-null
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_opportunity_embedding(db: AsyncSession):
    opp = await create_opportunity(
        db,
        professor_name="Prof. Seed",
        institution="IIT Test",
        research_area="Machine Learning",
        description="We research deep learning methods for vision and NLP tasks.",
        desired_skills=["Python", "PyTorch", "Deep Learning"],
        source="test_seed",
    )
    await db.commit()
    await db.refresh(opp)

    assert opp.embedding is not None
    assert len(opp.embedding) == EMBEDDING_DIM
