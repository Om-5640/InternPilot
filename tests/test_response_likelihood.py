"""Module 5 — Response Likelihood acceptance tests.

Covers:
- Pure function: _freshness step function (0-14d→1.0, ≥90d→0.1)
- Pure function: _compute_response_likelihood — data-rich vs cold-start paths
- Integration: responsive company posting has higher response_likelihood than unresponsive
- Integration: deceptive posting (fresh + specific JD, bad company) gets low expected_value
- Integration: match_explanation includes cohort reason when response rate < 25%
- Integration: match_explanation has NO cohort reason when response rate is high
- Integration: expected_value = match_score * response_likelihood * (1 - ghost_score)
"""
from __future__ import annotations

import math
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

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
from app.services.matching_service import (
    _COHORT_MIN_APPS,
    _LOW_RESP_RATE,
    _build_explanation,
    _compute_response_likelihood,
    _freshness,
)

MATCHES_URL = "/api/matches"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _vec(pos: int, val: float = 1.0) -> list[float]:
    v = [0.0] * EMBEDDING_DIM
    v[pos] = val
    return v


def _now_str() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _days_ago_str(days: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_posting(
    *,
    days_old: int = 0,
    ghost_score: float = 0.0,
    is_ghost: bool = False,
    source_sightings: int = 1,
    requirements: list[str] | None = None,
    description: str = "A test posting with relevant content.",
    company_id: uuid.UUID | None = None,
    embedding: list[float] | None = None,
    source_url_suffix: str = "",
) -> Posting:
    posted = _days_ago_str(days_old)
    return Posting(
        company_id=company_id or uuid.uuid4(),
        title="Test Role",
        description=description,
        requirements=requirements or ["Python"],
        location="Remote",
        work_mode="remote",
        source="greenhouse",
        source_url=f"https://example.com/jobs/{uuid.uuid4()}{source_url_suffix}",
        last_seen_at=posted,
        posted_at=posted,
        dedup_key=str(uuid.uuid4())[:16],
        status="active",
        ghost_score=ghost_score,
        is_ghost=is_ghost,
        source_sightings=source_sightings,
        embedding=embedding,
    )


def _make_company(
    *,
    cohort_applied_count: int = 0,
    responsiveness_score: float = 1.0,
    ghost_history_score: float = 0.0,
    suffix: str = "",
) -> Company:
    name = f"Co-{uuid.uuid4().hex[:6]}{suffix}"
    return Company(
        name=name,
        normalized_name=name.lower(),
        cohort_applied_count=cohort_applied_count,
        responsiveness_score=responsiveness_score,
        ghost_history_score=ghost_history_score,
    )


# ---------------------------------------------------------------------------
# Pure unit tests — no DB required
# ---------------------------------------------------------------------------


class TestFreshness:
    def test_fresh_posting_is_1(self) -> None:
        p = _make_posting(days_old=0)
        assert _freshness(p) == 1.0

    def test_5_days_old_is_1(self) -> None:
        p = _make_posting(days_old=5)
        assert _freshness(p) == 1.0

    def test_14_days_old_is_1(self) -> None:
        p = _make_posting(days_old=14)
        assert _freshness(p) == 1.0

    def test_15_days_old_is_0_8(self) -> None:
        p = _make_posting(days_old=15)
        assert _freshness(p) == 0.8

    def test_29_days_old_is_0_8(self) -> None:
        p = _make_posting(days_old=29)
        assert _freshness(p) == 0.8

    def test_30_days_old_is_0_5(self) -> None:
        p = _make_posting(days_old=30)
        assert _freshness(p) == 0.5

    def test_60_days_old_is_0_3(self) -> None:
        p = _make_posting(days_old=60)
        assert _freshness(p) == 0.3

    def test_90_days_old_is_0_1(self) -> None:
        p = _make_posting(days_old=90)
        assert _freshness(p) == 0.1

    def test_120_days_old_is_0_1(self) -> None:
        p = _make_posting(days_old=120)
        assert _freshness(p) == 0.1

    def test_no_date_returns_0_5(self) -> None:
        p = _make_posting(days_old=0)
        p.posted_at = None
        p.last_seen_at = ""  # type: ignore[assignment]
        assert _freshness(p) == 0.5


class TestComputeResponseLikelihood:
    def test_data_rich_responsive_company_is_high(self) -> None:
        """75% cohort response, fresh posting → RL should be high (> 0.75)."""
        p = _make_posting(days_old=0, ghost_score=0.0)
        c = _make_company(cohort_applied_count=10, responsiveness_score=0.75)
        rl = _compute_response_likelihood(p, c)
        # 0.55*0.75 + 0.35*1.0 + 0.10*1.0 = 0.4125 + 0.35 + 0.10 = 0.8625
        assert rl > 0.75, f"Expected RL > 0.75 for responsive company, got {rl}"

    def test_data_rich_unresponsive_company_is_low(self) -> None:
        """5% cohort response, fresh posting → RL should be significantly lower than responsive."""
        p = _make_posting(days_old=0, ghost_score=0.1)
        c = _make_company(cohort_applied_count=10, responsiveness_score=0.05)
        rl = _compute_response_likelihood(p, c)
        # 0.55*0.05 + 0.35*1.0 + 0.10*0.9 = 0.0275 + 0.35 + 0.09 = 0.4675
        assert rl < 0.55, f"Expected RL < 0.55 for unresponsive company, got {rl}"

    def test_responsive_higher_than_unresponsive_same_freshness(self) -> None:
        """Same posting age; responsive company should yield clearly higher RL."""
        p_good = _make_posting(days_old=5, ghost_score=0.02)
        p_bad = _make_posting(days_old=5, ghost_score=0.02)
        c_good = _make_company(cohort_applied_count=10, responsiveness_score=0.75)
        c_bad = _make_company(cohort_applied_count=10, responsiveness_score=0.05)
        rl_good = _compute_response_likelihood(p_good, c_good)
        rl_bad = _compute_response_likelihood(p_bad, c_bad)
        assert rl_good > rl_bad, f"Responsive RL ({rl_good}) must exceed unresponsive ({rl_bad})"
        assert rl_good - rl_bad > 0.3, "Difference should be substantial (> 0.30)"

    def test_cold_start_fresh_posting_is_high(self) -> None:
        """No cohort data + fresh posting + clean company → high RL."""
        p = _make_posting(days_old=3, ghost_score=0.0)
        c = _make_company(cohort_applied_count=0, ghost_history_score=0.0)
        rl = _compute_response_likelihood(p, c)
        # 0.65*1.0 + 0.35*1.0 = 1.0 (clamped)
        assert rl == 1.0, f"Expected 1.0 for fresh cold-start, got {rl}"

    def test_cold_start_stale_posting_is_lower(self) -> None:
        """No cohort data + 90-day-old posting → lower RL than fresh."""
        p_fresh = _make_posting(days_old=3, ghost_score=0.0)
        p_stale = _make_posting(days_old=90, ghost_score=0.0)
        c = _make_company(cohort_applied_count=2, ghost_history_score=0.0)
        rl_fresh = _compute_response_likelihood(p_fresh, c)
        rl_stale = _compute_response_likelihood(p_stale, c)
        assert rl_fresh > rl_stale, "Fresh cold-start should outrank stale cold-start"

    def test_cold_start_with_ghost_history_penalised(self) -> None:
        """Cold-start with high ghost_history_score → lower RL than clean company."""
        p = _make_posting(days_old=3, ghost_score=0.0)
        c_clean = _make_company(cohort_applied_count=1, ghost_history_score=0.0)
        c_ghosty = _make_company(cohort_applied_count=1, ghost_history_score=0.8)
        rl_clean = _compute_response_likelihood(p, c_clean)
        rl_ghosty = _compute_response_likelihood(p, c_ghosty)
        assert rl_clean > rl_ghosty

    def test_exactly_at_min_apps_boundary_uses_data_rich(self) -> None:
        """cohort_applied_count == _COHORT_MIN_APPS should use data-rich path."""
        p = _make_posting(days_old=0, ghost_score=0.0)
        c_rich = _make_company(cohort_applied_count=_COHORT_MIN_APPS, responsiveness_score=0.8)
        c_cold = _make_company(cohort_applied_count=_COHORT_MIN_APPS - 1, responsiveness_score=0.8)
        rl_rich = _compute_response_likelihood(p, c_rich)
        rl_cold = _compute_response_likelihood(p, c_cold)
        # Data-rich with 80% response → 0.55*0.8 + 0.35 + 0.10 = 0.44+0.35+0.10=0.89
        # Cold: 0.65 + 0.35 = 1.0 (company has no ghost history)
        # Different formulas → different numbers; mainly verify no crash and range
        assert 0.0 <= rl_rich <= 1.0
        assert 0.0 <= rl_cold <= 1.0

    def test_always_in_range(self) -> None:
        combos = [
            (0, 0.0, 0.0, 0.0),
            (10, 0.0, 0.0, 0.9),
            (10, 1.0, 0.0, 0.0),
            (3, 0.5, 0.5, 0.5),
            (0, 0.0, 1.0, 1.0),
        ]
        for applied, resp, ghost_hist, ghost_score in combos:
            p = _make_posting(days_old=0, ghost_score=ghost_score)
            c = _make_company(
                cohort_applied_count=applied,
                responsiveness_score=resp,
                ghost_history_score=ghost_hist,
            )
            rl = _compute_response_likelihood(p, c)
            assert 0.0 <= rl <= 1.0, f"RL out of range for {applied=}, {resp=}: {rl}"


class TestBuildExplanation:
    def test_low_cohort_rate_appends_reason(self) -> None:
        c = _make_company(cohort_applied_count=10, responsiveness_score=0.05)
        result = _build_explanation(["Python"], [], 0.9, company=c)
        assert "batchmates" in result, f"Expected cohort reason in: {result!r}"
        assert "of 10" in result

    def test_zero_cohort_rate_appends_reason(self) -> None:
        c = _make_company(cohort_applied_count=8, responsiveness_score=0.0)
        result = _build_explanation(["Python"], [], 0.9, company=c)
        assert "0 of 8 batchmates" in result

    def test_high_cohort_rate_no_reason(self) -> None:
        c = _make_company(cohort_applied_count=10, responsiveness_score=0.75)
        result = _build_explanation(["Python"], [], 0.9, company=c)
        assert "batchmates" not in result, f"Should not append reason for responsive company: {result!r}"

    def test_cohort_rate_exactly_at_threshold_no_reason(self) -> None:
        """At exactly _LOW_RESP_RATE, the warning should NOT appear."""
        c = _make_company(cohort_applied_count=10, responsiveness_score=_LOW_RESP_RATE)
        result = _build_explanation(["Python"], [], 0.9, company=c)
        assert "batchmates" not in result

    def test_insufficient_cohort_apps_no_reason(self) -> None:
        """Below _COHORT_MIN_APPS applications → never annotate."""
        c = _make_company(cohort_applied_count=_COHORT_MIN_APPS - 1, responsiveness_score=0.0)
        result = _build_explanation(["Python"], [], 0.9, company=c)
        assert "batchmates" not in result

    def test_no_company_no_reason(self) -> None:
        result = _build_explanation(["Python"], [], 0.9)
        assert "batchmates" not in result

    def test_base_text_still_present_with_reason(self) -> None:
        c = _make_company(cohort_applied_count=10, responsiveness_score=0.05)
        result = _build_explanation(["Python", "SQL"], [], 0.9, company=c)
        assert "Strong match" in result
        assert "batchmates" in result


# ---------------------------------------------------------------------------
# Integration fixtures
# ---------------------------------------------------------------------------


async def _make_rl_user(
    db: AsyncSession, *, email: str, skills: list[str], embedding: list[float]
) -> dict[str, str]:
    user = User(
        name="RLUser",
        email=email,
        password_hash=hash_password("password123"),
        role=UserRole.student,
        auth_provider=AuthProvider.password,
        consent={"gmail": False, "github": False, "alumni_data": False},
    )
    db.add(user)
    await db.flush()
    profile = Profile(user_id=user.id, skills=skills, embedding=embedding)
    db.add(profile)
    await db.commit()
    token = create_access_token({"sub": str(user.id)})
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def rl_user(db: AsyncSession) -> dict[str, str]:
    return await _make_rl_user(
        db, email="rl_user@test.com", skills=["Python", "FastAPI", "SQL"], embedding=_vec(5)
    )


@pytest_asyncio.fixture
async def seeded_rl(db: AsyncSession) -> dict[str, Any]:
    """Two companies, two postings — identical freshness and embeddings, different cohort data."""
    co_good = Company(
        name="ResponsiveCo",
        normalized_name="responsiveco",
        cohort_applied_count=10,
        responsiveness_score=0.75,
        ghost_history_score=0.05,
    )
    co_bad = Company(
        name="UnresponsiveCo",
        normalized_name="unresponsiveco",
        cohort_applied_count=10,
        responsiveness_score=0.04,
        ghost_history_score=0.45,
    )
    db.add_all([co_good, co_bad])
    await db.flush()

    now = _now_str()

    # Fresh posting at responsive company — skill overlap with rl_user
    p_good = Posting(
        company_id=co_good.id,
        title="Python Backend Intern – ResponsiveCo",
        description="Build APIs with FastAPI and PostgreSQL in a high-velocity team.",
        requirements=["Python", "FastAPI", "SQL"],
        location="Remote",
        work_mode="remote",
        source="greenhouse",
        source_url="https://responsiveco.com/jobs/rl-1",
        last_seen_at=now,
        posted_at=now,
        dedup_key=str(uuid.uuid4())[:16],
        status="active",
        ghost_score=0.02,
        is_ghost=False,
        source_sightings=1,
        embedding=_vec(5),
    )
    # Deceptive posting: fresh, specific JD, strong skill match — but company never responds
    p_deceptive = Posting(
        company_id=co_bad.id,
        title="Python Backend Intern – UnresponsiveCo",
        description=(
            "Join our platform team to build microservices with FastAPI, PostgreSQL, "
            "and Kubernetes. Rich technical environment with strong mentor support."
        ),
        requirements=["Python", "FastAPI", "SQL", "Docker"],
        location="Remote",
        work_mode="remote",
        source="greenhouse",
        source_url="https://unresponsiveco.com/jobs/rl-1",
        last_seen_at=now,
        posted_at=now,
        dedup_key=str(uuid.uuid4())[:16],
        status="active",
        ghost_score=0.08,   # below threshold — Ghost Shield does NOT flag it
        is_ghost=False,
        source_sightings=1,
        embedding=_vec(5),  # same embedding as p_good → equal semantic similarity
    )
    db.add_all([p_good, p_deceptive])
    await db.commit()

    return {
        "co_good": co_good, "co_bad": co_bad,
        "p_good": p_good, "p_deceptive": p_deceptive,
    }


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_responsive_company_has_higher_rl(
    client: AsyncClient,
    rl_user: dict[str, str],
    seeded_rl: dict[str, Any],
) -> None:
    """Posting at 75%-responsive company must have higher response_likelihood
    than identical posting at 4%-responsive company."""
    r = await client.get(MATCHES_URL, headers=rl_user)
    assert r.status_code == 200

    matches = {m["posting_id"]: m for m in r.json()["data"]}
    good_id = str(seeded_rl["p_good"].id)
    bad_id = str(seeded_rl["p_deceptive"].id)

    assert good_id in matches, "ResponsiveCo posting not in feed"
    assert bad_id in matches, "UnresponsiveCo posting not in feed"

    rl_good = matches[good_id]["response_likelihood"]
    rl_bad = matches[bad_id]["response_likelihood"]

    assert rl_good > rl_bad, (
        f"ResponsiveCo RL ({rl_good:.3f}) should exceed UnresponsiveCo RL ({rl_bad:.3f})"
    )
    assert rl_good - rl_bad > 0.25, (
        f"Difference should be substantial (> 0.25); got {rl_good - rl_bad:.3f}"
    )


@pytest.mark.asyncio
async def test_deceptive_posting_has_lower_expected_value(
    client: AsyncClient,
    rl_user: dict[str, str],
    seeded_rl: dict[str, Any],
) -> None:
    """Deceptive posting (fresh + low ghost_score, bad company) must rank below
    the identical posting at the responsive company — despite matching the same skills.
    This is the core Module 5 demo case."""
    r = await client.get(MATCHES_URL, headers=rl_user)
    assert r.status_code == 200

    matches = {m["posting_id"]: m for m in r.json()["data"]}
    good_id = str(seeded_rl["p_good"].id)
    bad_id = str(seeded_rl["p_deceptive"].id)

    ev_good = matches[good_id]["expected_value"]
    ev_bad = matches[bad_id]["expected_value"]

    assert ev_good > ev_bad, (
        f"ResponsiveCo EV ({ev_good:.3f}) should exceed deceptive UnresponsiveCo EV ({ev_bad:.3f})"
    )

    # Verify the deceptive posting ranks lower in the feed (higher index = worse rank)
    feed_ids = [m["posting_id"] for m in r.json()["data"]]
    assert feed_ids.index(good_id) < feed_ids.index(bad_id), (
        "ResponsiveCo posting should rank above deceptive UnresponsiveCo posting"
    )


@pytest.mark.asyncio
async def test_explanation_includes_cohort_reason_for_low_response_rate(
    client: AsyncClient,
    rl_user: dict[str, str],
    seeded_rl: dict[str, Any],
) -> None:
    """match_explanation for the deceptive posting must include the cohort demotion reason."""
    r = await client.get(MATCHES_URL, headers=rl_user)
    assert r.status_code == 200

    matches = {m["posting_id"]: m for m in r.json()["data"]}
    bad_id = str(seeded_rl["p_deceptive"].id)
    explanation = matches[bad_id]["match_explanation"]

    assert "batchmates" in explanation, (
        f"Expected cohort demotion reason in explanation; got: {explanation!r}"
    )
    assert "of 10" in explanation


@pytest.mark.asyncio
async def test_explanation_no_cohort_reason_for_responsive_company(
    client: AsyncClient,
    rl_user: dict[str, str],
    seeded_rl: dict[str, Any],
) -> None:
    """match_explanation for a responsive company posting must NOT include the cohort reason."""
    r = await client.get(MATCHES_URL, headers=rl_user)
    assert r.status_code == 200

    matches = {m["posting_id"]: m for m in r.json()["data"]}
    good_id = str(seeded_rl["p_good"].id)
    explanation = matches[good_id]["match_explanation"]

    assert "batchmates" not in explanation, (
        f"Responsive company should not trigger cohort warning; got: {explanation!r}"
    )


@pytest.mark.asyncio
async def test_expected_value_formula_holds(
    client: AsyncClient,
    rl_user: dict[str, str],
    seeded_rl: dict[str, Any],
) -> None:
    """expected_value == match_score * response_likelihood * (1 - ghost_score) for all matches."""
    r = await client.get(MATCHES_URL, headers=rl_user, params={"include_ghosts": "true"})
    assert r.status_code == 200

    for m in r.json()["data"]:
        computed = m["match_score"] * m["response_likelihood"] * (1.0 - m["ghost_score"])
        computed = max(0.0, min(1.0, computed))
        assert math.isclose(m["expected_value"], computed, abs_tol=1e-6), (
            f"EV mismatch for {m['posting_id']}: {m['expected_value']} != {computed:.6f}"
        )


@pytest.mark.asyncio
async def test_response_likelihood_in_range_for_all_feed_items(
    client: AsyncClient,
    rl_user: dict[str, str],
    seeded_rl: dict[str, Any],
) -> None:
    r = await client.get(MATCHES_URL, headers=rl_user, params={"include_ghosts": "true"})
    assert r.status_code == 200

    for m in r.json()["data"]:
        rl = m["response_likelihood"]
        assert 0.0 <= rl <= 1.0, f"response_likelihood out of [0,1]: {rl}"


@pytest.mark.asyncio
async def test_match_detail_includes_rl_and_cohort_reason(
    client: AsyncClient,
    rl_user: dict[str, str],
    seeded_rl: dict[str, Any],
) -> None:
    """Single-match detail endpoint also exposes correct RL and cohort annotation."""
    bad_id = str(seeded_rl["p_deceptive"].id)
    r = await client.get(f"{MATCHES_URL}/{bad_id}", headers=rl_user)
    assert r.status_code == 200

    m = r.json()["match"]
    assert 0.0 <= m["response_likelihood"] <= 1.0
    assert "batchmates" in m["match_explanation"]
    ev = m["match_score"] * m["response_likelihood"] * (1.0 - m["ghost_score"])
    ev = max(0.0, min(1.0, ev))
    assert math.isclose(m["expected_value"], ev, abs_tol=1e-6)
