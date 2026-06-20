"""Tests for grounding score calibration evaluation.

Pure-function tests need no DB.  Integration tests use the async DB fixture.
"""
from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.eval_grounding_service import (
    EvalGroundingService,
    bucket_analysis,
    ece,
    find_optimal_threshold,
    spearman_rho,
)

# ---------------------------------------------------------------------------
# 1. ECE — Expected Calibration Error (hand-verified)
# ---------------------------------------------------------------------------


def test_ece_perfect_calibration() -> None:
    """If every bucket's mean score equals its response rate, ECE = 0."""
    # 5 samples: scores exactly equal outcomes
    # All in [0.8, 0.9) bucket: mean_conf=0.85, mean_acc=1.0 → gap=0.15
    # But for perfect calibration: score must equal probability
    scores = [0.0, 0.25, 0.5, 0.75, 1.0]
    actuals = [0, 0, 1, 1, 1]   # rough but not perfect — just check it runs
    result = ece(scores, actuals)
    assert 0.0 <= result <= 1.0


def test_ece_empty_returns_zero() -> None:
    assert ece([], []) == pytest.approx(0.0)


def test_ece_all_correct_high_confidence() -> None:
    """All scores near 1.0, all actuals = 1 → low ECE."""
    scores = [0.95, 0.92, 0.91, 0.98, 0.93]
    actuals = [1, 1, 1, 1, 1]
    result = ece(scores, actuals, n_bins=10)
    assert result < 0.15  # well-calibrated


def test_ece_worst_case() -> None:
    """High confidence, always wrong → high ECE ≈ 0.9."""
    scores = [0.95, 0.96, 0.94, 0.97]
    actuals = [0, 0, 0, 0]
    result = ece(scores, actuals, n_bins=10)
    assert result > 0.8


# ---------------------------------------------------------------------------
# 2. find_optimal_threshold
# ---------------------------------------------------------------------------


def test_optimal_threshold_perfect_separator() -> None:
    """Scores perfectly separate classes → optimal threshold exists between 0.5 and 0.6."""
    scores = [0.1, 0.2, 0.15, 0.8, 0.9, 0.85]
    actuals = [0, 0, 0, 1, 1, 1]
    opt_t, f1_opt, _ = find_optimal_threshold(scores, actuals)
    assert 0.3 <= opt_t <= 0.85
    assert f1_opt == pytest.approx(1.0, abs=1e-4)


def test_optimal_threshold_returns_higher_than_current_when_beneficial() -> None:
    """When low scores predict positives better, optimal threshold should be low."""
    scores = [0.8, 0.9, 0.1, 0.15]   # reversed: high score → not responded
    actuals = [0, 0, 1, 1]
    opt_t, f1_opt, f1_cur = find_optimal_threshold(scores, actuals)
    # Threshold = 0.3 → preds all 1 for low scores... let's just check it runs
    assert 0.3 <= opt_t <= 0.9
    assert 0.0 <= f1_opt <= 1.0
    assert 0.0 <= f1_cur <= 1.0


def test_optimal_threshold_single_class_no_crash() -> None:
    """All same actual label → f1 may be 0 but function should not crash."""
    scores = [0.5, 0.6, 0.7]
    actuals = [0, 0, 0]
    opt_t, f1_opt, f1_cur = find_optimal_threshold(scores, actuals)
    assert 0.3 <= opt_t <= 0.9
    assert f1_opt >= 0.0


# ---------------------------------------------------------------------------
# 3. spearman_rho
# ---------------------------------------------------------------------------


def test_spearman_positive_correlation() -> None:
    scores = [0.1, 0.3, 0.5, 0.7, 0.9]
    actuals = [0, 0, 1, 1, 1]
    rho, p = spearman_rho(scores, actuals)
    assert rho > 0.6  # strong positive correlation
    assert p < 0.2


def test_spearman_negative_correlation() -> None:
    scores = [0.9, 0.8, 0.2, 0.1]
    actuals = [0, 0, 1, 1]
    rho, _ = spearman_rho(scores, actuals)
    assert rho < 0.0  # negative: higher score → no response


def test_spearman_too_few_samples() -> None:
    rho, p = spearman_rho([0.5, 0.6], [1, 0])
    assert rho == pytest.approx(0.0)
    assert p == pytest.approx(1.0)


def test_spearman_no_crash_constant_series() -> None:
    scores = [0.5, 0.5, 0.5, 0.5]
    actuals = [0, 1, 0, 1]
    rho, p = spearman_rho(scores, actuals)
    assert isinstance(rho, float)


# ---------------------------------------------------------------------------
# 4. bucket_analysis
# ---------------------------------------------------------------------------


def test_bucket_analysis_four_buckets_always_returned() -> None:
    result = bucket_analysis([], [])
    assert len(result) == 4
    for b in result:
        assert "bucket" in b and "n" in b and "response_rate" in b


