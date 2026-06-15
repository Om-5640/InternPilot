"""Module 9 — Interview Prep acceptance tests.

All LLM calls are mocked via patch("app.llm.extract.complete") so tests are deterministic and fast.
"""
from __future__ import annotations

import json
import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import Company
from app.models.posting import Posting
from app.models.profile import Profile
from app.models.user import User

PREP_URL = "/api/interview-prep"
SIGNUP_URL = "/api/auth/signup"

# ---------------------------------------------------------------------------
# Helpers — mock LLM response builders
# ---------------------------------------------------------------------------


def _q(
    q: str,
    qtype: str = "technical",
    category: str = "coding",
    difficulty: str = "medium",
    answer_guidance: str = "Think step by step.",
    ideal_answer_outline: str = "Outline key steps.",
) -> dict[str, Any]:
    return {
        "q": q,
        "type": qtype,
        "category": category,
        "difficulty": difficulty,
        "answer_guidance": answer_guidance,
        "ideal_answer_outline": ideal_answer_outline,
    }


def _make_prep_json(
    questions: list[dict[str, Any]],
    weak_spots: list[str] | None = None,
    reverse_questions: list[str] | None = None,
) -> str:
    return json.dumps({
        "questions": questions,
        "weak_spots": weak_spots or ["Needs deeper OS knowledge", "Limited system design exposure"],
        "reverse_questions": reverse_questions or [
            "What does a typical onboarding week look like?",
            "What are the biggest technical challenges the team faces?",
        ],
    })


# 10-question India company mock (includes 1 GD)
_INDIA_COMPANY_QUESTIONS = [
    _q("Find the two numbers in an array that sum to a target.", category="coding", difficulty="medium"),
    _q("Implement a LRU Cache.", category="coding", difficulty="hard"),
    _q("Explain the difference between process and thread.", category="cs_fundamentals", qtype="technical"),
    _q("What SQL query finds customers without orders?", category="cs_fundamentals", qtype="technical"),
    _q("Walk me through your project RealTimeChat.", category="project", qtype="technical"),
    _q("What was the hardest bug in RealTimeChat?", category="project", qtype="technical"),
    _q("Describe a time you resolved a team conflict. (STAR)", category="behavioral", qtype="behavioral"),
    _q("Tell me about yourself.", category="hr", qtype="behavioral"),
    _q("Social media has more negatives than positives — discuss.", category="gd", qtype="gd"),
    _q("Where do you see yourself in 5 years?", category="hr", qtype="behavioral"),
]

_INDIA_MOCK = _make_prep_json(_INDIA_COMPANY_QUESTIONS)

# 10-question US company mock (no GD)
_US_COMPANY_QUESTIONS = [
    _q("Given a binary tree, find its maximum depth.", category="coding", difficulty="easy"),
    _q("Design a URL shortener at scale.", category="coding", difficulty="hard"),
    _q("Explain ACID properties in databases.", category="cs_fundamentals", qtype="technical"),
    _q("How does virtual memory work?", category="cs_fundamentals", qtype="technical"),
    _q("Walk me through your project RealTimeChat.", category="project", qtype="technical"),
    _q("What trade-offs did you make choosing WebSockets for RealTimeChat?", category="project", qtype="technical"),
    _q("Tell me about a time you failed. (STAR)", category="behavioral", qtype="behavioral"),
    _q("Tell me about yourself.", category="hr", qtype="behavioral"),
    _q("Why do you want to work here?", category="behavioral", qtype="behavioral"),
    _q("Describe a time you resolved a conflict with a teammate.", category="behavioral", qtype="behavioral"),
]

_US_MOCK = _make_prep_json(_US_COMPANY_QUESTIONS)

# Service company mock (lighter coding)
_SERVICE_QUESTIONS = [
    _q("What is the difference between a stack and a queue?", category="coding", difficulty="easy"),
    _q("Write a function to reverse a string.", category="coding", difficulty="easy"),
    _q("Explain OOP principles with examples.", category="cs_fundamentals", qtype="technical"),
    _q("What is normalization in databases?", category="cs_fundamentals", qtype="technical"),
    _q("Walk me through your project RealTimeChat.", category="project", qtype="technical"),
    _q("What technologies did you use in RealTimeChat?", category="project", qtype="technical"),
    _q("Tell me about a challenging project.", category="behavioral", qtype="behavioral"),
    _q("Tell me about yourself.", category="hr", qtype="behavioral"),
    _q("What are your strengths and weaknesses?", category="hr", qtype="behavioral"),
    _q("Social media debate: tech benefits vs harm.", category="gd", qtype="gd"),
]

