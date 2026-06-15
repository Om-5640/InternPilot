"""Module 12 — ResearchService.

Matches students to research opportunities (GLOBAL) and manages outreach (USER-OWNED).

HONEST LIMITATION: no live paper-fetch API, so pitch specificity is bounded by the
seeded research description. In production, pull the professor's recent publications
to enrich the LLM prompt.

Reuses:
  - embed() from app.llm.embeddings for semantic similarity
  - _grounding_score / _find_unsupported_claims from application_service (anti-fabrication)
  - pgvector cosine distance (<=>) for ranking

No ghost/ATS/response-likelihood — not applicable to research outreach.
"""
from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import Float, cast, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError
from app.llm.embeddings import EMBEDDING_DIM, embed
from app.models.artifact import Artifact
from app.models.profile import Profile
from app.models.research_opportunity import ResearchOpportunity
from app.models.research_outreach import OUTREACH_STATUSES, ResearchOutreach
from app.schemas.research import (
    ResearchMatchSchema,
    ResearchOpportunitySchema,
)
from app.services.application_service import _find_unsupported_claims, _grounding_score
from app.services.base import BaseService
from app.services.matching_service import _compute_skill_overlap

logger = logging.getLogger(__name__)

SEMANTIC_WEIGHT: float = 0.7
SKILL_WEIGHT: float = 0.3
GROUNDING_THRESHOLD: float = 0.7


def _coerce_opportunity(opp: ResearchOpportunity) -> ResearchOpportunitySchema:
    return ResearchOpportunitySchema(
        id=opp.id,
        professor_name=opp.professor_name,
        institution=opp.institution,
        lab_name=opp.lab_name,
        research_area=opp.research_area,
        description=opp.description,
        desired_skills=[str(s) for s in (opp.desired_skills or [])],
        program=opp.program,
        region=opp.region,
        contact_email=opp.contact_email,
        url=opp.url,
        source=opp.source,
        posted_at=opp.posted_at,
        last_seen_at=opp.last_seen_at,
        created_at=opp.created_at,
    )


def _fit_explanation(
    research_area: str,
    top_interest: str,
    matched: list[str],
    missing: list[str],
    semantic_sim: float,
) -> str:
    base = (
        f"Your interest in {top_interest!r} aligns with the lab's work on {research_area!r}."
    )
    if matched:
        base += f" Matching skills: {', '.join(matched[:3])}."
    if missing:
        base += f" Consider building: {', '.join(missing[:2])}."
    if not matched and not missing:
        base += f" Semantic fit: {semantic_sim:.0%}."
    return base


