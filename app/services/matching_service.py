"""MatchingService — Module 3 + Module 5: per-user semantic matching + ranked feed.

Design:
- Postings are GLOBAL; profile + skills are per-user.
- Matches are computed ON-THE-FLY (no persistence / no matches table).
- Ghost scores and is_ghost are READ from the posting as-is (Module 4 populates them).
- response_likelihood is computed by _compute_response_likelihood (Module 5).
- expected_value = match_score * response_likelihood * (1 - ghost_score)
"""
from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Float, cast, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.embeddings import EMBEDDING_DIM
from app.models.company import Company
from app.models.posting import Posting
from app.models.profile import Profile
from app.schemas.match import MatchSchema, SkillGapItem
from app.schemas.posting import coerce_posting_schema

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module 3 scoring constants
# ---------------------------------------------------------------------------

SEMANTIC_WEIGHT: float = 0.7
SKILL_WEIGHT: float = 0.3

# ---------------------------------------------------------------------------
# Module 5 — Response Likelihood constants
# ---------------------------------------------------------------------------

_COHORT_MIN_APPS: int = 5          # mirrors CohortService.MIN_APPS

# Annotate match_explanation when company response rate falls below this
_LOW_RESP_RATE: float = 0.25

# Data-rich weights (cohort_applied_count >= _COHORT_MIN_APPS) — sum to 1.0
_RL_COHORT_WEIGHT: float = 0.55
_RL_FRESH_WEIGHT: float = 0.35
_RL_GHOST_WEIGHT: float = 0.10

# Cold-start weights (no cohort data yet) — sum to 1.0
_RL_COLD_FRESH_WEIGHT: float = 0.65
_RL_COLD_GHOST_WEIGHT: float = 0.35


# ---------------------------------------------------------------------------
# Pure helpers (no DB access)
# ---------------------------------------------------------------------------

def _compute_skill_overlap(
    profile_skills: list[str],
    requirements: list[str],
) -> tuple[list[str], list[str]]:
    """Return (matched, missing) for a single posting.

    Case-insensitive; allows simple substring match in either direction so
    "Python" matches "Python 3.x" and vice-versa.
    """
    if not requirements:
        return [], []
    normalized = {s.strip().lower() for s in profile_skills}
    matched: list[str] = []
    missing: list[str] = []
    for req in requirements:
        req_norm = req.strip().lower()
        if any(skill in req_norm or req_norm in skill for skill in normalized):
            matched.append(req)
        else:
            missing.append(req)
    return matched, missing


def _freshness(posting: Posting) -> float:
    """Step-function freshness: 1.0 (0–14 d) → 0.1 (≥90 d)."""
    date_str = posting.posted_at or posting.last_seen_at or ""
    if not date_str:
        return 0.5
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        days_old = max(0, (datetime.now(UTC) - dt).days)
        if days_old < 15:
            return 1.0
        if days_old < 30:
            return 0.8
        if days_old < 60:
            return 0.5
        if days_old < 90:
            return 0.3
        return 0.1
    except (ValueError, AttributeError, TypeError):
        return 0.5


def _compute_response_likelihood(posting: Posting, company: Company) -> float:
    """Module 5 response-likelihood model (no LLM — pure signal arithmetic).

    Data-rich path (cohort_applied_count >= _COHORT_MIN_APPS):
        0.55 * cohort_response_rate + 0.35 * freshness + 0.10 * (1 - ghost_score)

    Cold-start path (< _COHORT_MIN_APPS applications in cohort):
        0.65 * freshness + 0.35 * (1 - ghost_history_score)

    Result is clamped to [0, 1].
    """
    fresh = _freshness(posting)
    applied = int(getattr(company, "cohort_applied_count", 0) or 0)

    if applied >= _COHORT_MIN_APPS:
        cohort_rate = float(company.responsiveness_score or 0.0)
        score = (
            _RL_COHORT_WEIGHT * cohort_rate
            + _RL_FRESH_WEIGHT * fresh
            + _RL_GHOST_WEIGHT * (1.0 - posting.ghost_score)
        )
    else:
        ghost_hist = float(company.ghost_history_score or 0.0)
        score = (
            _RL_COLD_FRESH_WEIGHT * fresh
            + _RL_COLD_GHOST_WEIGHT * (1.0 - ghost_hist)
        )

    return max(0.0, min(1.0, score))


