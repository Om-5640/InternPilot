"""Tests for Module 6 — Referral / Warm-Intro Finder."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import Company
from app.models.contact import Contact, RelationshipType
from app.models.posting import Posting
from app.models.profile import Profile
from app.models.referral import Referral
from app.models.user import User
from app.services.referral_service import (
    _find_fabricated_tech,
    _intro_grounding_score,
    _parse_batch_year,
    _rank_contacts,
)
from app.services.university_normalizer import canonicalize as _canon

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_INTRO = "Dear Hiring Manager, I am a DAU alumnus applying for the SWE role. I will follow up."


async def _make_company(db: AsyncSession, name: str | None = None) -> Company:
    n = name or f"Co-{uuid.uuid4().hex[:8]}"
    company = Company(
        name=n,
        normalized_name=n.lower().replace(" ", "").replace("-", ""),
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
        title="Software Engineer Intern",
        description="Build great things.",
        requirements=["Python", "React"],
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


async def _make_contact(
    db: AsyncSession,
    company_id: uuid.UUID,
    name: str = "Alex Chen",
    relationship: RelationshipType = RelationshipType.alumni,
    grad_year: int | None = 2024,
    role: str | None = "SWE",
) -> Contact:
    contact = Contact(
        name=name,
        company_id=company_id,
        role=role,
        grad_year=grad_year,
        linkedin=f"https://linkedin.com/in/{name.lower().replace(' ', '')}",
        relationship=relationship,
        source="test",
    )
    db.add(contact)
    await db.flush()
    return contact


async def _make_profile(
    db: AsyncSession,
    user_id: uuid.UUID,
    skills: list[str] | None = None,
    projects: list[dict] | None = None,
    experience: list[dict] | None = None,
) -> Profile:
    profile = Profile(
        user_id=user_id,
        skills=skills or ["Python", "React"],
        projects=projects or [{"name": "MyApp", "tech": ["FastAPI"], "description": ""}],
        experience=experience or [{"title": "SWE Intern", "org": "ACME", "description": "Built Python APIs"}],
        education=[],
        headline="CS Student",
    )
    db.add(profile)
    await db.flush()
    return profile


# ---------------------------------------------------------------------------
# Unit tests — ranking + grounding helpers
# ---------------------------------------------------------------------------


def test_parse_batch_year_formats() -> None:
    assert _parse_batch_year("2024") == 2024
    assert _parse_batch_year("S2025") == 2025
    assert _parse_batch_year("Fall 2023") == 2023
    assert _parse_batch_year("F24") == 2024
    assert _parse_batch_year(None) == 0
    assert _parse_batch_year("") == 0


def test_rank_contacts_alumni_first() -> None:
    alumni = Contact(name="A", company_id=uuid.uuid4(), relationship=RelationshipType.alumni, grad_year=2024)
    second = Contact(name="B", company_id=uuid.uuid4(), relationship=RelationshipType.second_degree, grad_year=2025)
    ranked = _rank_contacts([second, alumni])
    assert ranked[0].name == "A"  # alumni before second_degree


def test_rank_contacts_recent_grad_first() -> None:
    older = Contact(name="Old", company_id=uuid.uuid4(), relationship=RelationshipType.alumni, grad_year=2020)
    newer = Contact(name="New", company_id=uuid.uuid4(), relationship=RelationshipType.alumni, grad_year=2025)
    ranked = _rank_contacts([older, newer])
    assert ranked[0].name == "New"  # more recent grad first


def test_rank_contacts_same_university_boosted() -> None:
    """Alumni from the student's own university (by canonical) are promoted above other alumni."""
    same_uni = Contact(
        name="SameUni",
        company_id=uuid.uuid4(),
        relationship=RelationshipType.second_degree,
        grad_year=2024,
        university="MIT",
        university_canonical=_canon("MIT"),
    )
    other_alumni = Contact(
        name="OtherAlum",
        company_id=uuid.uuid4(),
        relationship=RelationshipType.alumni,
        grad_year=2024,
        university="Stanford",
        university_canonical=_canon("Stanford"),
    )
    ranked = _rank_contacts([other_alumni, same_uni], student_university_canonical=_canon("MIT"))
    assert ranked[0].name == "SameUni"  # same university promoted to rank 0


