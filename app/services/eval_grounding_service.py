"""Grounding score calibration evaluation.

Uses live production data (pitch artifacts + research outreach outcomes) to answer:

  1. Calibration — does a higher grounding_score actually predict a higher professor
     reply rate?  Measured by Spearman ρ (monotonic correlation) and ECE (Expected
     Calibration Error, the gap between predicted confidence and actual accuracy).

  2. Threshold optimisation — what value of GROUNDING_THRESHOLD maximises F1 when
     treating grounding_score as a binary predictor of "professor will reply"?
     Currently hardcoded at 0.7; this service finds the data-driven optimum.

  3. Bucket analysis — breaks scores into four intuitive bands so a human reader
     can spot systematic over- or under-confidence at a glance.

  4. Statistical significance — reports whether the correlation is unlikely to be
     random (p < 0.05), so the team knows whether to trust the recommendation.

Data pipeline:
  research_pitch Artifact  →  ResearchOutreach (via pitch_artifact_id)
                                   ↓
          terminal status only: replied/accepted → responded=1
                                 declined/no_response → responded=0
          pending (suggested/drafted/contacted) → excluded (outcome unknown)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.artifact import Artifact
from app.models.research_outreach import ResearchOutreach
from app.services.research_service import GROUNDING_THRESHOLD

logger = logging.getLogger(__name__)

_TERMINAL_RESPONDED = frozenset({"replied", "accepted"})
_TERMINAL_NOT_RESPONDED = frozenset({"declined", "no_response"})
_MIN_SAMPLES = 10

# Bucket boundaries for the human-readable breakdown
_BUCKETS: list[tuple[float, float, str]] = [
    (0.0,  0.3,  "[0.00, 0.30)"),
    (0.3,  0.5,  "[0.30, 0.50)"),
    (0.5,  0.7,  "[0.50, 0.70)"),
    (0.7,  1.01, "[0.70, 1.00]"),
]


# ---------------------------------------------------------------------------
# Pure metric functions (fully testable without DB)
# ---------------------------------------------------------------------------


def ece(scores: list[float], actuals: list[int], n_bins: int = 10) -> float:
    """Expected Calibration Error — mean absolute gap between confidence and accuracy."""
    n = len(scores)
    if n == 0:
        return 0.0
    total = 0.0
    for b in range(n_bins):
        lo, hi = b / n_bins, (b + 1) / n_bins
        idx = [i for i, s in enumerate(scores) if lo <= s < hi]
        if b == n_bins - 1:
            idx = [i for i, s in enumerate(scores) if lo <= s <= 1.0]
        if not idx:
            continue
        mean_conf = sum(scores[i] for i in idx) / len(idx)
        mean_acc = sum(actuals[i] for i in idx) / len(idx)
        total += (len(idx) / n) * abs(mean_conf - mean_acc)
    return round(total, 4)


def find_optimal_threshold(scores: list[float], actuals: list[int]) -> tuple[float, float, float]:
    """Grid-search threshold ∈ [0.30, 0.90] maximising F1.

    Returns (optimal_threshold, optimal_f1, current_threshold_f1).
    """
    def _f1_at(t: float) -> float:
        tp = sum(1 for s, a in zip(scores, actuals) if s >= t and a == 1)
        fp = sum(1 for s, a in zip(scores, actuals) if s >= t and a == 0)
        fn = sum(1 for s, a in zip(scores, actuals) if s < t and a == 1)
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        return 2 * prec * rec / (prec + rec) if prec + rec else 0.0

    best_f1, best_t = 0.0, 0.5
    for t_int in range(30, 91, 5):
        t = t_int / 100
        f = _f1_at(t)
        if f > best_f1:
            best_f1, best_t = f, t

    current_f1 = _f1_at(GROUNDING_THRESHOLD)
    return round(best_t, 2), round(best_f1, 4), round(current_f1, 4)


def spearman_rho(scores: list[float], actuals: list[int]) -> tuple[float, float]:
    """Spearman ρ and two-sided p-value.  Returns (rho, p_value)."""
    import math
    import warnings
    from scipy.stats import spearmanr
    if len(scores) < 3:  # noqa: PLR2004
        return 0.0, 1.0
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        rho_raw, p_raw = spearmanr(scores, actuals)
    rho_f = 0.0 if (not isinstance(rho_raw, float) or math.isnan(rho_raw)) else float(rho_raw)
    p_f = 1.0 if (not isinstance(p_raw, float) or math.isnan(p_raw)) else float(p_raw)
    return round(rho_f, 4), round(p_f, 4)


def bucket_analysis(
    scores: list[float], actuals: list[int]
) -> list[dict]:
    """Group (score, actual) pairs into four bands; report count and response rate per band."""
    rows = []
    for lo, hi, label in _BUCKETS:
        idx = [i for i, s in enumerate(scores) if lo <= s < hi]
        if lo == 0.7:
            idx = [i for i, s in enumerate(scores) if 0.7 <= s <= 1.0]
        n = len(idx)
        rate = sum(actuals[i] for i in idx) / n if n else None
        rows.append({
            "bucket": label,
            "n": n,
            "response_rate": round(rate, 3) if rate is not None else None,
        })
    return rows


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class GroundingCalibrationResult:
    n_pitches: int
    n_with_outcomes: int
    spearman_rho: float
    spearman_p_value: float
    is_predictive: bool
    ece: float
    current_threshold: float
    optimal_threshold: float
    f1_at_current: float
    f1_at_optimal: float
    threshold_recommendation: str
    bucket_analysis: list[dict]
    health: str  # "good" | "needs_attention" | "insufficient_data"
    run_at: str


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class EvalGroundingService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def run_calibration(self) -> GroundingCalibrationResult:
        from datetime import UTC, datetime

        rows = await self._fetch_pairs()
        n_pitches = await self._count_pitches()

        if len(rows) < _MIN_SAMPLES:
            return GroundingCalibrationResult(
                n_pitches=n_pitches,
                n_with_outcomes=len(rows),
                spearman_rho=0.0,
                spearman_p_value=1.0,
                is_predictive=False,
                ece=0.0,
                current_threshold=GROUNDING_THRESHOLD,
                optimal_threshold=GROUNDING_THRESHOLD,
                f1_at_current=0.0,
                f1_at_optimal=0.0,
                threshold_recommendation=(
                    f"Not enough terminal outcomes yet ({len(rows)}/{_MIN_SAMPLES} minimum). "
                    "Keep grounding threshold at the current value and revisit after more pitches reach a terminal state."
                ),
                bucket_analysis=bucket_analysis([], []),
                health="insufficient_data",
                run_at=datetime.now(UTC).isoformat(),
            )

        scores = [r[0] for r in rows]
        actuals = [r[1] for r in rows]

        rho, p_val = spearman_rho(scores, actuals)
        is_predictive = p_val < 0.05 and rho > 0.1  # noqa: PLR2004
        ece_val = ece(scores, actuals)
        opt_t, f1_opt, f1_cur = find_optimal_threshold(scores, actuals)
        buckets = bucket_analysis(scores, actuals)

        f1_gain = f1_opt - f1_cur
        if not is_predictive:
            rec = (
                f"Grounding score is NOT a statistically significant predictor of replies "
                f"(Spearman ρ={rho:+.2f}, p={p_val:.3f}). "
                "Consider revisiting the grounding formula or wait for more data."
            )
            health = "needs_attention"
        elif abs(opt_t - GROUNDING_THRESHOLD) < 0.05 or f1_gain < 0.03:  # noqa: PLR2004
            rec = (
                f"Current threshold={GROUNDING_THRESHOLD} is near-optimal "
                f"(F1={f1_cur:.3f}; optimal={opt_t} gives F1={f1_opt:.3f}, Δ={f1_gain:+.3f}). "
                f"Grounding score is predictive (ρ={rho:+.2f}, p={p_val:.3f})."
            )
            health = "good"
        else:
            rec = (
                f"Set GROUNDING_THRESHOLD={opt_t} to improve F1 from "
                f"{f1_cur:.3f} → {f1_opt:.3f} (+{f1_gain:.3f}). "
                f"Grounding score is predictive (ρ={rho:+.2f}, p={p_val:.3f}, ECE={ece_val:.3f})."
            )
            health = "needs_attention"

        logger.info(
            "grounding_calibration: n=%d rho=%.3f p=%.3f ece=%.3f opt_t=%.2f f1_opt=%.3f",
            len(rows), rho, p_val, ece_val, opt_t, f1_opt,
        )

        return GroundingCalibrationResult(
            n_pitches=n_pitches,
            n_with_outcomes=len(rows),
            spearman_rho=rho,
            spearman_p_value=p_val,
            is_predictive=is_predictive,
            ece=ece_val,
            current_threshold=GROUNDING_THRESHOLD,
            optimal_threshold=opt_t,
            f1_at_current=f1_cur,
            f1_at_optimal=f1_opt,
            threshold_recommendation=rec,
            bucket_analysis=buckets,
            health=health,
            run_at=datetime.now(UTC).isoformat(),
        )

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------

    async def _count_pitches(self) -> int:
        from sqlalchemy import func
        return (
            await self.db.execute(
                select(func.count()).select_from(Artifact).where(
                    Artifact.type == "research_pitch",
                    Artifact.grounding_score.is_not(None),
                )
            )
        ).scalar_one()

    async def _fetch_pairs(self) -> list[tuple[float, int]]:
        """Return (grounding_score, responded) for terminal-state outreach only."""
        rows = (
            await self.db.execute(
                select(Artifact.grounding_score, ResearchOutreach.status)
                .join(
                    ResearchOutreach,
                    ResearchOutreach.pitch_artifact_id == Artifact.id,
                )
                .where(
                    Artifact.type == "research_pitch",
                    Artifact.grounding_score.is_not(None),
                    ResearchOutreach.status.in_(
                        list(_TERMINAL_RESPONDED | _TERMINAL_NOT_RESPONDED)
                    ),
                )
            )
        ).all()
        result: list[tuple[float, int]] = []
        for gs, status in rows:
            if gs is None:
                continue
            responded = 1 if status in _TERMINAL_RESPONDED else 0
            result.append((float(gs), responded))
        return result