def _build_explanation(
    matched: list[str],
    missing: list[str],
    semantic_sim: float,
    *,
    company: Company | None = None,
) -> str:
    """Deterministic templated explanation — no LLM call.

    When company cohort data shows a low response rate, appends a cohort reason
    so the ranking demotion is legible to the user.
    """
    if not matched and not missing:
        base = f"Semantic match ({semantic_sim:.0%}); no specific skill requirements listed."
    elif matched and not missing:
        top = ", ".join(matched[:3])
        base = f"Strong match on all listed requirements: {top}."
    elif matched:
        top_m = ", ".join(matched[:2])
        top_x = ", ".join(missing[:2])
        base = f"Strong on {top_m}; consider building {top_x}."
    else:
        top_x = ", ".join(missing[:3])
        base = f"Semantic fit ({semantic_sim:.0%}); key gaps: {top_x}."

    # Module 5: annotate when cohort data shows a low response rate
    if company is not None:
        applied = int(getattr(company, "cohort_applied_count", 0) or 0)
        if applied >= _COHORT_MIN_APPS:
            resp_rate = float(company.responsiveness_score or 0.0)
            if resp_rate < _LOW_RESP_RATE:
                responded = round(resp_rate * applied)
                base += (
                    f" Low reply rate: {responded} of {applied} batchmates heard back."
                )

    return base


