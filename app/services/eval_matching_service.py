"""Offline matching quality evaluation using a hand-labeled golden set.

Architecture
============
  Golden set: 4 profile archetypes × 8 opportunity archetypes = 32 (profile, opp) pairs,
              each labeled 0–3 (0=irrelevant, 1=marginal, 2=relevant, 3=highly relevant).

  Metrics (all computed with the PRODUCTION scoring formula):
    NDCG@3   — quality of the top-3 ranked results (most actionable)
    NDCG@5   — primary headline metric for regression detection
    Precision@3 — fraction of top-3 that are genuinely relevant (score ≥ 1)
    MRR      — mean reciprocal rank of the first truly relevant result

  Weight optimisation:
    Grid-search SEMANTIC_WEIGHT ∈ {0.40 … 0.90} (SKILL_WEIGHT = 1 − SEMANTIC_WEIGHT).
    Returns the pair that maximises NDCG@5 averaged across all profiles.
    Concretely answers: "would changing the weights improve ranking quality, and by how much?"

  Regression detection:
    Compares current run's NDCG@5 against the previous run stored in module-level cache.
    Flags if NDCG@5 drops > 0.02 (2 pp) — indicates a code or model regression.

  Fully offline — no DB, no live user data, no LLM calls.
  Embeddings are computed by the production sentence-transformer model and cached in memory
  after the first call so subsequent endpoint hits are sub-100 ms.
"""
from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass, field

import numpy as np

from app.llm.embeddings import embed
from app.services.matching_service import _compute_skill_overlap
from app.services.research_service import SEMANTIC_WEIGHT, SKILL_WEIGHT

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Golden set definition
# ---------------------------------------------------------------------------

# Each profile: {id, description (for embedding), skills (for skill-overlap)}
GOLDEN_PROFILES: list[dict] = [
    {
        "id": "nlp_researcher",
        "label": "NLP / AI researcher",
        "description": (
            "PhD student researching natural language processing, transformer architectures, "
            "and text generation. Developed BERT-based information extraction systems and "
            "multilingual summarisation pipelines. Deep expertise in attention mechanisms."
        ),
        "skills": ["Python", "PyTorch", "HuggingFace", "NLP", "BERT", "transformers", "text mining"],
        "interests": ["NLP", "language models", "text generation"],
    },
    {
        "id": "cv_researcher",
        "label": "Computer Vision researcher",
        "description": (
            "Undergraduate studying computer vision and deep learning for image recognition and "
            "medical imaging. Built CNN architectures for tumour detection and autonomous vehicle "
            "perception with PyTorch and OpenCV. Interested in 3-D reconstruction."
        ),
        "skills": ["Python", "PyTorch", "OpenCV", "CNNs", "TensorFlow", "image processing", "computer vision"],
        "interests": ["computer vision", "medical imaging", "deep learning"],
    },
    {
        "id": "fullstack_dev",
        "label": "Full-stack web developer",
        "description": (
            "Software engineer with two years building scalable web applications. Implemented "
            "React + TypeScript frontends, Node.js backends with REST APIs, and PostgreSQL "
            "databases. Shipped two SaaS products serving thousands of active users."
        ),
        "skills": ["TypeScript", "React", "Node.js", "PostgreSQL", "REST APIs", "Docker", "JavaScript"],
        "interests": ["web development", "software engineering", "product"],
    },
    {
        "id": "bio_researcher",
        "label": "Computational biologist",
        "description": (
            "Biology PhD student applying machine learning to genomics and protein structure "
            "prediction. Uses Python and R for CRISPR off-target analysis, variant calling, "
            "and phylogenetic inference. Proficient in standard bioinformatics pipelines."
        ),
        "skills": ["Python", "R", "BioPython", "genomics", "bioinformatics", "BLAST", "sequence analysis"],
        "interests": ["computational biology", "genomics", "protein structure"],
    },
]

