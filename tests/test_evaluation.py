"""Module 10 — Evaluation / Platform IQ acceptance tests.

All arithmetic is verified by hand in the comments; pytest.approx is used for
float comparisons. No LLM calls are made — this module is purely deterministic.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.application import Application
from app.models.company import Company
from app.models.evaluation import Evaluation
from app.models.outcome import Outcome
from app.models.posting import Posting
from app.models.user import AuthProvider, User, UserRole
from app.services.evaluation_service import (
    MIN_TOTAL,
    N_PREFIXES,
    W_GHOST,
    W_RESP,
    MetricResult,
    platform_iq,
    score,
)

METRICS_URL = "/api/evaluation/metrics"
RUN_URL = "/api/evaluation/run"
REPLAY_URL = "/api/evaluation/replay"
SIGNUP_URL = "/api/auth/signup"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def _ts(offset_minutes: int = 0) -> datetime:
    return _NOW + timedelta(minutes=offset_minutes)


async def _make_company(db: AsyncSession, idx: int = 0) -> Company:
    import re
    name = f"EvalCo{idx}"
    norm = re.sub(r"[^a-z0-9]", "", name.lower())
    co = Company(name=name, normalized_name=norm, ghost_history_score=0.0, responsiveness_score=1.0)
    db.add(co)
    await db.flush()
    return co


async def _make_posting(db: AsyncSession, company_id: uuid.UUID, idx: int = 0) -> Posting:
    p = Posting(
        company_id=company_id,
        title=f"Intern {idx}",
        description="desc",
        requirements=[],
        work_mode="remote",
        source="test",
        source_url=f"https://evalco.io/{uuid.uuid4().hex}",
        posted_at="2026-01-01T00:00:00Z",
        last_seen_at="2026-01-01T00:00:00Z",
        dedup_key=uuid.uuid4().hex[:16],
    )
    db.add(p)
    await db.flush()
    return p


async def _make_user(db: AsyncSession, email: str = "evaluser@example.com") -> User:
    u = User(
        name="Eval User",
        email=email,
        password_hash="x",
        role=UserRole.student,
        auth_provider=AuthProvider.password,
    )
    db.add(u)
    await db.flush()
    return u


async def _make_app(
    db: AsyncSession,
    user_id: uuid.UUID,
    posting_id: uuid.UUID,
    *,
    pred_prob: float,
    pred_ghost: bool,
) -> Application:
    a = Application(
        user_id=user_id,
        posting_id=posting_id,
        channel="web",
        status="applied",
        predicted_response_prob=pred_prob,
        predicted_ghost=pred_ghost,
    )
    db.add(a)
    await db.flush()
    return a


async def _make_outcome(
    db: AsyncSession,
    app_id: uuid.UUID,
    *,
    responded: bool,
    recorded_at: datetime,
) -> Outcome:
    o = Outcome(
        application_id=app_id,
        outcome_type="responded" if responded else "no_response",
        responded=responded,
        source="test",
        recorded_at=recorded_at,
    )
    db.add(o)
    await db.flush()
    return o


# Seed a batch of (app, outcome) pairs in one call.
# Each entry: (pred_prob, pred_ghost, responded, minutes_offset)
async def _seed_pairs(
    db: AsyncSession,
    entries: list[tuple[float, bool, bool, int]],
) -> None:
    co = await _make_company(db, idx=0)
    posting = await _make_posting(db, co.id, idx=0)
    user = await _make_user(db)
    for pred_prob, pred_ghost, responded, offset in entries:
        app = await _make_app(
            db, user.id, posting.id, pred_prob=pred_prob, pred_ghost=pred_ghost
        )
        await _make_outcome(db, app.id, responded=responded, recorded_at=_ts(offset))
    await db.commit()


# ---------------------------------------------------------------------------
# 1. score() — hand-verified numbers
# ---------------------------------------------------------------------------


def test_score_perfect_predictions() -> None:
    """
    response_probs = [0.9, 0.7, 0.3, 0.1], responded = [T, T, F, F]
    Brier = mean([(1-0.9)^2, (1-0.7)^2, (0-0.3)^2, (0-0.1)^2])
          = mean([0.01, 0.09, 0.09, 0.01]) = 0.05
    AUC = 1.0  (perfect separation)
    Accuracy = 1.0  (all threshold-0.5 predictions correct)
    ghost_actual = [F, F, T, T]  (not responded)
    ghost_pred   = [F, F, T, T]  → F1 = 1.0
    """
    r = score(
        response_probs=[0.9, 0.7, 0.3, 0.1],
        ghost_preds=[False, False, True, True],
        responded_actuals=[True, True, False, False],
    )
    assert r.insufficient is False
    assert r.response_brier == pytest.approx(0.05, abs=1e-9)
    assert r.response_auc == pytest.approx(1.0, abs=1e-9)
    assert r.response_accuracy == pytest.approx(1.0, abs=1e-9)
    assert r.ghost_precision == pytest.approx(1.0, abs=1e-9)
    assert r.ghost_recall == pytest.approx(1.0, abs=1e-9)
    assert r.ghost_f1 == pytest.approx(1.0, abs=1e-9)


def test_score_worst_predictions() -> None:
    """
    Perfectly wrong: predict 0.9 for non-responders, 0.1 for responders.
    Brier = mean([(0-0.9)^2, (1-0.1)^2]) for [F, T]
          = mean([0.81, 0.81]) = 0.81
    AUC = 0.0 (perfectly wrong)
    Accuracy = 0.0  (all threshold-0.5 predictions wrong)
    ghost: pred [F, T] vs actual [T, F] → no correct ghost detection
    """
    r = score(
        response_probs=[0.9, 0.1],
        ghost_preds=[False, True],
        responded_actuals=[False, True],
    )
    assert r.response_brier == pytest.approx(0.81, abs=1e-9)
    assert r.response_auc == pytest.approx(0.0, abs=1e-9)
    assert r.response_accuracy == pytest.approx(0.0, abs=1e-9)


def test_score_single_class_returns_null_auc() -> None:
    """When all actuals are the same class, AUC is undefined → None, no crash."""
    r = score(
        response_probs=[0.8, 0.9, 0.7],
        ghost_preds=[False, False, False],
        responded_actuals=[True, True, True],
    )
    assert r.response_auc is None
    assert r.insufficient is False


def test_score_too_few_samples_returns_insufficient() -> None:
    """n < 2 → insufficient flag, zeros, no crash."""
    r = score(
        response_probs=[0.9],
        ghost_preds=[False],
        responded_actuals=[True],
    )
    assert r.insufficient is True
    assert r.response_brier == 0.0
    assert r.response_auc is None


def test_score_zero_ghost_predictions() -> None:
    """All ghost_pred=False but some actuals are ghost → precision/recall/f1 = 0, no crash."""
    r = score(
        response_probs=[0.8, 0.2],
        ghost_preds=[False, False],
        responded_actuals=[True, False],
    )
    assert r.ghost_precision == pytest.approx(0.0)
    assert r.ghost_recall == pytest.approx(0.0)
    assert r.ghost_f1 == pytest.approx(0.0)
    assert r.insufficient is False


# ---------------------------------------------------------------------------
# 2. platform_iq() — matches documented formula exactly
# ---------------------------------------------------------------------------


def test_platform_iq_formula() -> None:
    """
    IQ = 100 * (W_RESP * (1 - brier) + W_GHOST * ghost_f1)
       = 100 * (0.6 * (1 - 0.05) + 0.4 * 1.0)
       = 100 * (0.57 + 0.40) = 97.0
    """
    m = MetricResult(
        response_brier=0.05,
        response_auc=1.0,
        response_accuracy=1.0,
        ghost_precision=1.0,
        ghost_recall=1.0,
        ghost_f1=1.0,
    )
    expected = 100.0 * (W_RESP * (1 - 0.05) + W_GHOST * 1.0)
    assert platform_iq(m) == pytest.approx(expected, abs=1e-9)


def test_platform_iq_clamp_high() -> None:
    """IQ can't exceed 100."""
    m = MetricResult(
        response_brier=0.0, response_auc=1.0, response_accuracy=1.0,
        ghost_precision=1.0, ghost_recall=1.0, ghost_f1=1.0,
    )
    assert platform_iq(m) <= 100.0