_SERVICE_MOCK = _make_prep_json(_SERVICE_QUESTIONS)

# Research mock (no coding, no GD; has research_fit, domain_depth, methods)
_RESEARCH_QUESTIONS = [
    _q("Why are you interested in NLP research and this lab specifically?", category="research_fit", qtype="technical"),
    _q("How does your experience align with our work on semantic parsing?", category="research_fit", qtype="technical"),
    _q("Explain transformer attention mechanisms.", category="domain_depth", qtype="technical"),
    _q("What are open problems in low-resource NLP?", category="domain_depth", qtype="technical"),
    _q("What evaluation metrics are used in dialogue systems?", category="domain_depth", qtype="technical"),
    _q("Describe your experience with fine-tuning language models.", category="methods", qtype="technical"),
    _q("How would you design a controlled experiment for comparing two NLP models?", category="methods", qtype="technical"),
    _q("Walk me through your project RealTimeChat and its relevance to NLP.", category="project", qtype="technical"),
    _q("What motivates you to pursue a research career?", category="behavioral", qtype="behavioral"),
    _q("Describe a time you had to learn a new concept independently.", category="behavioral", qtype="behavioral"),
]

_RESEARCH_MOCK = _make_prep_json(
    _RESEARCH_QUESTIONS,
    weak_spots=["Limited publication record", "No low-resource NLP experience"],
    reverse_questions=[
        "What papers are you currently working on that I could contribute to?",
        "How do PhD students collaborate with postdocs in your lab?",
    ],
)

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def _make_profile(
    db: AsyncSession,
    user_id: uuid.UUID,
    research_interests: list[str] | None = None,
) -> Profile:
    profile = Profile(
        user_id=user_id,
        skills=["Python", "WebSockets", "React", "PostgreSQL"],
        projects=[
            {"name": "RealTimeChat", "description": "Real-time chat with WebSockets", "tech": ["Python", "WebSockets", "React"]},
        ],
        experience=[
            {"title": "SWE Intern", "org": "TechCo", "description": "Built Python APIs"}
        ],
        education=[],
        headline="CS Student",
        research_interests=research_interests or [],
    )
    db.add(profile)
    await db.flush()
    return profile


async def _make_company(db: AsyncSession, name: str = "Acme") -> Company:
    import re
    norm = re.sub(r"[^a-z0-9]", "", name.lower())
    co = Company(
        name=name,
        normalized_name=norm,
        ghost_history_score=0.0,
        responsiveness_score=1.0,
    )
    db.add(co)
    await db.flush()
    return co


async def _make_posting(db: AsyncSession, company_id: uuid.UUID) -> Posting:
    p = Posting(
        company_id=company_id,
        title="SWE Intern",
        description="Build great things.",
        requirements=["Python"],
        work_mode="remote",
        source="greenhouse",
        source_url=f"https://acme.com/{uuid.uuid4().hex}",
        dedup_key=uuid.uuid4().hex[:16],
        posted_at="2026-01-01T00:00:00Z",
        last_seen_at="2026-01-01T00:00:00Z",
    )
    db.add(p)
    await db.flush()
    return p


# ---------------------------------------------------------------------------
# 1. COMPANY + India region → has GD question
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_company_india_has_gd_question(
    client: AsyncClient, auth_headers: dict, db: AsyncSession
) -> None:
    result = await db.execute(select(User).where(User.email == "test@example.com"))
    user = result.scalar_one()
    await _make_profile(db, user.id)
    await db.commit()

    with patch("app.llm.extract.complete", new=AsyncMock(return_value=_INDIA_MOCK)):
        resp = await client.post(
            PREP_URL,
            json={"company_name": "Infosys", "role": "SWE Intern", "region": "India campus"},
            headers=auth_headers,
        )

    assert resp.status_code == 201
    prep = resp.json()["prep"]
    categories = [q["category"] for q in prep["questions"]]
    assert "gd" in categories, f"Expected gd category, got: {categories}"