# Each opportunity: {id, description (for embedding), desired_skills}
GOLDEN_OPPORTUNITIES: list[dict] = [
    {
        "id": "nlp_lab",
        "label": "NLP Research Lab",
        "description": (
            "Research internship in a natural language processing lab. Projects include large "
            "language models, text summarisation, and question-answering over documents. "
            "Work with transformer architectures, attention mechanisms, and prompt engineering."
        ),
        "desired_skills": ["Python", "PyTorch", "NLP", "HuggingFace", "transformers"],
    },
    {
        "id": "cv_group",
        "label": "Computer Vision Group",
        "description": (
            "Research position studying object detection, image segmentation, and autonomous "
            "driving perception. Build deep-learning models using PyTorch and OpenCV for "
            "real-world scene understanding and 3-D reconstruction."
        ),
        "desired_skills": ["Python", "PyTorch", "OpenCV", "CNNs", "computer vision"],
    },
    {
        "id": "genomics_lab",
        "label": "Computational Genomics Lab",
        "description": (
            "Research assistant for computational genomics: whole-genome sequencing analysis, "
            "variant-calling pipelines, and CRISPR off-target prediction using machine learning. "
            "Protein structure and phylogenetic analysis also involved."
        ),
        "desired_skills": ["Python", "R", "bioinformatics", "genomics", "machine learning"],
    },
    {
        "id": "saas_startup",
        "label": "SaaS Full-Stack Internship",
        "description": (
            "Full-stack engineering internship building the frontend and backend of a B2B SaaS "
            "product. Implement new features in React and TypeScript, optimise PostgreSQL "
            "queries, and design REST APIs in Node.js. Ship to production weekly."
        ),
        "desired_skills": ["TypeScript", "React", "Node.js", "PostgreSQL", "REST APIs"],
    },
    {
        "id": "ml_generalist",
        "label": "General ML Research Internship",
        "description": (
            "Machine learning internship across computer vision, NLP, and tabular data tasks. "
            "Run experiments, implement paper reproductions, and build production ML pipelines. "
            "Strong Python and deep-learning framework skills required."
        ),
        "desired_skills": ["Python", "PyTorch", "machine learning", "scikit-learn", "deep learning"],
    },
    {
        "id": "backend_eng",
        "label": "Backend Engineering Internship",
        "description": (
            "Backend software-engineering internship building Python microservices and REST APIs. "
            "Focus on database optimisation, caching strategies, and API design. "
            "No machine learning or frontend work involved."
        ),
        "desired_skills": ["Python", "REST APIs", "SQL", "Docker", "FastAPI"],
    },
    {
        "id": "data_analytics",
        "label": "Data Analytics Internship",
        "description": (
            "Data analytics intern extracting business insights from large datasets using SQL, "
            "Python, and visualisation tools. Work with stakeholders to define KPIs and "
            "build executive dashboards. Statistical analysis background preferred."
        ),
        "desired_skills": ["Python", "SQL", "pandas", "data visualisation", "statistics"],
    },
    {
        "id": "embedded_sys",
        "label": "Embedded Systems Internship",
        "description": (
            "Systems-programming internship on embedded firmware and hardware drivers. "
            "Low-level C++ and Rust for operating-system networking stacks and real-time "
            "control loops. No machine learning, web development, or bioinformatics."
        ),
        "desired_skills": ["C++", "Rust", "embedded systems", "Linux", "networking", "firmware"],
    },
]

# Relevance labels: RELEVANCE[profile_idx][opp_idx] ∈ {0, 1, 2, 3}
# 3=highly relevant, 2=relevant, 1=marginal, 0=irrelevant
#                        nlp  cv   bio  web   ml  back data  sys
RELEVANCE: list[list[int]] = [
    [3,   1,   0,   0,   2,   0,   0,   0],   # nlp_researcher
    [1,   3,   0,   0,   2,   0,   0,   0],   # cv_researcher
    [0,   0,   0,   3,   0,   1,   1,   0],   # fullstack_dev
    [0,   0,   3,   0,   1,   0,   1,   0],   # bio_researcher
]

# ---------------------------------------------------------------------------
# Pure ranking metrics
# ---------------------------------------------------------------------------


def ndcg_at_k(ranked_scores: list[int], k: int) -> float:
    """NDCG@k.  ranked_scores[i] is the relevance label at rank i (0-indexed)."""
    dcg = sum(
        (2 ** rel - 1) / math.log2(i + 2)
        for i, rel in enumerate(ranked_scores[:k])
    )
    ideal = sorted(ranked_scores, reverse=True)
    idcg = sum(
        (2 ** rel - 1) / math.log2(i + 2)
        for i, rel in enumerate(ideal[:k])
    )
    return dcg / idcg if idcg > 0 else 0.0


def precision_at_k(ranked_scores: list[int], k: int, threshold: int = 1) -> float:
    """Fraction of top-k results with relevance ≥ threshold."""
    top = ranked_scores[:k]
    return sum(1 for r in top if r >= threshold) / k if k else 0.0


