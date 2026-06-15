"""Module 10 — Evaluation Service (Platform IQ).

Honesty contract:
  evaluate_now():  scores ALL (application, outcome) pairs using the predictions
                   that were snapshotted BEFORE outcomes were known (Module 7).
                   Every pair is out-of-sample by construction.
                   Reports response-calibration metrics + ghost P/R/F1 (stable,
                   rule-based shield — computed once on the full set).

  build_history(): FIXED-TEST-SET LEARNING CURVE.
                   Splits all pairs 70/30 by recorded_at (temporal order).
                   Trains a LogisticRegression calibrator on N_PREFIXES GROWING
                   PREFIXES of the 70% training pool, always predicting the SAME
                   held-out test set.  Plots how response-calibration accuracy
                   improves as the cohort accumulates more outcome data.

                   IQ trend formula (documented for reproducibility):
                     IQ_k = 100 × (1 − Brier_on_fixed_test)
                   This tracks the component that genuinely learns from outcomes.
                   Ghost P/R/F1 is reported per checkpoint but excluded from
                   the trend value (the ghost shield is rule-based, not trained).

                   Train and test sets are ASSERTED disjoint (no leakage ever).

Platform IQ formula (evaluate_now only):
  IQ = 100 × (W_RESP × (1 − brier) + W_GHOST × ghost_f1)
  W_RESP = 0.6, W_GHOST = 0.4, clamped to [0, 100].
  A null component contributes 0 (honest: missing data = no credit).
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    brier_score_loss,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.application import Application
from app.models.evaluation import Evaluation
from app.models.outcome import Outcome

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants (documented in module docstring)
# ---------------------------------------------------------------------------

W_RESP: float = 0.6
W_GHOST: float = 0.4

# Fraction of (application, outcome) pairs reserved as the fixed held-out test set
TEST_FRAC: float = 0.30

# Number of growing-prefix checkpoints on the training pool
N_PREFIXES: int = 8

# Minimum total pairs before build_history() will run
MIN_TOTAL: int = 30

# ---------------------------------------------------------------------------
# Pure-function scoring (fully testable without DB)
# ---------------------------------------------------------------------------


@dataclass
class MetricResult:
    response_brier: float
    response_auc: float | None
    response_accuracy: float
    ghost_precision: float
    ghost_recall: float
    ghost_f1: float
    insufficient: bool = False


def score(
    response_probs: list[float],
    ghost_preds: list[bool],
    responded_actuals: list[bool],
) -> MetricResult:
    """Compute all accuracy metrics for a set of (prediction, actual) pairs.

    response_probs   : predicted_response_prob per application
    ghost_preds      : snapshotted predicted_ghost per application
    responded_actuals: actual outcome.responded (True = company replied)

    ghost_actual = NOT responded (ghosted = company never replied).
    """
    n = len(response_probs)
    if n < 2:  # noqa: PLR2004
        return MetricResult(
            response_brier=0.0,
            response_auc=None,
            response_accuracy=0.0,
            ghost_precision=0.0,
            ghost_recall=0.0,
            ghost_f1=0.0,
            insufficient=True,
        )

    y_resp = [int(r) for r in responded_actuals]
    y_ghost = [int(not r) for r in responded_actuals]
    g_preds = [int(g) for g in ghost_preds]
    preds_binary = [1 if p >= 0.5 else 0 for p in response_probs]  # noqa: PLR2004

    brier = float(brier_score_loss(y_resp, response_probs))
    accuracy = float(accuracy_score(y_resp, preds_binary))

    if len(set(y_resp)) < 2:  # noqa: PLR2004
        auc: float | None = None
    else:
        try:
            auc = float(roc_auc_score(y_resp, response_probs))
        except ValueError:
            auc = None

    gp = float(precision_score(y_ghost, g_preds, zero_division=0.0))
    gr = float(recall_score(y_ghost, g_preds, zero_division=0.0))
    gf = float(f1_score(y_ghost, g_preds, zero_division=0.0))

    return MetricResult(
        response_brier=brier,
        response_auc=auc,
        response_accuracy=accuracy,
        ghost_precision=gp,
        ghost_recall=gr,
        ghost_f1=gf,
    )


def platform_iq(metrics: MetricResult) -> float:
    """evaluate_now() IQ: 100×(W_RESP×(1−brier)+W_GHOST×ghost_f1), clamped [0,100].

    Null component contributes 0 (honest: no data = no credit).
    """
    resp = 1.0 - metrics.response_brier if not metrics.insufficient else 0.0
    ghost = metrics.ghost_f1 if not metrics.insufficient else 0.0
    return max(0.0, min(100.0, 100.0 * (W_RESP * resp + W_GHOST * ghost)))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _dedupe_latest(
    rows: list[tuple[Any, Any]],
) -> list[tuple[Application, Outcome]]:
    """Keep the latest Outcome per Application (one outcome per application)."""
    seen: dict[uuid.UUID, tuple[Application, Outcome]] = {}
    for app, outcome in rows:
        if app.id not in seen or outcome.recorded_at > seen[app.id][1].recorded_at:
            seen[app.id] = (app, outcome)
    return sorted(seen.values(), key=lambda x: x[1].recorded_at)


def _calibrate_and_predict(
    train_pairs: list[tuple[Application, Outcome]],
    eval_pairs: list[tuple[Application, Outcome]],
) -> list[float]:
    """Platt-scale the snapshotted response scores using a LogisticRegression.

    Features: [predicted_response_prob, int(predicted_ghost)]
    Labels:   int(outcome.responded)

    If training set has only one class, falls back to the training base rate.
    """
    x_train = [
        [a.predicted_response_prob, int(a.predicted_ghost)]
        for a, _ in train_pairs
    ]
    y_train = [int(o.responded) for _, o in train_pairs]
    x_eval = [
        [a.predicted_response_prob, int(a.predicted_ghost)]
        for a, _ in eval_pairs
    ]

    classes = set(y_train)
    if len(classes) < 2:  # noqa: PLR2004
        base_rate = sum(y_train) / len(y_train)
        return [base_rate] * len(eval_pairs)

    clf = LogisticRegression(max_iter=500, random_state=42)
    clf.fit(x_train, y_train)
    proba = clf.predict_proba(x_eval)
    class_list = list(clf.classes_)
    idx = class_list.index(1) if 1 in class_list else 0
    return [float(p) for p in proba[:, idx]]


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class EvaluationService:
    """GLOBAL service — no user_id.  Reads all applications+outcomes."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _fetch_all_pairs(self) -> list[tuple[Application, Outcome]]:
        """Load all (Application, Outcome) pairs, sorted by recorded_at then id."""
        raw = (
            await self.db.execute(
                select(Application, Outcome)
                .join(Outcome, Outcome.application_id == Application.id)
                .order_by(Outcome.recorded_at.asc(), Application.id.asc())
            )
        ).all()
        return _dedupe_latest([(r[0], r[1]) for r in raw])

    def _persist(
        self,
        m: MetricResult,
        iq: float,
        n: int,
        run_at: datetime,
        version: str,
    ) -> Evaluation:
        row = Evaluation(
            run_at=run_at,
            n_outcomes=n,
            response_brier=m.response_brier,
            response_auc=m.response_auc,
            response_accuracy=m.response_accuracy,
            ghost_precision=m.ghost_precision,
            ghost_recall=m.ghost_recall,
            ghost_f1=m.ghost_f1,
            platform_iq=iq,
            model_version=version if not m.insufficient else "insufficient_data",
        )
        self.db.add(row)
        return row

    async def evaluate_now(self) -> Evaluation:
        """Score ALL applications against their snapshotted predictions.

        This is always out-of-sample: predictions were written before outcomes existed.
        Reports response-calibration metrics + stable ghost P/R/F1 on the full set.
        """
        pairs = await self._fetch_all_pairs()

        if not pairs:
            row = self._persist(
                MetricResult(0.0, None, 0.0, 0.0, 0.0, 0.0, insufficient=True),
                iq=0.0,
                n=0,
                run_at=datetime.now(UTC),
                version="insufficient_data",
            )
            await self.db.commit()
            await self.db.refresh(row)
            return row

        response_probs = [a.predicted_response_prob for a, _ in pairs]
        ghost_preds = [a.predicted_ghost for a, _ in pairs]
        responded_actuals = [bool(o.responded) for _, o in pairs]

        m = score(response_probs, ghost_preds, responded_actuals)
        iq = platform_iq(m)
        row = self._persist(m, iq, len(pairs), datetime.now(UTC), "formula_v1")
        await self.db.commit()
        await self.db.refresh(row)
        logger.info(
            "evaluate_now: n=%d brier=%.4f auc=%s ghost_f1=%.4f iq=%.2f",
            len(pairs), m.response_brier, m.response_auc, m.ghost_f1, iq,
        )
        return row

    async def build_history(self) -> list[Evaluation]:
        """Fixed-test-set learning curve (N_PREFIXES checkpoints).

        Splits all (application, outcome) pairs 70/30 by recorded_at:
          - Last TEST_FRAC = fixed held-out test set (never trained on).
          - Remaining 70% = training pool.

        Trains N_PREFIXES growing prefixes of the pool (1/N .. N/N of pool size),
        always predicting the SAME fixed test set.

        IQ trend formula: IQ_k = 100 × (1 − Brier_on_fixed_test), clamped [0, 100].
        Tracks response-calibration improvement — the metric that genuinely learns.

        Train/test disjointness is ASSERTED for every prefix (no leakage ever).
        Returns all N_PREFIXES checkpoint rows in temporal order.
        """
        pairs = await self._fetch_all_pairs()
        n = len(pairs)

        if n < MIN_TOTAL:
            logger.warning(
                "build_history: only %d pairs — need at least %d for a learning curve",
                n, MIN_TOTAL,
            )
            return []

        test_n = max(5, int(n * TEST_FRAC))
        train_pool = pairs[:-test_n]
        test_set = pairs[-test_n:]

        # Honesty guardrail: fixed test set must be disjoint from the entire training pool
        train_ids = {a.id for a, _ in train_pool}
        test_ids = {a.id for a, _ in test_set}
        assert not (train_ids & test_ids), (
            f"build_history: train/test overlap! IDs: {train_ids & test_ids}"
        )

        rows: list[Evaluation] = []
        base_run_at = datetime.now(UTC)

        for k in range(1, N_PREFIXES + 1):
            prefix_n = max(2, len(train_pool) * k // N_PREFIXES)
            prefix = train_pool[:prefix_n]

            # Guardrail: each prefix must also be disjoint from the test set
            prefix_ids = {a.id for a, _ in prefix}
            assert not (prefix_ids & test_ids), (
                f"build_history: prefix k={k} overlaps test set! IDs: {prefix_ids & test_ids}"
            )

            calibrated = _calibrate_and_predict(prefix, test_set)
            ghost_preds_test = [a.predicted_ghost for a, _ in test_set]
            responded_test = [bool(o.responded) for _, o in test_set]

            m = score(calibrated, ghost_preds_test, responded_test)

            # IQ trend = response-calibration score (the component that trains on outcomes)
            iq = (
                max(0.0, min(100.0, 100.0 * (1.0 - m.response_brier)))
                if not m.insufficient
                else 0.0
            )

            version = f"logreg_n{prefix_n}"
            # Use microsecond offset so get_history_rows() ORDER BY run_at is stable
            row = self._persist(m, iq, prefix_n, base_run_at + timedelta(microseconds=k), version)
            rows.append(row)
            logger.info(
                "build_history: k=%d prefix_n=%d brier=%s iq=%.2f",
                k, prefix_n,
                f"{m.response_brier:.4f}" if not m.insufficient else "N/A",
                iq,
            )

        if rows:
            await self.db.commit()
            for r in rows:
                await self.db.refresh(r)

        return rows

    async def get_latest_formula(self) -> Evaluation | None:
        """Most recent evaluate_now() row (formula_v1 or insufficient_data)."""
        return (
            await self.db.execute(
                select(Evaluation)
                .where(~Evaluation.model_version.like("logreg_%"))
                .order_by(Evaluation.run_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    async def get_history_rows(self) -> list[Evaluation]:
        """All build_history() checkpoint rows, ordered by run_at."""
        return list(
            (
                await self.db.execute(
                    select(Evaluation)
                    .where(Evaluation.model_version.like("logreg_%"))
                    .order_by(Evaluation.run_at.asc())
                )
            )
            .scalars()
            .all()
        )