# ---------------------------------------------------------------------------
# 2. COMPANY + US/global region → NO GD question
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_company_us_no_gd_question(
    client: AsyncClient, auth_headers: dict, db: AsyncSession
) -> None:
    result = await db.execute(select(User).where(User.email == "test@example.com"))
    user = result.scalar_one()
    await _make_profile(db, user.id)
    await db.commit()

    with patch("app.llm.extract.complete", new=AsyncMock(return_value=_US_MOCK)):
        resp = await client.post(
            PREP_URL,
            json={"company_name": "Stripe", "role": "Backend Intern", "region": "San Francisco, CA"},
            headers=auth_headers,
        )

    assert resp.status_code == 201
    prep = resp.json()["prep"]
    categories = [q["category"] for q in prep["questions"]]
    assert "gd" not in categories, f"Unexpected gd in US prep: {categories}"


# ---------------------------------------------------------------------------
# 3a. Product company → harder coding mix
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_company_product_has_hard_coding(
    client: AsyncClient, auth_headers: dict, db: AsyncSession
) -> None:
    result = await db.execute(select(User).where(User.email == "test@example.com"))
    user = result.scalar_one()
    await _make_profile(db, user.id)
    await db.commit()

    with patch("app.llm.extract.complete", new=AsyncMock(return_value=_US_MOCK)):
        resp = await client.post(
            PREP_URL,
            json={"company_name": "Google", "role": "SWE Intern", "region": "US"},
            headers=auth_headers,
        )

    assert resp.status_code == 201
    prep = resp.json()["prep"]
    assert prep["company_type"] == "product"
    coding_qs = [q for q in prep["questions"] if q["category"] == "coding"]
    assert len(coding_qs) >= 1


# ---------------------------------------------------------------------------
# 3b. Service company → classified as service
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_company_service_classified_correctly(
    client: AsyncClient, auth_headers: dict, db: AsyncSession
) -> None:
    result = await db.execute(select(User).where(User.email == "test@example.com"))
    user = result.scalar_one()
    await _make_profile(db, user.id)
    await db.commit()

    with patch("app.llm.extract.complete", new=AsyncMock(return_value=_SERVICE_MOCK)):
        resp = await client.post(
            PREP_URL,
            json={"company_name": "Infosys", "role": "Associate SWE", "region": "India"},
            headers=auth_headers,
        )

    assert resp.status_code == 201
    prep = resp.json()["prep"]
    assert prep["company_type"] == "service"


# ---------------------------------------------------------------------------
# 4. RESEARCH type → right categories, no coding, no GD
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_research_type_has_correct_categories(
    client: AsyncClient, auth_headers: dict, db: AsyncSession
) -> None:
    result = await db.execute(select(User).where(User.email == "test@example.com"))
    user = result.scalar_one()
    await _make_profile(db, user.id, research_interests=["NLP", "machine learning"])
    await db.commit()

    with patch("app.llm.extract.complete", new=AsyncMock(return_value=_RESEARCH_MOCK)):
        resp = await client.post(
            PREP_URL,
            json={
                "company_name": "MIT NLP Lab",
                "role": "Research Assistant",
                "opportunity_type": "research",
                "research_area": "natural language processing",
            },
            headers=auth_headers,
        )

    assert resp.status_code == 201
    prep = resp.json()["prep"]
    assert prep["opportunity_type"] == "research"
    assert prep["company_type"] == "research_lab"

    categories = {q["category"] for q in prep["questions"]}
    assert "research_fit" in categories, f"Missing research_fit: {categories}"
    assert "domain_depth" in categories, f"Missing domain_depth: {categories}"
    assert "methods" in categories, f"Missing methods: {categories}"
    assert "coding" not in categories, f"Unexpected coding in research prep: {categories}"
    assert "gd" not in categories, f"Unexpected gd in research prep: {categories}"