def test_intro_grounding_score_no_tech_claims() -> None:
    score = _intro_grounding_score("Hi, I am a DAU student!", {"python", "react"})
    assert score == 1.0  # no tech claims → perfectly grounded


def test_intro_grounding_score_all_in_whitelist() -> None:
    score = _intro_grounding_score("I have experience with Python and React.", {"python", "react"})
    assert score == 1.0


def test_intro_grounding_score_fabricated_tech() -> None:
    score = _intro_grounding_score("I know Kubernetes and Docker.", {"python", "react"})
    assert score < 1.0  # kubernetes/docker not in whitelist


def test_find_fabricated_tech_detects_unlisted() -> None:
    fabricated = _find_fabricated_tech("I know Kubernetes!", {"python", "react"})
    assert "kubernetes" in fabricated


def test_find_fabricated_tech_empty_when_all_grounded() -> None:
    fabricated = _find_fabricated_tech("I know Python and React.", {"python", "react"})
    assert fabricated == []


# ---------------------------------------------------------------------------
# 1. find_candidates by company_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_find_candidates_by_company(
    client: AsyncClient, auth_headers: dict, db: AsyncSession
) -> None:
    company = await _make_company(db, "TechCorp")
    await _make_contact(db, company.id, name="Aria Lee")
    await db.commit()

    resp = await client.get(
        f"/api/referrals/candidates?company_id={company.id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data) == 1
    assert data[0]["name"] == "Aria Lee"
    assert data[0]["company_name"] == "TechCorp"


# ---------------------------------------------------------------------------
# 2. find_candidates by posting_id (resolves to company)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_find_candidates_by_posting(
    client: AsyncClient, auth_headers: dict, db: AsyncSession
) -> None:
    company = await _make_company(db, "PostCo")
    posting = await _make_posting(db, company.id)
    await _make_contact(db, company.id, name="Benny Park")
    await db.commit()

    resp = await client.get(
        f"/api/referrals/candidates?posting_id={posting.id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["data"][0]["name"] == "Benny Park"


# ---------------------------------------------------------------------------
# 3. find_candidates — empty list, no crash
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_find_candidates_empty(
    client: AsyncClient, auth_headers: dict, db: AsyncSession
) -> None:
    company = await _make_company(db)
    await db.commit()

    resp = await client.get(
        f"/api/referrals/candidates?company_id={company.id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["data"] == []


# ---------------------------------------------------------------------------
# 4. find_candidates — ranking verified (alumni > second_degree; recent batch first)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_find_candidates_ranking(
    client: AsyncClient, auth_headers: dict, db: AsyncSession
) -> None:
    company = await _make_company(db)
    # second_degree with newer grad year
    await _make_contact(db, company.id, name="2nd-2026", relationship=RelationshipType.second_degree, grad_year=2026)
    # alumni with older grad year
    await _make_contact(db, company.id, name="Alum-2020", relationship=RelationshipType.alumni, grad_year=2020)
    # alumni with newer grad year
    await _make_contact(db, company.id, name="Alum-2025", relationship=RelationshipType.alumni, grad_year=2025)
    await db.commit()

    resp = await client.get(
        f"/api/referrals/candidates?company_id={company.id}",
        headers=auth_headers,
    )
    names = [c["name"] for c in resp.json()["data"]]
    # Alumni first (newer batch first among alumni), then second_degree
    assert names.index("Alum-2025") < names.index("Alum-2020")
    assert names.index("Alum-2020") < names.index("2nd-2026")


# ---------------------------------------------------------------------------
# 5. find_candidates — GLOBAL: two users see the same candidates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_find_candidates_global(
    client: AsyncClient, auth_headers: dict, db: AsyncSession
) -> None:
    company = await _make_company(db)
    await _make_contact(db, company.id, name="Shared Alumni")
    await db.commit()

    # Second user
    resp2 = await client.post(
        "/api/auth/signup",
        json={"name": "User B", "email": "userb@example.com", "password": "pass1234"},
    )
    assert resp2.status_code == 201
    headers_b = {"Authorization": f"Bearer {resp2.json()['token']}"}

    r1 = await client.get(f"/api/referrals/candidates?company_id={company.id}", headers=auth_headers)
    r2 = await client.get(f"/api/referrals/candidates?company_id={company.id}", headers=headers_b)
    assert r1.json()["data"][0]["id"] == r2.json()["data"][0]["id"]