class ResearchService(BaseService):
    """Outreach methods are user-scoped. Opportunity reads are GLOBAL."""

    def __init__(self, db: AsyncSession, user_id: uuid.UUID) -> None:
        super().__init__(db, user_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_profile(self) -> Profile | None:
        return (
            await self.db.execute(
                select(Profile).where(Profile.user_id == self.user_id)
            )
        ).scalar_one_or_none()

    async def _get_opportunity(self, opportunity_id: uuid.UUID) -> ResearchOpportunity:
        row = (
            await self.db.execute(
                select(ResearchOpportunity).where(
                    ResearchOpportunity.id == opportunity_id
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise APIError(404, "OPPORTUNITY_NOT_FOUND", "Research opportunity not found")
        return row

    async def _get_outreach_owned(self, outreach_id: uuid.UUID) -> ResearchOutreach:
        row = (
            await self.db.execute(
                select(ResearchOutreach).where(
                    ResearchOutreach.id == outreach_id,
                    ResearchOutreach.user_id == self.user_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise APIError(404, "OUTREACH_NOT_FOUND", "Research outreach not found")
        return row

    def _score_opportunity(
        self,
        opp: ResearchOpportunity,
        cosine_dist: float,
        profile_skills: list[str],
        top_interest: str,
    ) -> ResearchMatchSchema:
        desired = [str(s) for s in (opp.desired_skills or [])]
        matched, missing = _compute_skill_overlap(profile_skills, desired)
        semantic_sim = max(0.0, 1.0 - cosine_dist)
        skill_ratio = len(matched) / max(1, len(desired)) if desired else 0.0
        fit_score = max(
            0.0,
            min(1.0, SEMANTIC_WEIGHT * semantic_sim + SKILL_WEIGHT * skill_ratio),
        )
        explanation = _fit_explanation(
            opp.research_area, top_interest, matched, missing, semantic_sim
        )
        return ResearchMatchSchema(
            opportunity=_coerce_opportunity(opp),
            fit_score=fit_score,
            fit_explanation=explanation,
            matched_skills=matched,
            missing_skills=missing,
        )

    # ------------------------------------------------------------------
    # find_matches — ranked feed
    # ------------------------------------------------------------------

    async def find_matches(
        self, page: int = 1, limit: int = 20
    ) -> tuple[list[ResearchMatchSchema], int]:
        profile = await self._get_profile()
        if profile is None:
            return [], 0

        interests: list[str] = [str(i) for i in (profile.research_interests or [])]
        if not interests:
            return [], 0

        interest_text = " ".join(interests)
        vectors = await embed([interest_text])
        interest_vec = vectors[0]

        profile_vec = literal(interest_vec, type_=Vector(EMBEDDING_DIM))
        cosine_dist_col = cast(
            ResearchOpportunity.embedding.op("<=>")(profile_vec),
            Float,
        )
        rows = (
            await self.db.execute(
                select(ResearchOpportunity, cosine_dist_col.label("dist"))
                .where(ResearchOpportunity.embedding.is_not(None))
                .order_by(cosine_dist_col.asc())
            )
        ).all()

        profile_skills = [str(s) for s in (profile.skills or [])]
        top_interest = interests[0] if interests else "research"

        matches = [
            self._score_opportunity(row[0], float(row[1]), profile_skills, top_interest)
            for row in rows
        ]
        matches.sort(key=lambda m: m.fit_score, reverse=True)

        total = len(matches)
        start = (page - 1) * limit
        return matches[start : start + limit], total

    # ------------------------------------------------------------------
    # get_match — single detail
    # ------------------------------------------------------------------

    async def get_match(self, opportunity_id: uuid.UUID) -> ResearchMatchSchema:
        opp = await self._get_opportunity(opportunity_id)
        profile = await self._get_profile()

        if profile is None or opp.embedding is None:
            interests = (
                [str(i) for i in (profile.research_interests or [])] if profile else []
            )
            top_interest = interests[0] if interests else "research"
            desired = [str(s) for s in (opp.desired_skills or [])]
            return ResearchMatchSchema(
                opportunity=_coerce_opportunity(opp),
                fit_score=0.0,
                fit_explanation="Complete your profile research interests to see your fit score.",
                matched_skills=[],
                missing_skills=desired,
            )

        interests = [str(i) for i in (profile.research_interests or [])]
        if not interests:
            desired = [str(s) for s in (opp.desired_skills or [])]
            return ResearchMatchSchema(
                opportunity=_coerce_opportunity(opp),
                fit_score=0.0,
                fit_explanation="Add research interests to your profile to see your fit score.",
                matched_skills=[],
                missing_skills=desired,
            )

        interest_text = " ".join(interests)
        vectors = await embed([interest_text])
        interest_vec = vectors[0]

        profile_vec_d = literal(interest_vec, type_=Vector(EMBEDDING_DIM))
        dist_row = (
            await self.db.execute(
                select(
                    cast(
                        ResearchOpportunity.embedding.op("<=>")(profile_vec_d),
                        Float,
                    ).label("dist")
                ).where(ResearchOpportunity.id == opportunity_id)
            )
        ).first()
        cosine_dist = float(dist_row.dist) if dist_row and dist_row.dist is not None else 1.0

        profile_skills = [str(s) for s in (profile.skills or [])]
        top_interest = interests[0]
        return self._score_opportunity(opp, cosine_dist, profile_skills, top_interest)

    # ------------------------------------------------------------------
    # draft_pitch — LLM + grounding guard → Artifact(type="research_pitch")
    # ------------------------------------------------------------------

    async def draft_pitch(self, opportunity_id: uuid.UUID) -> Artifact:
        from app.llm.router import complete

        opp = await self._get_opportunity(opportunity_id)
        profile = await self._get_profile()

        # Build profile context
        skills: list[str] = []
        project_techs: list[str] = []
        experience_text = ""
        interests_str = ""
        proj_bullets = ""
        exp_bullets = ""

        if profile is not None:
            skills = [str(s) for s in (profile.skills or [])]
            interests_list = [str(i) for i in (profile.research_interests or [])]
            interests_str = ", ".join(interests_list)
            for proj in (profile.projects or []):
                if isinstance(proj, dict):
                    for t in proj.get("tech", []):
                        project_techs.append(str(t))
            proj_parts: list[str] = []
            for proj in (profile.projects or []):
                if isinstance(proj, dict):
                    tech_str = ", ".join(str(t) for t in proj.get("tech", []))
                    line = f"{proj.get('name', '?')}: {proj.get('description', '')}"
                    if tech_str:
                        line += f" (tech: {tech_str})"
                    proj_parts.append(line)
            proj_bullets = "\n".join(f"  - {p}" for p in proj_parts)
            exp_parts: list[str] = []
            for exp in (profile.experience or []):
                if isinstance(exp, dict):
                    line = f"{exp.get('title', '?')} at {exp.get('org', '?')}"
                    desc = exp.get("description", "")
                    if desc:
                        line += f": {desc}"
                        experience_text += " " + str(desc)
                    exp_parts.append(line)
            exp_bullets = "\n".join(f"  - {e}" for e in exp_parts)

        desired_str = ", ".join([str(s) for s in (opp.desired_skills or [])])
        allowed_set = set(skills) | set(project_techs)
        if allowed_set:
            whitelist_rule = (
                f"VERIFIED SKILL WHITELIST: {', '.join(sorted(allowed_set))}. "
                "You may ONLY reference skills from this list. "
                "If a desired skill is absent from the whitelist, do NOT claim the student has it."
            )
        else:
            whitelist_rule = (
                "No confirmed skills — write only what experience bullets explicitly describe. "
                "Do not infer or assume technical skills."
            )

        system_msg = (
            "You are a career advisor helping a student write a concise, grounded professor cold-email "
            "for a research internship. "
            f"{whitelist_rule} "
            "Output must start with 'Subject: <specific subject line>' on line 1, "
            "then a blank line, then 3-4 short paragraphs following this structure:\n"
            "  (1) Hook: reference the professor's specific research area and description.\n"
            "  (2) Bridge: connect the student's REAL research interests to the lab's work.\n"
            "  (3) Background: student's verified skills/projects — ONLY from the whitelist.\n"
            "  (4) CTA: short, low-commitment closing asking if there's an opportunity to contribute.\n"
            "Keep the total under 250 words. Use no placeholder text."
        )
        user_msg = (
            f"Professor: {opp.professor_name}, {opp.institution}"
            + (f" ({opp.lab_name})" if opp.lab_name else "")
            + f"\nResearch area: {opp.research_area}"
            + f"\nDescription: {opp.description[:2000]}"
            + f"\nDesired skills: {desired_str}"
            + f"\n\nStudent research interests: {interests_str or '(none listed)'}"
            + f"\nStudent skills (whitelist): {', '.join(skills) or '(none)'}"
            + f"\nProjects:\n{proj_bullets or '  (none listed)'}"
            + f"\nExperience:\n{exp_bullets or '  (none listed)'}"
            + "\n\nWrite the professor cold-email."
        )

        try:
            content = await complete([
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ])
        except Exception as exc:
            logger.exception("draft_pitch LLM call failed: %s", exc)
            raise APIError(500, "PITCH_FAILED", "Failed to generate research pitch") from exc

        # Grounding guard — desired_skills serve as the "requirements" claim list
        desired_list = [str(s) for s in (opp.desired_skills or [])]
        gs = _grounding_score(content, desired_list, skills, project_techs, experience_text)

        if gs < GROUNDING_THRESHOLD and (skills or project_techs):
            unsupported = _find_unsupported_claims(
                content, desired_list, skills, project_techs, experience_text
            )
            if unsupported:
                names = ", ".join(unsupported)
                retry_msg = (
                    f"Your draft claimed expertise in {names}. "
                    "The student does NOT have these — they are NOT on the verified whitelist. "
                    f"Remove every reference to {names} and rewrite using only whitelist skills. "
                    "Keep the Subject: line and the same 4-paragraph structure."
                )
                try:
                    content = await complete([
                        {"role": "system", "content": system_msg},
                        {"role": "user", "content": user_msg},
                        {"role": "assistant", "content": content},
                        {"role": "user", "content": retry_msg},
                    ])
                    gs = _grounding_score(
                        content, desired_list, skills, project_techs, experience_text
                    )
                except Exception as exc:
                    logger.warning("draft_pitch retry failed, keeping first attempt: %s", exc)

        artifact = Artifact(
            user_id=self.user_id,
            application_id=None,
            type="research_pitch",
            content=content,
            ats_score=None,
            missing_keywords=[],
            grounding_score=gs,
            predicted_response=None,
            version=1,
        )
        self.db.add(artifact)
        await self.db.commit()
        await self.db.refresh(artifact)
        logger.info(
            "draft_pitch: opportunity=%s grounding=%.3f", opportunity_id, gs
        )
        return artifact

    # ------------------------------------------------------------------
    # create_outreach
    # ------------------------------------------------------------------

    async def create_outreach(
        self,
        opportunity_id: uuid.UUID,
        pitch_artifact_id: uuid.UUID | None = None,
    ) -> ResearchOutreach:
        await self._get_opportunity(opportunity_id)  # 404 guard

        status = "drafted" if pitch_artifact_id is not None else "suggested"
        outreach = ResearchOutreach(
            user_id=self.user_id,
            research_opportunity_id=opportunity_id,
            status=status,
            pitch_artifact_id=pitch_artifact_id,
        )
        self.db.add(outreach)
        await self.db.commit()
        await self.db.refresh(outreach)
        return outreach

    # ------------------------------------------------------------------
    # list_outreach — user-scoped
    # ------------------------------------------------------------------

    async def list_outreach(self) -> list[ResearchOutreach]:
        return list(
            (
                await self.db.execute(
                    select(ResearchOutreach)
                    .where(ResearchOutreach.user_id == self.user_id)
                    .order_by(ResearchOutreach.created_at.desc())
                )
            )
            .scalars()
            .all()
        )

    # ------------------------------------------------------------------
    # update_status — 404 if not owned
    # ------------------------------------------------------------------

    async def update_status(
        self, outreach_id: uuid.UUID, status: str
    ) -> ResearchOutreach:
        if status not in OUTREACH_STATUSES:
            raise APIError(
                400,
                "INVALID_STATUS",
                f"status must be one of {sorted(OUTREACH_STATUSES)}",
            )
        outreach = await self._get_outreach_owned(outreach_id)
        outreach.status = status
        outreach.updated_at = datetime.now(UTC)
        self.db.add(outreach)
        await self.db.commit()
        await self.db.refresh(outreach)
        return outreach


# ---------------------------------------------------------------------------
# Standalone helper for seeding: create opportunity + compute embedding
# ---------------------------------------------------------------------------


async def create_opportunity(
    db: AsyncSession,
    *,
    professor_name: str,
    institution: str,
    research_area: str,
    description: str,
    desired_skills: list[str],
    lab_name: str | None = None,
    program: str | None = None,
    region: str | None = None,
    contact_email: str | None = None,
    url: str | None = None,
    source: str = "seed",
    posted_at: str | None = None,
    extra: dict[str, Any] | None = None,
) -> ResearchOpportunity:
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    embed_text = research_area + " " + description
    vectors = await embed([embed_text])
    opp = ResearchOpportunity(
        professor_name=professor_name,
        institution=institution,
        lab_name=lab_name,
        research_area=research_area,
        description=description,
        desired_skills=desired_skills,
        program=program,
        region=region,
        contact_email=contact_email,
        url=url,
        source=source,
        posted_at=posted_at or now,
        last_seen_at=now,
        embedding=vectors[0],
    )
    db.add(opp)
    return opp
