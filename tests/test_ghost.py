"""Tests for Module 4 — Ghost-Job Shield."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import Company
from app.models.posting import Posting
from app.services.aggregation_service import AggregationService
from app.services.ghost_service import (
    AGE_WEIGHT,
    COHORT_WEIGHT,
    COMPANY_WEIGHT,
    GHOST_THRESHOLD,
    REPOST_WEIGHT,
    VAGUE_WEIGHT,
    GhostService,
    age_score,
    cohort_score,
    company_ghost_score,
    compute_ghost_score,
    repost_score,
    vague_jd_score,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_RICH_DESC = ("We are building a great product and need someone. " * 8).strip()
_RICH_REQS = ["Python", "FastAPI", "PostgreSQL", "Docker", "Redis", "SQL"]


def _make_company(*, ghost_history_score: float = 0.0) -> Company:
    name = f"Co-{uuid.uuid4().hex[:8]}"
    return Company(
        name=name,
        normalized_name=name.lower().replace("-", ""),
        domain=None,
        industry=None,
        size=None,
        ghost_history_score=ghost_history_score,
        responsiveness_score=1.0 - ghost_history_score,
    )


def _make_posting(
    *,
    company_id: uuid.UUID,
    days_old: int = 0,
    description: str = "",
    requirements: list[str] | None = None,
    source_sightings: int = 1,
) -> Posting:
    now = datetime.now(UTC)
    posted = (now - timedelta(days=days_old)).isoformat().replace("+00:00", "Z")
    p = Posting(
        company_id=company_id,
        title="Test Intern Role",
        description=description,
        requirements=requirements or [],
        work_mode="remote",
        source="greenhouse",
        source_url=f"https://example.com/{uuid.uuid4().hex}",
        dedup_key=uuid.uuid4().hex[:16],
        posted_at=posted,
        last_seen_at=posted,
    )
    p.source_sightings = source_sightings
    return p


# ---------------------------------------------------------------------------
# 1. High-ghost posting → above threshold, is_ghost=True
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rescore_all_high_ghost_posting(db: AsyncSession) -> None:
    """90-day posting, 3 board sightings, vague JD, high-ghost company → above threshold."""
    company = _make_company(ghost_history_score=0.9)
    db.add(company)
    await db.flush()

    # source_sightings=3 simulates the role appearing on 3 separate job boards
    posting = _make_posting(
        company_id=company.id,
        days_old=105,
        description="",
        requirements=[],
        source_sightings=3,
    )
    db.add(posting)
    await db.commit()

    svc = GhostService(db)
    result = await svc.rescore_all()

    assert result["rescored"] >= 1
    assert result["flagged_ghost"] >= 1

    await db.refresh(posting)
    assert posting.ghost_score > GHOST_THRESHOLD, (
        f"expected > {GHOST_THRESHOLD}, got {posting.ghost_score}"
    )
    assert posting.is_ghost is True


# ---------------------------------------------------------------------------
# 2. Low-ghost posting → below threshold, is_ghost=False
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rescore_all_low_ghost_posting(db: AsyncSession) -> None:
    """5-day posting, 1 board, specific reqs, new company → low score, is_ghost=False."""
    company = _make_company(ghost_history_score=0.0)
    db.add(company)
    await db.flush()

    posting = _make_posting(
        company_id=company.id,
        days_old=5,
        description=_RICH_DESC,
        requirements=_RICH_REQS,
        source_sightings=1,
    )
    db.add(posting)
    await db.commit()

    svc = GhostService(db)
    await svc.rescore_all()

    await db.refresh(posting)
    assert posting.ghost_score < GHOST_THRESHOLD
    assert posting.is_ghost is False


# ---------------------------------------------------------------------------
# 3. Exact weighted-sum formula verified
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_formula_exact_weighted_sum(db: AsyncSession) -> None:
    """ghost_score == AGE*age + REPOST*repost + VAGUE*vague + COMPANY*hist + COHORT*cohort."""
    company = _make_company(ghost_history_score=0.9)
    db.add(company)
    await db.flush()

    posting = _make_posting(
        company_id=company.id,
        days_old=105,
        description="",
        requirements=[],
        source_sightings=3,
    )
    db.add(posting)
    await db.commit()

    now = datetime.now(UTC)
    a_s = age_score(posting, now)
    r_s = repost_score(posting.source_sightings)
    v_s = vague_jd_score(posting)
    c_s = company_ghost_score(company)
    co_s = cohort_score()

    expected = max(
        0.0,
        min(
            1.0,
            AGE_WEIGHT * a_s
            + REPOST_WEIGHT * r_s
            + VAGUE_WEIGHT * v_s
            + COMPANY_WEIGHT * c_s
            + COHORT_WEIGHT * co_s,
        ),
    )

    actual = compute_ghost_score(posting, company, now)
    assert abs(actual - expected) < 1e-9


# ---------------------------------------------------------------------------
# 4. is_ghost flips exactly at GHOST_THRESHOLD
# ---------------------------------------------------------------------------


def test_is_ghost_flips_at_threshold() -> None:
    """Weight constants must sum to 1.0; GHOST_THRESHOLD is the warm-start value."""
    assert GHOST_THRESHOLD == 0.38
    total = AGE_WEIGHT + REPOST_WEIGHT + VAGUE_WEIGHT + COMPANY_WEIGHT + COHORT_WEIGHT
    assert abs(total - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# 5. company.ghost_history_score updates after rescore_all
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_company_ghost_history_updates_after_rescore(db: AsyncSession) -> None:
    """company.ghost_history_score = avg(ghost_score) across company's postings."""
    company = _make_company(ghost_history_score=0.0)
    db.add(company)
    await db.flush()

    p1 = _make_posting(company_id=company.id, days_old=105, description="", requirements=[])
    p2 = _make_posting(
        company_id=company.id, days_old=5, description=_RICH_DESC, requirements=_RICH_REQS
    )
    db.add(p1)
    db.add(p2)
    await db.commit()

    svc = GhostService(db)
    await svc.rescore_all()

    await db.refresh(p1)
    await db.refresh(p2)
    await db.refresh(company)

    expected_avg = (p1.ghost_score + p2.ghost_score) / 2.0
    assert abs(company.ghost_history_score - expected_avg) < 1e-6
    assert abs(company.responsiveness_score - (1.0 - expected_avg)) < 1e-6


