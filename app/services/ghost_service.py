"""GhostService — Module 4: Ghost-Job Shield.

Five independent signals → weighted sum → ghost_score ∈ [0, 1].
No LLM calls. Writes to existing columns only (plus source_sightings, added in 0005 migration).
"""
from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import Company
from app.models.posting import Posting
from app.schemas.posting import CohortStats, PostingGhostDetail

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Weight constants — sum to 1.0
# ---------------------------------------------------------------------------
AGE_WEIGHT: float = 0.30
REPOST_WEIGHT: float = 0.20
VAGUE_WEIGHT: float = 0.25
COMPANY_WEIGHT: float = 0.15
COHORT_WEIGHT: float = 0.10

# Warm-start threshold; recalibrate toward 0.55 once REPOST sightings accumulate
# and COHORT (Module 7) comes online.
GHOST_THRESHOLD: float = 0.38

# ---------------------------------------------------------------------------
# Vagueness heuristics
# ---------------------------------------------------------------------------
_PIPELINE_PHRASES: tuple[str, ...] = (
    "talent community",
    "always looking",
    "building a pipeline",
    "future opportunities",
    "pipeline of candidates",
    "expressions of interest",
    "not currently hiring",
    "always on the lookout",
)

_TECH_TERMS: frozenset[str] = frozenset(
    {
        "python",
        "javascript",
        "typescript",
        "java",
        "go",
        "rust",
        "c++",
        "c#",
        "react",
        "vue",
        "angular",
        "node",
        "fastapi",
        "django",
        "flask",
        "spring",
        "postgresql",
        "mysql",
        "mongodb",
        "redis",
        "elasticsearch",
        "docker",
        "kubernetes",
        "terraform",
        "aws",
        "gcp",
        "azure",
        "pytorch",
        "tensorflow",
        "scikit-learn",
        "pandas",
        "numpy",
        "sql",
        "graphql",
        "rest",
        "grpc",
        "kafka",
        "rabbitmq",
        "git",
        "linux",
        "bash",
        "shell",
    }
)


# ---------------------------------------------------------------------------
# Pure signal functions (no DB access)
# ---------------------------------------------------------------------------


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError, AttributeError):
        return None


def _days_live(posting: Posting, now: datetime) -> int:
    """Days since the earlier of posted_at and last_seen_at (fallback: last_seen_at)."""
    candidates: list[datetime] = []
    for s in (posting.posted_at, posting.last_seen_at):
        dt = _parse_dt(s)
        if dt is not None:
            candidates.append(dt)
    if not candidates:
        return 0
    return max(0, (now - min(candidates)).days)


def age_score(posting: Posting, now: datetime) -> float:
    """Step function: 0-14d→0, 15-29d→0.2, 30-59d→0.5, 60-89d→0.7, 90+d→1.0."""
    days = _days_live(posting, now)
    if days < 15:
        return 0.0
    if days < 30:
        return 0.2
    if days < 60:
        return 0.5
    if days < 90:
        return 0.7
    return 1.0


def repost_score(sightings: int) -> float:
    """1 board→0.0, 2 boards→0.4, 3+ boards→0.8 (driven by posting.source_sightings)."""
    if sightings <= 1:
        return 0.0
    if sightings == 2:
        return 0.4
    return 0.8


def vague_jd_score(posting: Posting) -> float:
    """Heuristic vagueness: word count + req count + pipeline phrases − specificity bonus."""
    description = str(posting.description or "").lower()
    requirements: list[str] = [str(r) for r in (posting.requirements or []) if r]

    word_count = len(description.split())
    if word_count == 0:
        word_s = 1.0
    elif word_count < 50:
        word_s = 0.8
    elif word_count < 100:
        word_s = 0.5
    elif word_count < 200:
        word_s = 0.2
    else:
        word_s = 0.0

    req_count = len(requirements)
    if req_count == 0:
        req_s = 1.0
    elif req_count <= 2:
        req_s = 0.6
    elif req_count <= 4:
        req_s = 0.3
    else:
        req_s = 0.0

    phrase_hits = sum(1 for phrase in _PIPELINE_PHRASES if phrase in description)
    phrase_s = min(1.0, phrase_hits * 0.4)

    # Specificity bonus: tech/tool names in requirements OR description lower vagueness
    combined_text = (" ".join(requirements) + " " + description).lower()
    tech_hits = sum(1 for term in _TECH_TERMS if term in combined_text)
    specificity_bonus = min(0.4, tech_hits * 0.1)

    raw = word_s * 0.35 + req_s * 0.35 + phrase_s * 0.30 - specificity_bonus
    return max(0.0, min(1.0, raw))


MIN_COHORT_APPS: int = 5


def company_ghost_score(company: Company) -> float:
    return float(company.ghost_history_score or 0.0)


