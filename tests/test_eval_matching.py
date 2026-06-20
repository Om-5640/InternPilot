"""Tests for the offline matching quality evaluation system.

All pure-function tests run without a DB or the sentence-transformer model.
Integration test uses the real embedding model (marked asyncio).
"""
from __future__ import annotations

import pytest

from app.services.eval_matching_service import (
    GOLDEN_OPPORTUNITIES,
    GOLDEN_PROFILES,
    RELEVANCE,
    EvalMatchingService,
    _cosine_sim,
    _fit_score,
    _rank_opps_for_profile,
    mrr,
    ndcg_at_k,
    precision_at_k,
)

# ---------------------------------------------------------------------------
# 1. NDCG pure-function correctness (hand-verified)
# ---------------------------------------------------------------------------


def test_ndcg_perfect_ranking() -> None:
    """Ideal ordering → NDCG = 1.0."""
    ranked = [3, 2, 1, 0, 0]
    assert ndcg_at_k(ranked, k=5) == pytest.approx(1.0, abs=1e-6)


def test_ndcg_worst_ranking() -> None:
    """Reversed ordering → NDCG < 1.0."""
    ranked = [0, 0, 1, 2, 3]
    assert ndcg_at_k(ranked, k=5) < 1.0


def test_ndcg_all_zero_is_zero() -> None:
    """No relevant results → 0 (IDCG = 0 so we return 0 not NaN)."""
    assert ndcg_at_k([0, 0, 0], k=3) == pytest.approx(0.0)


def test_ndcg_k_truncation() -> None:
    """Only top-k entries are counted."""
    # Position 0 is rank-3, position 1 is rank-0 → NDCG@1 uses only position 0.
    ranked = [3, 0, 0]
    assert ndcg_at_k(ranked, k=1) == pytest.approx(1.0, abs=1e-6)


def test_ndcg_partial_relevance_hand_verified() -> None:
    """Hand-verify NDCG@3 for [2, 1, 0, 3].

    DCG@3  = (2^2-1)/log2(2) + (2^1-1)/log2(3) + (2^0-1)/log2(4)
           = 3/1 + 1/1.585 + 0/2 = 3 + 0.631 = 3.631
    IDCG@3 = (2^3-1)/log2(2) + (2^2-1)/log2(3) + (2^1-1)/log2(4)
           = 7/1 + 3/1.585 + 1/2 = 7 + 1.893 + 0.5 = 9.393
    NDCG@3 = 3.631 / 9.393 ≈ 0.3866
    """
    import math
    ranked = [2, 1, 0, 3]
    dcg = 3 / math.log2(2) + 1 / math.log2(3) + 0 / math.log2(4)
    idcg = 7 / math.log2(2) + 3 / math.log2(3) + 1 / math.log2(4)
    expected = dcg / idcg
    assert ndcg_at_k(ranked, k=3) == pytest.approx(expected, abs=1e-4)


# ---------------------------------------------------------------------------
# 2. Precision@k
# ---------------------------------------------------------------------------


def test_precision_at_k_all_relevant() -> None:
    assert precision_at_k([3, 2, 1], k=3) == pytest.approx(1.0)


def test_precision_at_k_none_relevant() -> None:
    assert precision_at_k([0, 0, 0], k=3) == pytest.approx(0.0)


def test_precision_at_k_mixed() -> None:
    # 2 of top-3 have relevance ≥ 1
    assert precision_at_k([2, 0, 1, 3], k=3) == pytest.approx(2 / 3, abs=1e-6)


# ---------------------------------------------------------------------------
# 3. MRR
# ---------------------------------------------------------------------------


def test_mrr_first_position() -> None:
    assert mrr([3, 0, 0]) == pytest.approx(1.0)


def test_mrr_third_position() -> None:
    assert mrr([0, 0, 2, 1]) == pytest.approx(1 / 3, abs=1e-6)


def test_mrr_no_relevant() -> None:
    assert mrr([0, 0, 0]) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# 4. _cosine_sim
# ---------------------------------------------------------------------------


def test_cosine_sim_identical() -> None:
    v = [1.0, 0.0, 1.0]
    assert _cosine_sim(v, v) == pytest.approx(1.0, abs=1e-6)