# ---------------------------------------------------------------------------
# 5. PROJECT grounding — questions reference real profile project names
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_project_questions_reference_real_projects(
    client: AsyncClient, auth_headers: dict, db: AsyncSession
) -> None:
    result = await db.execute(select(User).where(User.email == "test@example.com"))
    user = result.scalar_one()
    await _make_profile(db, user.id)
    await db.commit()

    with patch("app.llm.extract.complete", new=AsyncMock(return_value=_US_MOCK)):
        resp = await client.post(
            PREP_URL,
            json={"company_name": "Stripe", "role": "Backend Intern", "region": "US"},
            headers=auth_headers,
        )

    assert resp.status_code == 201
    prep = resp.json()["prep"]
    project_qs = [q for q in prep["questions"] if q["category"] == "project"]
    real_project = "realtimechat"
    for pq in project_qs:
        text = (pq["q"] + " " + (pq.get("answer_guidance") or "")).lower()
        assert real_project in text, (
            f"Project question doesn't mention the real project: {pq['q']!r}"
        )


# ---------------------------------------------------------------------------
# 6. weak_spots present and non-empty
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_weak_spots_present(
    client: AsyncClient, auth_headers: dict, db: AsyncSession
) -> None:
    result = await db.execute(select(User).where(User.email == "test@example.com"))
    user = result.scalar_one()
    await _make_profile(db, user.id)
    await db.commit()

    with patch("app.llm.extract.complete", new=AsyncMock(return_value=_US_MOCK)):
        resp = await client.post(
            PREP_URL,
            json={"company_name": "Stripe", "role": "Backend Intern"},
            headers=auth_headers,
        )

    assert resp.status_code == 201
    prep = resp.json()["prep"]
    assert len(prep["weak_spots"]) >= 1


# ---------------------------------------------------------------------------
# 7. reverse_questions ≥ 2
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reverse_questions_at_least_two(
    client: AsyncClient, auth_headers: dict, db: AsyncSession
) -> None:
    result = await db.execute(select(User).where(User.email == "test@example.com"))
    user = result.scalar_one()
    await _make_profile(db, user.id)
    await db.commit()

    with patch("app.llm.extract.complete", new=AsyncMock(return_value=_US_MOCK)):
        resp = await client.post(
            PREP_URL,
            json={"company_name": "Stripe", "role": "Backend Intern"},
            headers=auth_headers,
        )

    assert resp.status_code == 201
    prep = resp.json()["prep"]
    assert len(prep["reverse_questions"]) >= 2


# ---------------------------------------------------------------------------
# 8. Question count and full schema on each item
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_question_count_and_schema(
    client: AsyncClient, auth_headers: dict, db: AsyncSession
) -> None:
    result = await db.execute(select(User).where(User.email == "test@example.com"))
    user = result.scalar_one()
    await _make_profile(db, user.id)
    await db.commit()

    with patch("app.llm.extract.complete", new=AsyncMock(return_value=_INDIA_MOCK)):
        resp = await client.post(
            PREP_URL,
            json={"company_name": "TCS", "role": "SWE", "region": "India"},
            headers=auth_headers,
        )

    assert resp.status_code == 201
    prep = resp.json()["prep"]
    qs = prep["questions"]
    assert 10 <= len(qs) <= 14, f"Expected 10-14 questions, got {len(qs)}"
    required_fields = {"q", "type", "category", "difficulty", "answer_guidance", "ideal_answer_outline"}
    for q in qs:
        assert required_fields.issubset(q.keys()), f"Question missing fields: {q.keys()}"