def mrr(ranked_scores: list[int]) -> float:
    """Mean Reciprocal Rank: reciprocal rank of first relevant result."""
    for i, r in enumerate(ranked_scores):
        if r >= 1:
            return 1.0 / (i + 1)
    return 0.0


# ---------------------------------------------------------------------------
# Scoring helpers (replicates production formula without DB)
# ---------------------------------------------------------------------------


def _cosine_sim(a: list[float], b: list[float]) -> float:
    va, vb = np.array(a, dtype=np.float32), np.array(b, dtype=np.float32)
    denom = float(np.linalg.norm(va) * np.linalg.norm(vb))
    return float(np.dot(va, vb) / denom) if denom > 0 else 0.0


def _fit_score(
    profile_emb: list[float],
    opp_emb: list[float],
    profile_skills: list[str],
    desired_skills: list[str],
    sem_w: float,
    skill_w: float,
) -> float:
    """Mirror of ResearchService._score_opportunity without DB access."""
    matched, _ = _compute_skill_overlap(profile_skills, desired_skills)
    semantic_sim = max(0.0, _cosine_sim(profile_emb, opp_emb))
    skill_ratio = 1.0 if not desired_skills else len(matched) / len(desired_skills)
    return max(0.0, min(1.0, sem_w * semantic_sim + skill_w * skill_ratio))


def _rank_opps_for_profile(
    profile_emb: list[float],
    opp_embs: list[list[float]],
    profile_skills: list[str],
    sem_w: float,
    skill_w: float,
) -> list[int]:
    """Return list of opportunity indices sorted best-first."""
    scores = [
        (
            _fit_score(
                profile_emb, opp_emb, profile_skills,
                GOLDEN_OPPORTUNITIES[j]["desired_skills"], sem_w, skill_w,
            ),
            j,
        )
        for j, opp_emb in enumerate(opp_embs)
    ]
    return [j for _, j in sorted(scores, reverse=True)]


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ProfileResult:
    profile_id: str
    label: str
    ndcg_at_3: float
    ndcg_at_5: float
    precision_at_3: float
    mrr: float
    top_match_label: str
    top_match_is_correct: bool


@dataclass
class WeightSearchResult:
    semantic_weight: float
    skill_weight: float
    ndcg_at_5: float


@dataclass
class MatchingEvalResult:
    ndcg_at_3: float
    ndcg_at_5: float
    precision_at_3: float
    mrr: float
    current_weights: dict
    optimal_weights: dict
    optimal_ndcg_at_5: float
    weight_gain_pct: float
    weight_recommendation: str
    profile_breakdown: list[ProfileResult]
    regression_detected: bool
    previous_ndcg_at_5: float | None
    health: str  # "good" | "needs_attention" | "insufficient_data"
    run_at: str


# ---------------------------------------------------------------------------
# Module-level embedding cache + regression baseline
# ---------------------------------------------------------------------------

_emb_cache: dict[str, list[float]] = {}
_prev_ndcg5: float | None = None
_cache_lock = asyncio.Lock()