def test_cosine_sim_orthogonal() -> None:
    assert _cosine_sim([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0, abs=1e-6)


def test_cosine_sim_opposite() -> None:
    assert _cosine_sim([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0, abs=1e-6)


def test_cosine_sim_zero_vector() -> None:
    assert _cosine_sim([0.0, 0.0], [1.0, 0.0]) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# 5. _fit_score matches documented formula
# ---------------------------------------------------------------------------


def test_fit_score_formula() -> None:
    """fit_score = sem_w × cos_sim + skill_w × skill_ratio, clamped [0, 1]."""
    emb_a = [1.0, 0.0, 0.0]
    emb_b = [1.0, 0.0, 0.0]   # identical → cos_sim = 1.0
    profile_skills = ["Python", "PyTorch"]
    desired = ["Python", "PyTorch", "NLP"]   # 2/3 matched → skill_ratio = 0.667

    sem_w, skill_w = 0.7, 0.3
    score = _fit_score(emb_a, emb_b, profile_skills, desired, sem_w, skill_w)
    expected = 0.7 * 1.0 + 0.3 * (2 / 3)
    assert score == pytest.approx(expected, abs=1e-4)


def test_fit_score_empty_desired_skills_gives_full_skill_credit() -> None:
    """No desired skills → skill_ratio = 1.0 (benefit of the doubt)."""
    emb = [1.0, 0.0]
    score = _fit_score(emb, emb, ["Python"], [], sem_w=0.7, skill_w=0.3)
    assert score == pytest.approx(0.7 * 1.0 + 0.3 * 1.0, abs=1e-4)


def test_fit_score_clamped_to_unit_interval() -> None:
    emb = [1.0, 0.0]
    s = _fit_score(emb, emb, ["Python"], ["Python"], sem_w=1.0, skill_w=0.0)
    assert 0.0 <= s <= 1.0


# ---------------------------------------------------------------------------
# 6. Golden set structural integrity
# ---------------------------------------------------------------------------


def test_golden_set_sizes() -> None:
    assert len(GOLDEN_PROFILES) == 4
    assert len(GOLDEN_OPPORTUNITIES) == 8
    assert len(RELEVANCE) == 4
    assert all(len(row) == 8 for row in RELEVANCE)


def test_relevance_labels_in_range() -> None:
    for row in RELEVANCE:
        for label in row:
            assert 0 <= label <= 3


def test_each_profile_has_exactly_one_peak() -> None:
    """Each profile should have at least one opportunity with relevance = 3."""
    for p_idx, profile in enumerate(GOLDEN_PROFILES):
        assert max(RELEVANCE[p_idx]) == 3, (
            f"Profile '{profile['id']}' has no highly-relevant opportunity (max={max(RELEVANCE[p_idx])})"
        )


def test_embedded_systems_always_zero() -> None:
    """Embedded systems is irrelevant to all profiles by design."""
    sys_idx = next(i for i, o in enumerate(GOLDEN_OPPORTUNITIES) if o["id"] == "embedded_sys")
    for p_idx in range(len(GOLDEN_PROFILES)):
        assert RELEVANCE[p_idx][sys_idx] == 0


# ---------------------------------------------------------------------------
# 7. _rank_opps_for_profile — with mock embeddings
# ---------------------------------------------------------------------------


def _unit_vec(dim: int, idx: int) -> list[float]:
    """Return a one-hot unit vector at position idx (length dim)."""
    v = [0.0] * dim
    v[idx % dim] = 1.0
    return v


def test_rank_opps_prefers_identical_embedding() -> None:
    """Profile embedding = opp[2] → opp[2] should rank first when skills match."""
    dim = 8  # must be ≥ 8 so no modulo wrap produces duplicate vectors
    profile_emb = _unit_vec(dim, 2)
    opp_embs = [_unit_vec(dim, i) for i in range(8)]  # 8 orthogonal vectors
    profile_skills: list[str] = []
    desired = [[] for _ in range(8)]

    # Monkey-patch GOLDEN_OPPORTUNITIES desired_skills temporarily
    original = [o["desired_skills"] for o in GOLDEN_OPPORTUNITIES]
    for i, o in enumerate(GOLDEN_OPPORTUNITIES):
        o["desired_skills"] = desired[i]

    ranked = _rank_opps_for_profile(profile_emb, opp_embs, profile_skills, 0.7, 0.3)
    assert ranked[0] == 2  # opp at index 2 has identical embedding → ranks first

    for i, o in enumerate(GOLDEN_OPPORTUNITIES):
        o["desired_skills"] = original[i]


# ---------------------------------------------------------------------------
# 8. EvalMatchingService — integration (real embeddings, no DB)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_eval_matching_returns_valid_metrics() -> None:
    """Run the full eval with the real sentence-transformer model.

    Asserts that metrics are in [0, 1] and the result is structurally correct.
    This test is slow (~5 s on first run) because it loads the model.
    """
    svc = EvalMatchingService()
    result = await svc.run_eval()

    assert 0.0 <= result.ndcg_at_3 <= 1.0
    assert 0.0 <= result.ndcg_at_5 <= 1.0
    assert 0.0 <= result.precision_at_3 <= 1.0
    assert 0.0 <= result.mrr <= 1.0
    assert result.health in ("good", "needs_attention", "insufficient_data")
    assert len(result.profile_breakdown) == 4
    for p in result.profile_breakdown:
        assert p.profile_id in {pr["id"] for pr in GOLDEN_PROFILES}
        assert 0.0 <= p.ndcg_at_5 <= 1.0

    # Weight recommendation must always be a non-empty string
    assert len(result.weight_recommendation) > 10  # noqa: PLR2004

    # Optimal NDCG@5 must be ≥ current NDCG@5 (grid search maximises)
    assert result.optimal_ndcg_at_5 >= result.ndcg_at_5 - 1e-6


@pytest.mark.asyncio
async def test_eval_matching_nlp_profile_top_match_is_nlp_lab() -> None:
    """The NLP-researcher profile should rank the NLP-lab opportunity first."""
    svc = EvalMatchingService()
    result = await svc.run_eval()

    nlp_profile = next(p for p in result.profile_breakdown if p.profile_id == "nlp_researcher")
    assert nlp_profile.top_match_is_correct, (
        f"Expected NLP lab as top match, got '{nlp_profile.top_match_label}'"
    )


@pytest.mark.asyncio
async def test_eval_matching_bio_profile_top_match_is_genomics() -> None:
    """The bio-researcher profile should rank the genomics lab first."""
    svc = EvalMatchingService()
    result = await svc.run_eval()

    bio_profile = next(p for p in result.profile_breakdown if p.profile_id == "bio_researcher")
    assert bio_profile.top_match_is_correct, (
        f"Expected genomics lab as top match, got '{bio_profile.top_match_label}'"
    )


@pytest.mark.asyncio
async def test_eval_matching_regression_detection() -> None:
    """Second call with same weights should not flag a regression."""
    svc = EvalMatchingService()
    await svc.run_eval()           # sets the baseline
    result2 = await svc.run_eval() # baseline == current → no regression
    assert result2.previous_ndcg_at_5 is not None
    # Regression threshold is 0.02; same run should be identical → no regression
    assert result2.regression_detected is False