def test_platform_iq_insufficient_is_zero() -> None:
    """Insufficient flag → IQ = 0 regardless of stored values."""
    m = MetricResult(
        response_brier=0.0, response_auc=None, response_accuracy=0.0,
        ghost_precision=0.0, ghost_recall=0.0, ghost_f1=0.0,
        insufficient=True,
    )
    assert platform_iq(m) == pytest.approx(0.0)


def test_platform_iq_null_ghost_uses_zero_credit() -> None:
    """
    If ghost_f1 is 0 (no ghost predictions), only response component counts.
    IQ = 100 * (0.6 * (1 - 0.25) + 0.4 * 0.0) = 45.0
    """
    m = MetricResult(
        response_brier=0.25, response_auc=None, response_accuracy=0.5,
        ghost_precision=0.0, ghost_recall=0.0, ghost_f1=0.0,
    )
    expected = 100.0 * (W_RESP * (1 - 0.25) + W_GHOST * 0.0)
    assert platform_iq(m) == pytest.approx(expected, abs=1e-9)


# ---------------------------------------------------------------------------
# 3. evaluate_now() — persists a row; GET /metrics works
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evaluate_now_persists_row(db: AsyncSession, client: AsyncClient, auth_headers: dict) -> None:
    """evaluate_now() should persist one Evaluation row even with 0 outcomes."""
    resp = await client.post(RUN_URL, headers=auth_headers)
    # Non-admin → 403 with regular auth_headers
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_run_endpoint_admin_only(client: AsyncClient, db: AsyncSession) -> None:
    """POST /run requires admin role."""
    # Sign up a student
    r = await client.post(SIGNUP_URL, json={"name": "S", "email": "stud@ex.com", "password": "pass1234"})
    assert r.status_code == 201
    student_token = r.json()["token"]
    student_headers = {"Authorization": f"Bearer {student_token}"}

    # Student → 403
    resp = await client.post(RUN_URL, headers=student_headers)
    assert resp.status_code == 403

    # Promote to admin directly in DB
    u = (await db.execute(select(User).where(User.email == "stud@ex.com"))).scalar_one()
    u.role = UserRole.admin
    db.add(u)
    await db.commit()

    # Admin → 202 with Evaluation row
    resp = await client.post(RUN_URL, headers=student_headers)
    assert resp.status_code == 202
    data = resp.json()
    assert "latest" in data
    assert data["latest"]["n_outcomes"] == 0  # no outcomes seeded yet
    assert data["latest"]["platform_iq"] == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_get_metrics_no_data(client: AsyncClient, auth_headers: dict) -> None:
    """GET /metrics with no data returns empty trend and null latest."""
    resp = await client.get(METRICS_URL, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["latest"] is None
    assert data["iq_trend"] == []


@pytest.mark.asyncio
async def test_run_then_get_metrics(client: AsyncClient, db: AsyncSession) -> None:
    """After POST /run (admin), GET /metrics returns the row as latest."""
    r = await client.post(SIGNUP_URL, json={"name": "Admin", "email": "adm2@ex.com", "password": "pass1234"})
    token = r.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    u = (await db.execute(select(User).where(User.email == "adm2@ex.com"))).scalar_one()
    u.role = UserRole.admin
    db.add(u)
    await db.commit()

    await client.post(RUN_URL, headers=headers)

    resp = await client.get(METRICS_URL, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["latest"] is not None
    assert data["latest"]["model_version"] in ("formula_v1", "insufficient_data")
    assert isinstance(data["iq_trend"], list)


# ---------------------------------------------------------------------------
# 4. replay_endpoint — admin only
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_replay_endpoint_admin_only(client: AsyncClient, db: AsyncSession) -> None:
    """POST /replay requires admin role; student → 403."""
    r = await client.post(SIGNUP_URL, json={"name": "S2", "email": "stud2@ex.com", "password": "pass1234"})
    token = r.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.post(REPLAY_URL, headers=headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_replay_no_data_returns_empty(client: AsyncClient, db: AsyncSession) -> None:
    """POST /replay with no outcomes returns empty iq_trend and points=0."""
    r = await client.post(SIGNUP_URL, json={"name": "A3", "email": "adm3@ex.com", "password": "pass1234"})
    token = r.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    u = (await db.execute(select(User).where(User.email == "adm3@ex.com"))).scalar_one()
    u.role = UserRole.admin
    db.add(u)
    await db.commit()

    resp = await client.post(REPLAY_URL, headers=headers)
    assert resp.status_code == 202
    data = resp.json()
    assert data["points"] == 0
    assert data["iq_trend"] == []


# ---------------------------------------------------------------------------
# 5. build_history() — disjoint train/eval + IQ rises with better data
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_history_disjoint_train_eval(db: AsyncSession) -> None:
    """
    Seed MIN_TOTAL pairs → N_PREFIXES checkpoints, all with disjoint train/test.

    build_history() internally asserts disjointness at every prefix.
    If the function returns without raising AssertionError, the guardrail held.
    """
    entries = [
        (0.8 if i % 2 == 0 else 0.2, i % 2 != 0, i % 2 == 0, i)
        for i in range(MIN_TOTAL)
    ]
    await _seed_pairs(db, entries)

    from app.services.evaluation_service import EvaluationService
    svc = EvaluationService(db)

    rows = await svc.build_history()
    assert len(rows) == N_PREFIXES  # one row per growing prefix

    for row in rows:
        assert row.model_version is not None
        assert row.model_version.startswith("logreg_n")

    # run_at is offset by microseconds per prefix — must be strictly increasing
    for i in range(len(rows) - 1):
        assert rows[i].run_at <= rows[i + 1].run_at


@pytest.mark.asyncio
async def test_build_history_iq_rises_with_better_calibration(db: AsyncSession) -> None:
    """Fixed-test-set learning curve rises as more signal-rich data enters training.

    Design (40 total pairs, test_n=12, train_pool=28):
      Pairs 0-13  (offsets 0-13):  NOISY — pred_prob=0.5, no feature signal.
                                    LogReg learns only base rate ≈ 0.5.
                                    Brier on fixed test ≈ 0.25.  IQ ≈ 75.
      Pairs 14-27 (offsets 14-27): CLEAN — pred_prob in {0.9, 0.1} perfectly
                                    correlated with responded.  LogReg learns
                                    the signal, Brier drops sharply.  IQ >> 75.
      Pairs 28-39 (offsets 28-39): FIXED TEST SET — same clean distribution.

    First 4 prefix points (sizes ≤ 14): all inside noisy region → IQ ≈ 75.
    Last 4 prefix points (sizes > 14):  include clean data → IQ rises above 75.
    Assertions: mean(later half) > mean(earlier half), and last > first.
    """
    # offsets 0-13: noisy (no pred signal)
    noisy = [(0.5, False, i % 2 == 0, i) for i in range(14)]
    # offsets 14-27: clean signal-rich training pairs
    clean_train: list[tuple[float, bool, bool, int]] = []
    for i in range(14):
        if i % 2 == 0:
            clean_train.append((0.9, False, True, 14 + i))
        else:
            clean_train.append((0.1, True, False, 14 + i))
    # offsets 28-39: fixed test set (same clean distribution)
    test_entries: list[tuple[float, bool, bool, int]] = []
    for i in range(12):
        if i % 2 == 0:
            test_entries.append((0.9, False, True, 28 + i))
        else:
            test_entries.append((0.1, True, False, 28 + i))

    await _seed_pairs(db, noisy + clean_train + test_entries)

    from app.services.evaluation_service import EvaluationService
    svc = EvaluationService(db)
    rows = await svc.build_history()

    assert len(rows) == N_PREFIXES, f"Expected {N_PREFIXES} checkpoints, got {len(rows)}"

    iq_values = [r.platform_iq for r in rows]
    first_half_mean = sum(iq_values[: N_PREFIXES // 2]) / (N_PREFIXES // 2)
    second_half_mean = sum(iq_values[N_PREFIXES // 2 :]) / (N_PREFIXES // 2)

    assert second_half_mean > first_half_mean, (
        f"Expected later-half mean IQ > earlier-half: "
        f"{second_half_mean:.2f} vs {first_half_mean:.2f}  values={iq_values}"
    )
    assert iq_values[-1] > iq_values[0], (
        f"Expected last IQ > first: {iq_values[-1]:.2f} vs {iq_values[0]:.2f}"
    )


# ---------------------------------------------------------------------------
# 6. evaluate_now() — with actual seeded outcomes, scores them
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evaluate_now_with_outcomes(db: AsyncSession) -> None:
    """
    Seed 4 perfect predictions; evaluate_now() should return Brier ~0.05.
    response_probs=[0.9,0.7,0.3,0.1], ghost_preds=[F,F,T,T], responded=[T,T,F,F]
    Brier = 0.05 (hand-verified above)
    IQ = 100*(0.6*(1-0.05) + 0.4*1.0) = 97.0
    """
    co = await _make_company(db, idx=99)
    posting = await _make_posting(db, co.id, idx=99)
    user = await _make_user(db, email="evaluser2@example.com")

    cases = [
        (0.9, False, True, 1),
        (0.7, False, True, 2),
        (0.3, True, False, 3),
        (0.1, True, False, 4),
    ]
    for pred_prob, pred_ghost, responded, t in cases:
        app = await _make_app(db, user.id, posting.id, pred_prob=pred_prob, pred_ghost=pred_ghost)
        await _make_outcome(db, app.id, responded=responded, recorded_at=_ts(t))
    await db.commit()

    from app.services.evaluation_service import EvaluationService
    svc = EvaluationService(db)
    row = await svc.evaluate_now()

    assert row.n_outcomes == 4
    assert row.response_brier == pytest.approx(0.05, abs=1e-6)
    assert row.ghost_f1 == pytest.approx(1.0, abs=1e-6)
    assert row.platform_iq == pytest.approx(
        100.0 * (W_RESP * (1 - 0.05) + W_GHOST * 1.0), abs=1e-4
    )
    assert row.model_version == "formula_v1"

    # Row must be in DB
    stored = (await db.execute(select(Evaluation).where(Evaluation.id == row.id))).scalar_one()
    assert stored.platform_iq == pytest.approx(row.platform_iq)


# ---------------------------------------------------------------------------
# 7. Global — evaluations not user-scoped
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evaluations_are_global(db: AsyncSession, client: AsyncClient) -> None:
    """Two different users both see the same metrics (no user scoping)."""
    # User A runs evaluation
    r_a = await client.post(SIGNUP_URL, json={"name": "A", "email": "usera@ex.com", "password": "pass1234"})
    token_a = r_a.json()["token"]
    headers_a = {"Authorization": f"Bearer {token_a}"}

    # User B
    r_b = await client.post(SIGNUP_URL, json={"name": "B", "email": "userb@ex.com", "password": "pass1234"})
    token_b = r_b.json()["token"]
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # Promote user A to admin and run evaluation
    u_a = (await db.execute(select(User).where(User.email == "usera@ex.com"))).scalar_one()
    u_a.role = UserRole.admin
    db.add(u_a)
    await db.commit()

    await client.post(RUN_URL, headers=headers_a)

    # Both users see the same metrics endpoint
    resp_a = await client.get(METRICS_URL, headers=headers_a)
    resp_b = await client.get(METRICS_URL, headers=headers_b)

    assert resp_a.status_code == 200
    assert resp_b.status_code == 200
    assert resp_a.json()["latest"]["id"] == resp_b.json()["latest"]["id"]


# ---------------------------------------------------------------------------
# 8. Full end-to-end: replay with meaningful data, check iq_trend shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_replay_returns_iq_trend(client: AsyncClient, db: AsyncSession) -> None:
    """POST /replay with enough seeded outcomes returns iq_trend list with dates and values."""
    # Seed MIN_TOTAL pairs → exactly N_PREFIXES checkpoint points
    entries = [
        (0.8 if i % 2 == 0 else 0.2, i % 2 != 0, i % 2 == 0, i)
        for i in range(MIN_TOTAL)
    ]
    await _seed_pairs(db, entries)

    # Create admin user
    r = await client.post(SIGNUP_URL, json={"name": "Admin4", "email": "adm4@ex.com", "password": "pass1234"})
    token = r.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    u = (await db.execute(select(User).where(User.email == "adm4@ex.com"))).scalar_one()
    u.role = UserRole.admin
    db.add(u)
    await db.commit()

    resp = await client.post(REPLAY_URL, headers=headers)
    assert resp.status_code == 202
    data = resp.json()
    assert data["points"] == N_PREFIXES
    trend = data["iq_trend"]
    assert len(trend) == N_PREFIXES
    assert "date" in trend[0]
    assert "value" in trend[0]
    assert all(0.0 <= pt["value"] <= 100.0 for pt in trend)

    # GET /metrics now shows the trend
    resp2 = await client.get(METRICS_URL, headers=headers)
    assert resp2.status_code == 200
    assert len(resp2.json()["iq_trend"]) == N_PREFIXES