def cohort_response_signal(company: Company) -> float:
    """Cross-user response signal.

    Returns 0.0 (neutral) when applied count < MIN_COHORT_APPS.
    Once enough data exists, unresponsive companies raise the ghost score.
    """
    applied = getattr(company, "cohort_applied_count", None) or 0
    if applied < MIN_COHORT_APPS:
        return 0.0
    return max(0.0, min(1.0, 1.0 - float(company.responsiveness_score or 1.0)))


def compute_ghost_score(
    posting: Posting,
    company: Company,
    now: datetime,
) -> float:
    """Weighted sum of 5 named signals, clamped to [0, 1]."""
    score = (
        AGE_WEIGHT * age_score(posting, now)
        + REPOST_WEIGHT * repost_score(posting.source_sightings)
        + VAGUE_WEIGHT * vague_jd_score(posting)
        + COMPANY_WEIGHT * company_ghost_score(company)
        + COHORT_WEIGHT * cohort_response_signal(company)
    )
    return max(0.0, min(1.0, score))


def build_signals(
    posting: Posting,
    company: Company,
    now: datetime,
) -> list[str]:
    """Human-readable triggered signals, e.g. ["Live 73 days", "Seen on 2 boards", "Vague JD"]."""
    signals: list[str] = []
    days = _days_live(posting, now)
    a_s = age_score(posting, now)
    r_s = repost_score(posting.source_sightings)
    v_s = vague_jd_score(posting)
    c_s = company_ghost_score(company)

    if a_s > 0.0:
        signals.append(f"Live {days} days")
    if r_s > 0.0:
        signals.append(f"Seen on {posting.source_sightings} boards")
    if v_s >= 0.3:
        signals.append("Vague JD")
    if c_s >= 0.3:
        signals.append("Company has ghost history")
    return signals


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class GhostService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def rescore_all(self) -> dict[str, int]:
        """Rescore every posting + update company rolling averages.

        Returns {"rescored": N, "flagged_ghost": M}.
        """
        rows = (
            await self.db.execute(
                select(Posting, Company).join(Company, Posting.company_id == Company.id)
            )
        ).all()

        if not rows:
            return {"rescored": 0, "flagged_ghost": 0}

        postings: list[Posting] = []
        company_by_posting: dict[uuid.UUID, Company] = {}
        company_by_id: dict[uuid.UUID, Company] = {}
        for r in rows:
            p: Posting = r[0]
            c: Company = r[1]
            postings.append(p)
            company_by_posting[p.id] = c
            company_by_id[c.id] = c

        now = datetime.now(UTC)

        # Phase 1: compute posting ghost_scores using current company.ghost_history_score
        for posting in postings:
            company = company_by_posting[posting.id]
            score = compute_ghost_score(posting, company, now)
            posting.ghost_score = score
            posting.is_ghost = score >= GHOST_THRESHOLD
            self.db.add(posting)

        # Phase 2: update company.ghost_history_score = rolling avg of ghost_scores
        company_posting_groups: dict[uuid.UUID, list[Posting]] = {}
        for posting in postings:
            company_posting_groups.setdefault(posting.company_id, []).append(posting)

        for company_id, co_postings in company_posting_groups.items():
            company = company_by_id[company_id]
            avg_ghost = sum(p.ghost_score for p in co_postings) / len(co_postings)
            company.ghost_history_score = avg_ghost
            # Only update responsiveness_score from ghost history when there is no
            # real cohort data yet; CohortService owns it once MIN_COHORT_APPS is met.
            applied = getattr(company, "cohort_applied_count", None) or 0
            if applied < MIN_COHORT_APPS:
                company.responsiveness_score = 1.0 - avg_ghost
            self.db.add(company)

        await self.db.commit()

        flagged = sum(1 for p in postings if p.is_ghost)
        return {"rescored": len(postings), "flagged_ghost": flagged}

    async def rescore_posting(self, posting_id: uuid.UUID) -> PostingGhostDetail | None:
        """Re-score a single posting and return its ghost detail. Returns None if not found."""
        row = (
            await self.db.execute(
                select(Posting, Company)
                .join(Company, Posting.company_id == Company.id)
                .where(Posting.id == posting_id)
            )
        ).first()
        if row is None:
            return None
        posting: Posting = row[0]
        company: Company = row[1]

        now = datetime.now(UTC)
        score = compute_ghost_score(posting, company, now)
        posting.ghost_score = score
        posting.is_ghost = score >= GHOST_THRESHOLD
        self.db.add(posting)
        await self.db.commit()

        signals = build_signals(posting, company, now)
        return PostingGhostDetail(
            ghost_score=score,
            is_ghost=posting.is_ghost,
            signals=signals,
            cohort=CohortStats(applied=0, responded=0),
        )