# ---------------------------------------------------------------------------
# 9. GET → own only; isolation; unknown → 404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_prep_own(
    client: AsyncClient, auth_headers: dict, db: AsyncSession
) -> None:
    result = await db.execute(select(User).where(User.email == "test@example.com"))
    user = result.scalar_one()
    await _make_profile(db, user.id)
    await db.commit()

    with patch("app.llm.extract.complete", new=AsyncMock(return_value=_US_MOCK)):
        create_resp = await client.post(
            PREP_URL,
            json={"company_name": "Stripe", "role": "Backend Intern"},
            headers=auth_headers,
        )
    assert create_resp.status_code == 201
    prep_id = create_resp.json()["prep"]["id"]

    get_resp = await client.get(f"{PREP_URL}/{prep_id}", headers=auth_headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["prep"]["id"] == prep_id


@pytest.mark.asyncio
async def test_get_prep_not_found(client: AsyncClient, auth_headers: dict) -> None:
    resp = await client.get(f"{PREP_URL}/{uuid.uuid4()}", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "PREP_NOT_FOUND"


@pytest.mark.asyncio
async def test_get_prep_isolation(
    client: AsyncClient, auth_headers: dict, db: AsyncSession
) -> None:
    result = await db.execute(select(User).where(User.email == "test@example.com"))
    user = result.scalar_one()
    await _make_profile(db, user.id)
    await db.commit()

    with patch("app.llm.extract.complete", new=AsyncMock(return_value=_US_MOCK)):
        create_resp = await client.post(
            PREP_URL,
            json={"company_name": "Stripe", "role": "Backend Intern"},
            headers=auth_headers,
        )
    prep_id = create_resp.json()["prep"]["id"]

    # User B cannot access User A's prep
    resp_b = await client.post(
        SIGNUP_URL,
        json={"name": "Eve Prep", "email": "eve.prep@example.com", "password": "pass1234"},
    )
    headers_b = {"Authorization": f"Bearer {resp_b.json()['token']}"}
    resp = await client.get(f"{PREP_URL}/{prep_id}", headers=headers_b)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 10. POST with valid application_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_prep_with_application_id(
    client: AsyncClient, auth_headers: dict, db: AsyncSession
) -> None:
    from app.models.application import Application

    result = await db.execute(select(User).where(User.email == "test@example.com"))
    user = result.scalar_one()
    await _make_profile(db, user.id)
    co = await _make_company(db)
    posting = await _make_posting(db, co.id)

    app_row = Application(
        user_id=user.id,
        posting_id=posting.id,
        channel="portal",
        status="applied",
        predicted_response_prob=0.5,
        predicted_ghost=False,
    )
    db.add(app_row)
    await db.commit()

    with patch("app.llm.extract.complete", new=AsyncMock(return_value=_US_MOCK)):
        resp = await client.post(
            PREP_URL,
            json={
                "application_id": str(app_row.id),
                "company_name": "Acme",
                "role": "SWE Intern",
            },
            headers=auth_headers,
        )

    assert resp.status_code == 201
    prep = resp.json()["prep"]
    assert prep["application_id"] == str(app_row.id)


# ---------------------------------------------------------------------------
# 11. POST with unknown application_id → 404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_prep_unknown_application_id(
    client: AsyncClient, auth_headers: dict, db: AsyncSession
) -> None:
    result = await db.execute(select(User).where(User.email == "test@example.com"))
    user = result.scalar_one()
    await _make_profile(db, user.id)
    await db.commit()

    with patch("app.llm.extract.complete", new=AsyncMock(return_value=_US_MOCK)):
        resp = await client.post(
            PREP_URL,
            json={
                "application_id": str(uuid.uuid4()),
                "company_name": "Acme",
                "role": "SWE Intern",
            },
            headers=auth_headers,
        )

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "APPLICATION_NOT_FOUND"


# ---------------------------------------------------------------------------
# 12. opportunity_type defaults to "company"
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_opportunity_type_defaults_to_company(
    client: AsyncClient, auth_headers: dict, db: AsyncSession
) -> None:
    result = await db.execute(select(User).where(User.email == "test@example.com"))
    user = result.scalar_one()
    await _make_profile(db, user.id)
    await db.commit()

    with patch("app.llm.extract.complete", new=AsyncMock(return_value=_US_MOCK)):
        resp = await client.post(
            PREP_URL,
            json={"company_name": "Notion", "role": "Backend Intern"},
            headers=auth_headers,
        )

    assert resp.status_code == 201
    assert resp.json()["prep"]["opportunity_type"] == "company"


# ---------------------------------------------------------------------------
# 13. Response schema has all required top-level fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_response_schema_fields(
    client: AsyncClient, auth_headers: dict, db: AsyncSession
) -> None:
    result = await db.execute(select(User).where(User.email == "test@example.com"))
    user = result.scalar_one()
    await _make_profile(db, user.id)
    await db.commit()

    with patch("app.llm.extract.complete", new=AsyncMock(return_value=_US_MOCK)):
        resp = await client.post(
            PREP_URL,
            json={"company_name": "Figma", "role": "Frontend Intern", "region": "US"},
            headers=auth_headers,
        )

    assert resp.status_code == 201
    prep = resp.json()["prep"]
    required = {
        "id", "user_id", "application_id", "company_name", "role",
        "opportunity_type", "region", "company_type",
        "questions", "weak_spots", "reverse_questions",
        "created_at", "updated_at",
    }
    assert required.issubset(prep.keys()), f"Missing fields: {required - prep.keys()}"