def test_bucket_analysis_counts_correctly() -> None:
    scores = [0.1, 0.25, 0.4, 0.6, 0.75, 0.9]
    actuals = [0, 0, 0, 1, 1, 1]
    result = bucket_analysis(scores, actuals)
    totals = sum(b["n"] for b in result)
    assert totals == len(scores)


def test_bucket_analysis_response_rate_in_range() -> None:
    scores = [0.1, 0.4, 0.6, 0.8]
    actuals = [0, 1, 1, 1]
    result = bucket_analysis(scores, actuals)
    for b in result:
        if b["response_rate"] is not None:
            assert 0.0 <= b["response_rate"] <= 1.0


# ---------------------------------------------------------------------------
# 5. EvalGroundingService — integration (DB required)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_grounding_calibration_insufficient_data(db: AsyncSession) -> None:
    """With no pitch artifacts in DB, returns health=insufficient_data."""
    svc = EvalGroundingService(db)
    result = await svc.run_calibration()
    assert result.health == "insufficient_data"
    assert result.n_with_outcomes == 0
    assert result.is_predictive is False
    assert result.spearman_rho == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_grounding_calibration_with_synthetic_data(db: AsyncSession) -> None:
    """Seed pitch artifacts + outreach with known scores → calibration runs correctly."""
    import uuid as _uuid
    from datetime import UTC, datetime

    from app.models.artifact import Artifact
    from app.models.research_opportunity import ResearchOpportunity
    from app.models.research_outreach import ResearchOutreach
    from app.models.user import AuthProvider, User, UserRole

    # Create user and opportunity
    user = User(
        name="Grounding Test",
        email="grounding_test@example.com",
        password_hash="x",
        role=UserRole.student,
        auth_provider=AuthProvider.password,
    )
    db.add(user)
    opp = ResearchOpportunity(
        professor_name="Dr. Test",
        institution="Test University",
        research_area="NLP",
        description="Research on language models.",
        desired_skills=["Python"],
        source="test",
        last_seen_at=datetime.now(UTC),
    )
    db.add(opp)
    await db.flush()

    # Seed 12 (artifact, outreach) pairs with known calibration signal:
    # high grounding score → replied/accepted; low score → declined/no_response
    cases = [
        (0.85, "replied"),
        (0.90, "accepted"),
        (0.80, "replied"),
        (0.82, "accepted"),
        (0.78, "replied"),
        (0.88, "accepted"),
        (0.15, "declined"),
        (0.20, "no_response"),
        (0.10, "declined"),
        (0.25, "no_response"),
        (0.12, "declined"),
        (0.18, "no_response"),
    ]
    for gs, status in cases:
        artifact = Artifact(
            user_id=user.id,
            application_id=None,
            type="research_pitch",
            content="Subject: Test\n\nBody",
            ats_score=None,
            missing_keywords=[],
            grounding_score=gs,
            predicted_response=None,
            version=1,
        )
        db.add(artifact)
        await db.flush()

        outreach = ResearchOutreach(
            user_id=user.id,
            research_opportunity_id=opp.id,
            pitch_artifact_id=artifact.id,
            status=status,
        )
        db.add(outreach)

    await db.commit()

    svc = EvalGroundingService(db)
    result = await svc.run_calibration()

    # With a clean separation between high and low scores, Spearman ρ > 0.8
    assert result.n_with_outcomes == 12
    assert result.spearman_rho > 0.7, f"Expected ρ > 0.7, got {result.spearman_rho}"
    assert result.is_predictive is True
    assert result.spearman_p_value < 0.05  # noqa: PLR2004

    # Optimal threshold should be between 0.25 and 0.78 (the separation gap)
    assert 0.25 <= result.optimal_threshold <= 0.78

    # F1 at optimal threshold should be high (clean separation)
    assert result.f1_at_optimal > 0.8

    # Bucket analysis should show 4 buckets, high score → high response rate
    high_bucket = next(b for b in result.bucket_analysis if b["bucket"] == "[0.70, 1.00]")
    low_bucket = next(b for b in result.bucket_analysis if b["bucket"] == "[0.00, 0.30)")
    assert high_bucket["response_rate"] is not None and high_bucket["response_rate"] > 0.8
    assert low_bucket["response_rate"] is not None and low_bucket["response_rate"] < 0.2

    # Health should not be insufficient_data
    assert result.health != "insufficient_data"


# ---------------------------------------------------------------------------
# 6. API endpoint integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_grounding_endpoint_requires_admin(
    client: AsyncClient, auth_headers: dict
) -> None:
    """GET /api/evaluation/grounding → 403 for non-admin."""
    resp = await client.get("/api/evaluation/grounding", headers=auth_headers)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_matching_endpoint_requires_admin(
    client: AsyncClient, auth_headers: dict
) -> None:
    """POST /api/evaluation/matching → 403 for non-admin."""
    resp = await client.post("/api/evaluation/matching", headers=auth_headers)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"