async def _get_embeddings() -> tuple[list[list[float]], list[list[float]]]:
    """Return (profile_embs, opp_embs), computed once and cached for the process lifetime."""
    global _emb_cache
    async with _cache_lock:
        profile_texts = [p["description"] for p in GOLDEN_PROFILES]
        opp_texts = [o["description"] for o in GOLDEN_OPPORTUNITIES]
        missing = [t for t in profile_texts + opp_texts if t not in _emb_cache]
        if missing:
            vectors = await embed(missing)
            for text, vec in zip(missing, vectors):
                _emb_cache[text] = vec
    profile_embs = [_emb_cache[p["description"]] for p in GOLDEN_PROFILES]
    opp_embs = [_emb_cache[o["description"]] for o in GOLDEN_OPPORTUNITIES]
    return profile_embs, opp_embs


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class EvalMatchingService:
    """Offline matching quality evaluation — no DB required."""

    async def run_eval(self) -> MatchingEvalResult:
        global _prev_ndcg5
        from datetime import UTC, datetime

        profile_embs, opp_embs = await _get_embeddings()

        # ── Evaluate with current production weights ──────────────────────
        profile_results, avg_metrics = self._eval_weights(
            profile_embs, opp_embs, SEMANTIC_WEIGHT, SKILL_WEIGHT
        )

        # ── Weight grid search ────────────────────────────────────────────
        weight_candidates: list[WeightSearchResult] = []
        for sem_100 in range(40, 95, 5):          # 0.40 → 0.90 in 0.05 steps
            sem_w = sem_100 / 100
            skill_w = round(1.0 - sem_w, 2)
            _, m = self._eval_weights(profile_embs, opp_embs, sem_w, skill_w)
            weight_candidates.append(WeightSearchResult(sem_w, skill_w, m["ndcg_at_5"]))

        best = max(weight_candidates, key=lambda x: x.ndcg_at_5)
        current_ndcg5 = avg_metrics["ndcg_at_5"]
        gain = best.ndcg_at_5 - current_ndcg5
        gain_pct = (gain / current_ndcg5 * 100) if current_ndcg5 > 0 else 0.0

        if gain_pct > 1.0:
            rec = (
                f"Consider updating SEMANTIC_WEIGHT={best.semantic_weight}, "
                f"SKILL_WEIGHT={best.skill_weight} — "
                f"NDCG@5 improves from {current_ndcg5:.3f} to {best.ndcg_at_5:.3f} "
                f"(+{gain_pct:.1f}%)."
            )
        else:
            rec = (
                f"Current weights SEMANTIC={SEMANTIC_WEIGHT}, SKILL={SKILL_WEIGHT} are "
                f"near-optimal — grid search found ≤1% NDCG@5 improvement available."
            )

        # ── Regression detection ──────────────────────────────────────────
        regression = _prev_ndcg5 is not None and (current_ndcg5 < _prev_ndcg5 - 0.02)
        prev = _prev_ndcg5
        _prev_ndcg5 = current_ndcg5

        # ── Health signal ─────────────────────────────────────────────────
        if regression:
            health = "needs_attention"
        elif current_ndcg5 >= 0.75:
            health = "good"
        else:
            health = "needs_attention"

        return MatchingEvalResult(
            ndcg_at_3=avg_metrics["ndcg_at_3"],
            ndcg_at_5=avg_metrics["ndcg_at_5"],
            precision_at_3=avg_metrics["precision_at_3"],
            mrr=avg_metrics["mrr"],
            current_weights={"semantic": SEMANTIC_WEIGHT, "skill": SKILL_WEIGHT},
            optimal_weights={"semantic": best.semantic_weight, "skill": best.skill_weight},
            optimal_ndcg_at_5=best.ndcg_at_5,
            weight_gain_pct=round(gain_pct, 2),
            weight_recommendation=rec,
            profile_breakdown=profile_results,
            regression_detected=regression,
            previous_ndcg_at_5=prev,
            health=health,
            run_at=datetime.now(UTC).isoformat(),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _eval_weights(
        self,
        profile_embs: list[list[float]],
        opp_embs: list[list[float]],
        sem_w: float,
        skill_w: float,
    ) -> tuple[list[ProfileResult], dict[str, float]]:
        profile_results: list[ProfileResult] = []
        ndcg3_sum = ndcg5_sum = prec3_sum = mrr_sum = 0.0

        for p_idx, (p_emb, profile) in enumerate(zip(profile_embs, GOLDEN_PROFILES)):
            ranked_opp_idxs = _rank_opps_for_profile(
                p_emb, opp_embs, profile["skills"], sem_w, skill_w
            )
            ranked_rels = [RELEVANCE[p_idx][j] for j in ranked_opp_idxs]

            n3 = ndcg_at_k(ranked_rels, k=3)
            n5 = ndcg_at_k(ranked_rels, k=5)
            p3 = precision_at_k(ranked_rels, k=3)
            m = mrr(ranked_rels)

            top_opp_idx = ranked_opp_idxs[0]
            ideal_opp_idx = RELEVANCE[p_idx].index(max(RELEVANCE[p_idx]))

            profile_results.append(ProfileResult(
                profile_id=profile["id"],
                label=profile["label"],
                ndcg_at_3=round(n3, 4),
                ndcg_at_5=round(n5, 4),
                precision_at_3=round(p3, 4),
                mrr=round(m, 4),
                top_match_label=GOLDEN_OPPORTUNITIES[top_opp_idx]["label"],
                top_match_is_correct=(top_opp_idx == ideal_opp_idx),
            ))
            ndcg3_sum += n3; ndcg5_sum += n5; prec3_sum += p3; mrr_sum += m

        n = len(GOLDEN_PROFILES)
        return profile_results, {
            "ndcg_at_3": round(ndcg3_sum / n, 4),
            "ndcg_at_5": round(ndcg5_sum / n, 4),
            "precision_at_3": round(prec3_sum / n, 4),
            "mrr": round(mrr_sum / n, 4),
        }