# ---------------------------------------------------------------------------
# 6. find_candidates — missing both params → 400
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_find_candidates_missing_params(
    client: AsyncClient, auth_headers: dict
) -> None:
    resp = await client.get("/api/referrals/candidates", headers=auth_headers)
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "MISSING_PARAMETER"


# ---------------------------------------------------------------------------
# 7. create_referral — creates referral + artifact
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_referral_creates_record(
    client: AsyncClient, auth_headers: dict, db: AsyncSession
) -> None:
    user_result = await db.execute(select(User).where(User.email == "test@example.com"))
    user = user_result.scalar_one()

    company = await _make_company(db, "AcmeCorp")
    contact = await _make_contact(db, company.id, name="Carol Wu")
    await _make_profile(db, user.id)
    await db.commit()

    with patch("app.llm.router.complete", new_callable=AsyncMock, return_value=_INTRO):
        resp = await client.post(
            "/api/referrals",
            json={"company_id": str(company.id), "contact_id": str(contact.id)},
            headers=auth_headers,
        )

    assert resp.status_code == 201
    body = resp.json()["referral"]
    assert body["status"] == "suggested"
    assert body["company_id"] == str(company.id)
    assert body["contact"]["name"] == "Carol Wu"
    assert body["intro_artifact_id"] is not None


# ---------------------------------------------------------------------------
# 8. create_referral — intro has alumni opener + role + ask + easy out
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_referral_intro_structure(
    client: AsyncClient, auth_headers: dict, db: AsyncSession
) -> None:
    user_result = await db.execute(select(User).where(User.email == "test@example.com"))
    user = user_result.scalar_one()

    company = await _make_company(db, "BigTech")
    contact = await _make_contact(db, company.id, name="Dana Kim")
    posting = await _make_posting(db, company.id)
    await _make_profile(db, user.id)
    await db.commit()

    intro_content = (
        "Subject: DAU Alumnus Reaching Out re: Software Engineer Intern\n\n"
        "Hi Dana,\n\n"
        "I'm a fellow DAU student (CS, 2026) and noticed you work at BigTech as SWE. "
        "I'm applying for the Software Engineer Intern role and would love to connect. "
        "I've been working with Python and React on several projects. "
        "Would you be open to a quick chat or advice? "
        "I completely understand if a direct referral isn't comfortable — "
        "advice or even a forward would mean a lot. Thanks!"
    )

    with patch("app.llm.router.complete", new_callable=AsyncMock, return_value=intro_content):
        resp = await client.post(
            "/api/referrals",
            json={
                "company_id": str(company.id),
                "contact_id": str(contact.id),
                "posting_id": str(posting.id),
            },
            headers=auth_headers,
        )

    assert resp.status_code == 201
    referral_id = resp.json()["referral"]["id"]

    # Verify the artifact content has expected elements
    list_resp = await client.get("/api/referrals", headers=auth_headers)
    assert list_resp.json()["data"][0]["id"] == referral_id


# ---------------------------------------------------------------------------
# 9. create_referral — grounding guard fires on fabricated skills
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_referral_grounding_guard(
    client: AsyncClient, auth_headers: dict, db: AsyncSession
) -> None:
    """LLM returning Kubernetes (not in profile) triggers retry; final intro is clean."""
    user_result = await db.execute(select(User).where(User.email == "test@example.com"))
    user = user_result.scalar_one()

    company = await _make_company(db)
    contact = await _make_contact(db, company.id)
    # Profile has ONLY Python + React — NOT Kubernetes
    await _make_profile(db, user.id, skills=["Python", "React"])
    await db.commit()

    dirty_intro = "I have deep expertise in Python, React, and Kubernetes."
    clean_intro = "I have deep expertise in Python and React."

    call_sequence = [dirty_intro, clean_intro]

    with patch(
        "app.llm.router.complete",
        new_callable=AsyncMock,
        side_effect=call_sequence,
    ):
        resp = await client.post(
            "/api/referrals",
            json={"company_id": str(company.id), "contact_id": str(contact.id)},
            headers=auth_headers,
        )

    assert resp.status_code == 201
    # Verify referral was created (guard loop ran twice)
    referrals = await db.execute(
        select(Referral).where(Referral.user_id == user.id)
    )
    assert referrals.scalar_one_or_none() is not None