# ---------------------------------------------------------------------------
# 6. Cohort signal defaults to 0.0 (TODO Module 7)
# ---------------------------------------------------------------------------


def test_cohort_signal_defaults_to_zero() -> None:
    """cohort_score() returns 0.0 until Module 7 wires real data."""
    assert cohort_score() == 0.0
    assert COHORT_WEIGHT == 0.10


# ---------------------------------------------------------------------------
# 7. GET /api/postings/{id}/ghost returns correct shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_posting_ghost_endpoint_shape(
    client: AsyncClient,
    db: AsyncSession,
    auth_headers: dict[str, str],
) -> None:
    company = _make_company(ghost_history_score=0.5)
    db.add(company)
    await db.flush()

    posting = _make_posting(company_id=company.id, days_old=95, description="", requirements=[])
    db.add(posting)
    await db.commit()

    resp = await client.get(f"/api/postings/{posting.id}/ghost", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert "ghost_score" in data
    assert "is_ghost" in data
    assert "signals" in data
    assert "cohort" in data
    assert isinstance(data["ghost_score"], float)
    assert isinstance(data["is_ghost"], bool)
    assert isinstance(data["signals"], list)
    assert "applied" in data["cohort"]
    assert "responded" in data["cohort"]
    assert data["cohort"]["applied"] == 0
    assert data["cohort"]["responded"] == 0


# ---------------------------------------------------------------------------
# 8. Unknown id → 404 in error shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_posting_ghost_404(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    resp = await client.get(f"/api/postings/{uuid.uuid4()}/ghost", headers=auth_headers)
    assert resp.status_code == 404
    body = resp.json()
    assert "error" in body
    assert body["error"]["code"] == "POSTING_NOT_FOUND"


# ---------------------------------------------------------------------------
# 9. rescore_all returns {rescored: N, flagged_ghost: M}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rescore_all_return_shape(db: AsyncSession) -> None:
    company = _make_company()
    db.add(company)
    await db.flush()

    db.add(_make_posting(company_id=company.id, days_old=5))
    db.add(_make_posting(company_id=company.id, days_old=5))
    await db.commit()

    svc = GhostService(db)
    result = await svc.rescore_all()

    assert set(result.keys()) == {"rescored", "flagged_ghost"}
    assert result["rescored"] >= 2
    assert result["flagged_ghost"] <= result["rescored"]


# ---------------------------------------------------------------------------
# 10. Wire test: GET /api/matches excludes is_ghost=True by default
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_matches_excludes_ghost_by_default(
    client: AsyncClient,
    db: AsyncSession,
    auth_headers: dict[str, str],
) -> None:
    """Postings with is_ghost=True must not appear in GET /matches (include_ghosts=False default)."""
    company = _make_company()
    db.add(company)
    await db.flush()

    ghost_posting = _make_posting(company_id=company.id, days_old=5)
    ghost_posting.is_ghost = True
    ghost_posting.ghost_score = 0.8
    db.add(ghost_posting)
    await db.commit()

    resp = await client.get("/api/matches", headers=auth_headers)
    assert resp.status_code == 200
    ids = [m["posting"]["id"] for m in resp.json().get("data", [])]
    assert str(ghost_posting.id) not in ids

    resp2 = await client.get("/api/matches?include_ghosts=true", headers=auth_headers)
    assert resp2.status_code == 200


# ---------------------------------------------------------------------------
# 11. AggregationService.refresh() calls GhostService.rescore_all()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_aggregation_refresh_calls_ghost_rescore(db: AsyncSession) -> None:
    """AggregationService.refresh() must wire through to GhostService.rescore_all()."""
    with (
        patch.object(GhostService, "rescore_all", new_callable=AsyncMock) as mock_rescore,
        patch("app.services.aggregation_service.GreenhouseSource") as mock_gh,
        patch("app.services.aggregation_service.AshbySource") as mock_ashby,
        patch("app.services.aggregation_service.RemoteOKSource") as mock_rok,
        patch("app.services.aggregation_service.RemotiveSource") as mock_rtv,
    ):
        mock_rescore.return_value = {"rescored": 0, "flagged_ghost": 0}
        for mock_cls in (mock_gh, mock_ashby, mock_rok, mock_rtv):
            instance = mock_cls.return_value
            instance.fetch = AsyncMock(return_value=[])
            instance.name = "mock"

        svc = AggregationService(db)
        await svc.refresh()

    mock_rescore.assert_called_once()


# ---------------------------------------------------------------------------
# 12. Cross-source dedup increments source_sightings
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cross_source_dedup_increments_sightings(db: AsyncSession) -> None:
    """When aggregation finds the same role on a second board, source_sightings += 1."""
    from app.sources.base import RawPosting
    from app.sources.normalize import build_dedup_key

    # Seed a company and an existing posting via AggregationService internals
    svc = AggregationService(db)
    company_name = f"TestCo-{uuid.uuid4().hex[:6]}"

    raw1: RawPosting = {
        "title": "Software Intern",
        "company_name": company_name,
        "description": "Build cool things.",
        "location": None,
        "work_mode": None,
        "stipend": None,
        "source": "greenhouse",
        "source_url": f"https://boards.greenhouse.io/{uuid.uuid4().hex}",
        "posted_at": None,
        "requirements": [],
    }
    was_dedup = await svc._upsert_one(raw1)
    assert not was_dedup  # first insert

    # Second raw: different source_url but same normalized title+company → same dedup_key
    dedup = build_dedup_key(company_name, "Software Intern", None)
    raw2: RawPosting = {
        "title": "Software Intern",
        "company_name": company_name,
        "description": "Build cool things.",
        "location": None,
        "work_mode": None,
        "stipend": None,
        "source": "lever",
        "source_url": f"https://jobs.lever.co/{uuid.uuid4().hex}",
        "posted_at": None,
        "requirements": [],
    }
    was_dedup2 = await svc._upsert_one(raw2)
    assert was_dedup2  # cross-source duplicate

    # source_sightings on the original posting must now be 2
    existing = (
        await db.execute(
            sa_select(Posting).where(Posting.dedup_key == dedup)
        )
    ).scalar_one()
    assert existing.source_sightings == 2
