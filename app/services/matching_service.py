"""MatchingService — Module 3: per-user semantic matching + ranked feed.

Design:
- Postings are GLOBAL; profile + skills are per-user.
- Matches are computed ON-THE-FLY (no persistence / no matches table).
- Ghost scores and is_ghost are READ from the posting as-is (Module 4 populates them).
- response_likelihood is a PLACEHOLDER freshness heuristic (Module 5 replaces it).
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
# Scoring constants — named so Modules 4 & 5 can find and replace them
# ---------------------------------------------------------------------------

SEMANTIC_WEIGHT: float = 0.7
SKILL_WEIGHT: float = 0.3


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


def _response_likelihood_placeholder(posting: Posting) -> float:
    # TODO Module 5 — replace with trained response-likelihood model.
    # Placeholder: linear freshness decay from posted_at or last_seen_at.
    # 0 days old → 0.9, ≥200 days old → 0.1 (floor).
    date_str = posting.posted_at or posting.last_seen_at or ""
    if not date_str:
        return 0.5
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        days_old = max(0, (datetime.now(UTC) - dt).days)
        return max(0.1, min(0.9, 0.9 - days_old * 0.004))
    except (ValueError, AttributeError, TypeError):
        return 0.5


def _build_explanation(
    matched: list[str],
    missing: list[str],
    semantic_sim: float,
) -> str:
    """Deterministic templated explanation — no LLM call."""
    if not matched and not missing:
        return f"Semantic match ({semantic_sim:.0%}); no specific skill requirements listed."
    if matched and not missing:
        top = ", ".join(matched[:3])
        return f"Strong match on all listed requirements: {top}."
    if matched:
        top_m = ", ".join(matched[:2])
        top_x = ", ".join(missing[:2])
        return f"Strong on {top_m}; consider building {top_x}."
    top_x = ", ".join(missing[:3])
    return f"Semantic fit ({semantic_sim:.0%}); key gaps: {top_x}."


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
        response_likelihood = _response_likelihood_placeholder(posting)
        expected_value = max(
            0.0,
            min(1.0, match_score * response_likelihood * (1.0 - posting.ghost_score)),
        )
        explanation = _build_explanation(matched, missing, semantic_sim)
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