async def _llm_explanation_for_detail(
    profile: Profile,
    posting: Posting,
    company: Company,
    fallback: str,
) -> str:
    """Optional LLM explanation — only called on the detail endpoint when ?enrich=true."""
    try:
        from app.llm.router import complete

        skills_str = ", ".join(str(s) for s in (profile.skills or [])) or "none listed"
        reqs_str = ", ".join(str(r) for r in (posting.requirements or [])) or "none listed"
        result = await complete(
            [
                {
                    "role": "system",
                    "content": (
                        "You are a concise career advisor for internship applicants. "
                        "Answer in 2-3 sentences."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Role: {posting.title} at {company.name}. "
                        f"Candidate skills: {skills_str}. "
                        f"Requirements: {reqs_str}. "
                        "Why does this role fit and how should the candidate position themselves?"
                    ),
                },
            ]
        )
        return result.strip()
    except Exception:  # noqa: BLE001
        return fallback


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class MatchingService:
    """Computes per-user matches against the global postings table.

    Postings are not user-scoped (global shared data), but the profile lookup
    and all score computation are scoped to the authenticated user.
    """

    def __init__(self, db: AsyncSession, user_id: uuid.UUID) -> None:
        self.db = db
        self.user_id = user_id

    # ------------------------------------------------------------------
    # Public — ranked feed
    # ------------------------------------------------------------------

    async def get_matches(
        self,
        *,
        work_mode: str | None = None,
        domain: str | None = None,
        include_ghosts: bool = False,
        sort: str = "expected_value",
        page: int = 1,
        limit: int = 20,
    ) -> tuple[list[MatchSchema], int]:
        profile = await self._get_profile()
        if profile is None or profile.embedding is None:
            return [], 0

        candidates = await self._fetch_candidates(
            profile=profile,
            work_mode=work_mode,
            domain=domain,
            include_ghosts=include_ghosts,
        )

        profile_skills = [str(s) for s in (profile.skills or [])]
        now = _now_iso()
        matches: list[MatchSchema] = []
        for posting, company, cosine_dist in candidates:
            matches.append(
                self._score(
                    posting=posting,
                    company=company,
                    profile_skills=profile_skills,
                    cosine_dist=float(cosine_dist),
                    now=now,
                )
            )

        # Sort by expected_value (default); fall back to same key for any other value
        matches.sort(key=lambda m: m.expected_value, reverse=True)

        total = len(matches)
        start = (page - 1) * limit
        return matches[start : start + limit], total

    # ------------------------------------------------------------------
    # Public — single match detail (with optional LLM enrichment)
    # ------------------------------------------------------------------

    async def get_match_detail(
        self,
        posting_id: uuid.UUID,
        *,
        enrich: bool = False,
    ) -> MatchSchema | None:
        row = (
            await self.db.execute(
                select(Posting, Company)
                .join(Company, Posting.company_id == Company.id)
                .where(Posting.id == posting_id)
            )
        ).first()
        if row is None:
            return None
        posting, company = row

        profile = await self._get_profile()
        if profile is None or profile.embedding is None:
            return self._zero_match(posting, company)

        # Compute cosine distance for this one posting
        profile_vec_d = literal(profile.embedding, type_=Vector(EMBEDDING_DIM))
        dist_row = (
            await self.db.execute(
                select(
                    cast(
                        Posting.embedding.op("<=>")(
                            profile_vec_d
                        ),
                        Float,
                    ).label("dist")
                ).where(Posting.id == posting_id)
                .where(Posting.embedding.is_not(None))
            )
        ).first()
        cosine_dist = float(dist_row.dist) if dist_row and dist_row.dist is not None else 1.0

        profile_skills = [str(s) for s in (profile.skills or [])]
        now = _now_iso()
        match = self._score(
            posting=posting,
            company=company,
            profile_skills=profile_skills,
            cosine_dist=cosine_dist,
            now=now,
        )

        if enrich:
            match = MatchSchema(
                **{
                    **match.model_dump(),
                    "match_explanation": await _llm_explanation_for_detail(
                        profile, posting, company, match.match_explanation
                    ),
                }
            )
        return match

    # ------------------------------------------------------------------
    # Public — skill gap analysis
    # ------------------------------------------------------------------

    async def get_skill_gaps(self) -> list[SkillGapItem]:
        profile = await self._get_profile()
        if profile is None or profile.embedding is None:
            return []

        candidates = await self._fetch_candidates(
            profile=profile,
            work_mode=None,
            domain=None,
            include_ghosts=False,
        )

        profile_skills = [str(s) for s in (profile.skills or [])]
        missing_count: dict[str, int] = {}
        for posting, _company, _dist in candidates:
            requirements = [str(r) for r in (posting.requirements or [])]
            _, missing = _compute_skill_overlap(profile_skills, requirements)
            for skill in missing:
                key = skill.strip().lower()
                missing_count[key] = missing_count.get(key, 0) + 1

        return sorted(
            [
                SkillGapItem(skill=skill, unlockable_roles=count)
                for skill, count in missing_count.items()
            ],
            key=lambda x: x.unlockable_roles,
            reverse=True,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_profile(self) -> Profile | None:
        result = await self.db.execute(
            select(Profile).where(Profile.user_id == self.user_id)
        )
        return result.scalar_one_or_none()

    async def _fetch_candidates(
        self,
        *,
        profile: Profile,
        work_mode: str | None,
        domain: str | None,
        include_ghosts: bool,
    ) -> list[tuple[Posting, Company, float]]:
        """Fetch postings ordered by cosine distance to profile embedding."""
        profile_vec = literal(profile.embedding, type_=Vector(EMBEDDING_DIM))
        # Cast to Float so SQLAlchemy uses Float's result processor, not Vector's
        cosine_dist = cast(
            Posting.embedding.op("<=>")(
                profile_vec
            ),
            Float,
        )

        stmt = (
            select(Posting, Company, cosine_dist.label("cosine_dist"))
            .join(Company, Posting.company_id == Company.id)
            .where(Posting.status == "active")
            .where(Posting.embedding.is_not(None))
        )

        if not include_ghosts:
            stmt = stmt.where(Posting.is_ghost == False)  # noqa: E712
        if work_mode:
            stmt = stmt.where(Posting.work_mode == work_mode)
        if domain:
            stmt = stmt.where(Company.domain.ilike(f"%{domain}%"))

        stmt = stmt.order_by(cosine_dist.asc())
        rows = (await self.db.execute(stmt)).all()
        return [(row[0], row[1], float(row[2])) for row in rows]

    def _score(
        self,
        *,
        posting: Posting,
        company: Company,
        profile_skills: list[str],
        cosine_dist: float,
        now: str,
    ) -> MatchSchema:
        """Compute all scores for a single (posting, cosine_dist) pair."""
        requirements = [str(r) for r in (posting.requirements or [])]
        matched, missing = _compute_skill_overlap(profile_skills, requirements)

        semantic_sim = max(0.0, 1.0 - cosine_dist)
        skill_ratio = len(matched) / max(1, len(requirements))
        match_score = max(
            0.0,
            min(1.0, SEMANTIC_WEIGHT * semantic_sim + SKILL_WEIGHT * skill_ratio),
        )
        response_likelihood = _compute_response_likelihood(posting, company)
        expected_value = max(
            0.0,
            min(1.0, match_score * response_likelihood * (1.0 - posting.ghost_score)),
        )
        explanation = _build_explanation(matched, missing, semantic_sim, company=company)
        posting_schema = coerce_posting_schema(posting, company)
        return MatchSchema(
            posting_id=posting.id,
            posting=posting_schema,
            match_score=match_score,
            match_explanation=explanation,
            matched_skills=matched,
            missing_skills=missing,
            response_likelihood=response_likelihood,
            expected_value=expected_value,
            ghost_score=posting.ghost_score,
            is_ghost=posting.is_ghost,
            created_at=now,
        )

    def _zero_match(self, posting: Posting, company: Company) -> MatchSchema:
        """Return a zeroed match for users without a profile embedding."""
        posting_schema = coerce_posting_schema(posting, company)
        return MatchSchema(
            posting_id=posting.id,
            posting=posting_schema,
            match_score=0.0,
            match_explanation="Complete your profile to see your personalized match score.",
            matched_skills=[],
            missing_skills=[str(r) for r in (posting.requirements or [])],
            response_likelihood=0.0,
            expected_value=0.0,
            ghost_score=posting.ghost_score,
            is_ghost=posting.is_ghost,
            created_at=_now_iso(),
        )