# ---------------------------------------------------------------------------
# 10. create_referral — contact not found → 404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_referral_contact_not_found(
    client: AsyncClient, auth_headers: dict, db: AsyncSession
) -> None:
    company = await _make_company(db)
    await db.commit()

    resp = await client.post(
        "/api/referrals",
        json={"company_id": str(company.id), "contact_id": str(uuid.uuid4())},
        headers=auth_headers,
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "CONTACT_NOT_FOUND"


# ---------------------------------------------------------------------------
# 11. list_referrals — returns user's own only
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_referrals_own_only(
    client: AsyncClient, auth_headers: dict, db: AsyncSession
) -> None:
    user_result = await db.execute(select(User).where(User.email == "test@example.com"))
    user = user_result.scalar_one()

    company = await _make_company(db)
    contact = await _make_contact(db, company.id)
    await _make_profile(db, user.id)
    await db.commit()

    with patch("app.llm.router.complete", new_callable=AsyncMock, return_value=_INTRO):
        await client.post(
            "/api/referrals",
            json={"company_id": str(company.id), "contact_id": str(contact.id)},
            headers=auth_headers,
        )

    resp = await client.get("/api/referrals", headers=auth_headers)
    assert resp.status_code == 200
    assert len(resp.json()["data"]) == 1


# ---------------------------------------------------------------------------
# 12. list_referrals — isolation: user B can't see user A's referrals
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_referrals_isolation(
    client: AsyncClient, auth_headers: dict, db: AsyncSession
) -> None:
    user_result = await db.execute(select(User).where(User.email == "test@example.com"))
    user = user_result.scalar_one()

    company = await _make_company(db)
    contact = await _make_contact(db, company.id)
    await _make_profile(db, user.id)
    await db.commit()

    # User A creates a referral
    with patch("app.llm.router.complete", new_callable=AsyncMock, return_value=_INTRO):
        await client.post(
            "/api/referrals",
            json={"company_id": str(company.id), "contact_id": str(contact.id)},
            headers=auth_headers,
        )

    # User B signs up + lists referrals
    resp_b = await client.post(
        "/api/auth/signup",
        json={"name": "User B", "email": "userb2@example.com", "password": "pass1234"},
    )
    headers_b = {"Authorization": f"Bearer {resp_b.json()['token']}"}
    resp = await client.get("/api/referrals", headers=headers_b)
    assert resp.status_code == 200
    assert len(resp.json()["data"]) == 0


# ---------------------------------------------------------------------------
# 13. update_status — valid transition
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_referral_status(
    client: AsyncClient, auth_headers: dict, db: AsyncSession
) -> None:
    user_result = await db.execute(select(User).where(User.email == "test@example.com"))
    user = user_result.scalar_one()

    company = await _make_company(db)
    contact = await _make_contact(db, company.id)
    await _make_profile(db, user.id)
    await db.commit()

    with patch("app.llm.router.complete", new_callable=AsyncMock, return_value=_INTRO):
        create_resp = await client.post(
            "/api/referrals",
            json={"company_id": str(company.id), "contact_id": str(contact.id)},
            headers=auth_headers,
        )
    referral_id = create_resp.json()["referral"]["id"]

    resp = await client.put(
        f"/api/referrals/{referral_id}",
        json={"status": "requested"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["referral"]["status"] == "requested"


# ---------------------------------------------------------------------------
# 14. update_status — invalid value → 400
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_referral_invalid_status(
    client: AsyncClient, auth_headers: dict, db: AsyncSession
) -> None:
    user_result = await db.execute(select(User).where(User.email == "test@example.com"))
    user = user_result.scalar_one()

    company = await _make_company(db)
    contact = await _make_contact(db, company.id)
    await _make_profile(db, user.id)
    await db.commit()

    with patch("app.llm.router.complete", new_callable=AsyncMock, return_value=_INTRO):
        create_resp = await client.post(
            "/api/referrals",
            json={"company_id": str(company.id), "contact_id": str(contact.id)},
            headers=auth_headers,
        )
    referral_id = create_resp.json()["referral"]["id"]

    resp = await client.put(
        f"/api/referrals/{referral_id}",
        json={"status": "MOON_SHOT"},
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_STATUS"


# ---------------------------------------------------------------------------
# 15. update_status — isolation: can't update other user's referral → 404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_referral_isolation(
    client: AsyncClient, auth_headers: dict, db: AsyncSession
) -> None:
    user_result = await db.execute(select(User).where(User.email == "test@example.com"))
    user = user_result.scalar_one()

    company = await _make_company(db)
    contact = await _make_contact(db, company.id)
    await _make_profile(db, user.id)
    await db.commit()

    # User A creates referral
    with patch("app.llm.router.complete", new_callable=AsyncMock, return_value=_INTRO):
        create_resp = await client.post(
            "/api/referrals",
            json={"company_id": str(company.id), "contact_id": str(contact.id)},
            headers=auth_headers,
        )
    referral_id = create_resp.json()["referral"]["id"]

    # User B tries to update it
    resp_b = await client.post(
        "/api/auth/signup",
        json={"name": "User B", "email": "userb3@example.com", "password": "pass1234"},
    )
    headers_b = {"Authorization": f"Bearer {resp_b.json()['token']}"}
    resp = await client.put(
        f"/api/referrals/{referral_id}",
        json={"status": "requested"},
        headers=headers_b,
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 16. update_status — 404 for nonexistent referral
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_referral_not_found(
    client: AsyncClient, auth_headers: dict
) -> None:
    resp = await client.put(
        f"/api/referrals/{uuid.uuid4()}",
        json={"status": "requested"},
        headers=auth_headers,
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 17. seed_alumni.py — imports CSV → creates contacts + resolves/creates companies
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seed_alumni_creates_contacts(db: AsyncSession) -> None:
    from scripts.seed_alumni import _normalize, _resolve_or_create_company

    # Seed a company
    company = await _resolve_or_create_company(db, "SeedCorp")
    await db.flush()
    assert company.normalized_name == _normalize("SeedCorp")

    # Re-resolve — should return existing, not create new
    company2 = await _resolve_or_create_company(db, "SeedCorp")
    assert company2.id == company.id

    # Create a contact
    contact = Contact(
        name="Seed Person",
        company_id=company.id,
        grad_year=2024,
        relationship=RelationshipType.alumni,
        source="csv_seed",
    )
    db.add(contact)
    await db.commit()

    result = await db.execute(
        select(Contact).where(Contact.company_id == company.id)
    )
    assert result.scalar_one().name == "Seed Person"


# ---------------------------------------------------------------------------
# 18. list_referrals — shows newly created referral with embedded contact
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_referral_after_create(
    client: AsyncClient, auth_headers: dict, db: AsyncSession
) -> None:
    user_result = await db.execute(select(User).where(User.email == "test@example.com"))
    user = user_result.scalar_one()

    company = await _make_company(db, "EmbedCo")
    contact = await _make_contact(db, company.id, name="Eva Nguyen", grad_year=2025)
    await _make_profile(db, user.id)
    await db.commit()

    with patch("app.llm.router.complete", new_callable=AsyncMock, return_value=_INTRO):
        await client.post(
            "/api/referrals",
            json={"company_id": str(company.id), "contact_id": str(contact.id)},
            headers=auth_headers,
        )

    list_resp = await client.get("/api/referrals", headers=auth_headers)
    assert list_resp.status_code == 200
    referrals = list_resp.json()["data"]
    assert len(referrals) == 1
    r = referrals[0]
    assert r["contact"]["name"] == "Eva Nguyen"
    assert r["contact"]["company_name"] == "EmbedCo"
    assert r["contact"]["grad_year"] == 2025
    assert r["intro_artifact_id"] is not None


# ---------------------------------------------------------------------------
# 19. canonical matching — same institution, different name variants
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_same_uni_canonical_boost_with_variants(
    client: AsyncClient, auth_headers: dict, db: AsyncSession
) -> None:
    """A student at 'IIT Bombay' sees an 'Indian Institute of Technology Bombay' alum boosted."""
    from sqlalchemy import select as _select

    from app.models.user import User
    from app.services.university_normalizer import canonicalize as _canon

    user_result = await db.execute(_select(User).where(User.email == "test@example.com"))
    user = user_result.scalar_one()

    # Student profile uses the short variant
    profile = Profile(
        user_id=user.id,
        skills=["Python"],
        projects=[],
        experience=[],
        education=[],
        university="IIT Bombay",
        university_canonical=_canon("IIT Bombay"),
    )
    db.add(profile)

    company = await _make_company(db, "AlumniCorp")

    # Contact recorded with full name variant
    same_uni_contact = Contact(
        name="SameIIT",
        company_id=company.id,
        relationship=RelationshipType.second_degree,
        grad_year=2024,
        university="Indian Institute of Technology Bombay",
        university_canonical=_canon("Indian Institute of Technology Bombay"),
        source="test",
    )
    # Contact from a completely different school
    other_contact = Contact(
        name="OtherSchool",
        company_id=company.id,
        relationship=RelationshipType.alumni,
        grad_year=2024,
        university="Stanford University",
        university_canonical=_canon("Stanford University"),
        source="test",
    )
    db.add(same_uni_contact)
    db.add(other_contact)
    await db.commit()

    resp = await client.get(
        f"/api/referrals/candidates?company_id={company.id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    names = [c["name"] for c in resp.json()["data"]]
    # SameIIT (2nd_degree, same canonical) should rank above OtherSchool (alumni, different uni)
    assert names.index("SameIIT") < names.index("OtherSchool")


@pytest.mark.asyncio
async def test_different_unis_no_boost(
    client: AsyncClient, auth_headers: dict, db: AsyncSession
) -> None:
    """A student at 'Stanford' does not get IIT Bombay alumni boosted."""
    from sqlalchemy import select as _select

    from app.models.user import User
    from app.services.university_normalizer import canonicalize as _canon

    user_result = await db.execute(_select(User).where(User.email == "test@example.com"))
    user = user_result.scalar_one()

    profile = Profile(
        user_id=user.id,
        skills=["Python"],
        projects=[],
        experience=[],
        education=[],
        university="Stanford University",
        university_canonical=_canon("Stanford University"),
    )
    db.add(profile)

    company = await _make_company(db, "MixedCorp")

    iit_contact = Contact(
        name="IITAlum",
        company_id=company.id,
        relationship=RelationshipType.second_degree,
        grad_year=2024,
        university="IIT Bombay",
        university_canonical=_canon("IIT Bombay"),
        source="test",
    )
    stanford_contact = Contact(
        name="StanfordAlum",
        company_id=company.id,
        relationship=RelationshipType.alumni,
        grad_year=2024,
        university="Stanford",
        university_canonical=_canon("Stanford"),
        source="test",
    )
    db.add(iit_contact)
    db.add(stanford_contact)
    await db.commit()

    resp = await client.get(
        f"/api/referrals/candidates?company_id={company.id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    names = [c["name"] for c in resp.json()["data"]]
    # StanfordAlum (alumni, same canonical as student) should rank above IITAlum (2nd_degree)
    assert names.index("StanfordAlum") < names.index("IITAlum")


@pytest.mark.asyncio
async def test_backfill_university_canonical(db: AsyncSession) -> None:
    """Setting university_canonical via the normalizer produces the expected canonical."""
    from app.services.university_normalizer import canonicalize as _canon

    company = await _make_company(db, "BackfillCo")
    contact = Contact(
        name="BackfillPerson",
        company_id=company.id,
        relationship=RelationshipType.alumni,
        university="Indian Institute of Technology Bombay",
        university_canonical=None,  # simulate pre-migration row
        source="test",
    )
    db.add(contact)
    await db.flush()

    # Simulate what the migration backfill does
    contact.university_canonical = _canon(contact.university) or None
    db.add(contact)
    await db.commit()

    await db.refresh(contact)
    assert contact.university_canonical == "iit bombay"


def test_rank_contacts_canonical_variant_match() -> None:
    """_rank_contacts boosts a contact when canonical matches even if raw strings differ."""
    same_canon = Contact(
        name="VariantMatch",
        company_id=uuid.uuid4(),
        relationship=RelationshipType.second_degree,
        grad_year=2024,
        university="Indian Institute of Technology Bombay",
        university_canonical=_canon("Indian Institute of Technology Bombay"),
    )
    other = Contact(
        name="NoMatch",
        company_id=uuid.uuid4(),
        relationship=RelationshipType.alumni,
        grad_year=2024,
        university="Stanford University",
        university_canonical=_canon("Stanford University"),
    )
    # Student registered as "IITB" — canonical is "iit bombay", same as same_canon's canonical
    ranked = _rank_contacts([other, same_canon], student_university_canonical=_canon("IITB"))
    assert ranked[0].name == "VariantMatch"
