"""Interview Prep service — Module 9.

Single LLM call via extract_structured; branches on opportunity_type (company vs research)
and region (India campus vs US/EU/global).  Anti-fabrication guard mirrors Module 7.
All records are USER-OWNED (data isolation rule).
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError
from app.llm.extract import extract_structured
from app.models.interview_prep import InterviewPrep
from app.models.profile import Profile
from app.schemas.interview_prep import (
    InterviewPrepSchema,
    OpportunityType,
    PrepExtract,
    PrepQuestion,
    PrepRequest,
    coerce_prep_schema,
)
from app.services.base import BaseService

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Company-type classifier
# ---------------------------------------------------------------------------

_SERVICE_INDICATORS: frozenset[str] = frozenset({
    "consulting", "infosys", "tcs", "wipro", "accenture", "cognizant",
    "capgemini", "deloitte", "hcl", "ibm", "tech mahindra", "cts",
    "mphasis", "hexaware", "mindtree", "ltimindtree", "ltts", "ntt data",
    "dxc", "kyndryl",
})


def _classify_company_type(company_name: str, opp_type: OpportunityType) -> str:
    if opp_type == OpportunityType.research:
        return "research_lab"
    lower = company_name.lower()
    if any(ind in lower for ind in _SERVICE_INDICATORS):
        return "service"
    return "product"


# ---------------------------------------------------------------------------
# Region helpers
# ---------------------------------------------------------------------------

_INDIA_TOKENS: frozenset[str] = frozenset({
    "india", "mumbai", "delhi", "bangalore", "bengaluru", "hyderabad",
    "chennai", "pune", "kolkata", "noida", "gurugram", "gurgaon",
    "campus", "on-campus", "on campus",
})


def _is_india_region(region: str | None) -> bool:
    if not region:
        return False
    lower = region.lower()
    return any(tok in lower for tok in _INDIA_TOKENS)


# ---------------------------------------------------------------------------
# Grounding helpers (mirror Module 7)
# ---------------------------------------------------------------------------

def _project_names_lower(projects: list[dict[str, Any]]) -> set[str]:
    return {p.get("name", "").lower() for p in projects if p.get("name")}


def _question_mentions_unknown_project(
    q: PrepQuestion,
    known_names: set[str],
) -> bool:
    """True if a project-category question references a project not in the profile."""
    if q.category != "project":
        return False
    text = (q.q + " " + (q.answer_guidance or "") + " " + (q.ideal_answer_outline or "")).lower()
    # If we can't find ANY known project name, the question may be fabricated
    return bool(known_names) and not any(name in text for name in known_names)


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

def _profile_summary(profile: Profile | None) -> str:
    if not profile:
        return "No profile data available."
    parts: list[str] = []
    if profile.skills:
        parts.append(f"Skills: {', '.join(str(s) for s in profile.skills[:20])}")
    if profile.research_interests:
        parts.append(f"Research interests: {', '.join(str(r) for r in profile.research_interests)}")
    for proj in (profile.projects or [])[:5]:
        if not isinstance(proj, dict):
            continue
        name = proj.get("name", "")
        desc = proj.get("description", "")
        tech = ", ".join(proj.get("tech") or [])
        parts.append(f"Project '{name}': {desc} | Tech: {tech}")
    for exp in (profile.experience or [])[:3]:
        if not isinstance(exp, dict):
            continue
        parts.append(
            f"Experience: {exp.get('title', '')} @ {exp.get('org', '')} — {exp.get('description', '')[:120]}"
        )
    return "\n".join(parts) or "No profile data."


def _build_instructions(
    req: PrepRequest,
    profile: Profile | None,
    company_type: str,
    is_india: bool,
    is_research: bool,
    whitelist_str: str,
    project_names_str: str,
    research_area: str,
) -> str:
    if is_research:
        return (
            f"Generate interview prep for a RESEARCH POSITION at {req.company_name}, role: {req.role}.\n"
            f"Research area / topic: {research_area}\n\n"
            "STRUCTURE — include these categories (no coding, no GD):\n"
            "  research_fit (2–3 questions): Why this lab/professor; how the student's interests "
            "align; evidence of engagement with the research area.\n"
            "  domain_depth (3–4 questions): Core technical concepts, seminal papers, open problems "
            "in the research area.\n"
            "  methods (2–3 questions): Techniques, tools, experimental or theoretical approaches "
            "relevant to the area.\n"
            "  project (2–3 questions): The student's REAL projects/papers as evidence of research "
            f"aptitude. ONLY reference these real projects: {project_names_str}.\n"
            "  behavioral (1–2 questions): Motivation, independence, long-term research goals. STAR format.\n\n"
            f"SKILL WHITELIST (only reference skills/tech from this list): {whitelist_str}\n\n"
            "OUTPUT RULES:\n"
            "  - Total 10–14 questions.\n"
            "  - Each question: q, type ('technical'/'behavioral'), category, difficulty, "
            "answer_guidance, ideal_answer_outline.\n"
            "  - weak_spots: 3–5 real gaps between student background and research area requirements.\n"
            "  - reverse_questions: exactly 2 smart questions the student can ask the professor/PI.\n"
            "  - NEVER invent skills, projects, or research interests not in the profile."
        )

    region_label = "India campus" if is_india else "US/EU/global"
    gd_rule = (
        "INCLUDE exactly 1 GD (group discussion) topic question (category='gd', type='gd'). "
        "GD format: ~12–14 participants, concise points style."
        if is_india
        else "Do NOT include any GD question. Regional context is non-India."
    )
    coding_rule = (
        "Include 4–5 DSA/coding questions at medium–hard difficulty (arrays, trees, DP, graphs)."
        if company_type == "product"
        else "Include 2 basic coding questions at easy–medium difficulty. Focus on fundamentals over DSA."
    )
    return (
        f"Generate interview prep for a COMPANY POSITION at {req.company_name} "
        f"(company_type={company_type}), role: {req.role}, region: {region_label}.\n\n"
        f"REGION RULE: {gd_rule}\n"
        f"CODING RULE: {coding_rule}\n\n"
        "ROUND STRUCTURE — include these categories:\n"
        "  coding: DSA / algorithms (calibrated above).\n"
        "  cs_fundamentals: OOP, DBMS/SQL joins + indexing, OS/networking if role-relevant.\n"
        f"  project (3–4 questions): Deep-dive into the student's REAL projects only: {project_names_str}. "
        "Ask about tech-stack rationale, challenges, and trade-offs.\n"
        "  behavioral/hr: Self-intro, motivation, strengths/weaknesses. STAR guidance.\n"
        + ("  gd: One group-discussion topic.\n" if is_india else "")
        + f"\nSKILL WHITELIST (only reference these): {whitelist_str}\n\n"
        "OUTPUT RULES:\n"
        "  - Total 10–14 questions.\n"
        "  - Each question: q, type ('technical'/'behavioral'/'gd'), category, difficulty, "
        "answer_guidance, ideal_answer_outline.\n"
        "  - weak_spots: 3–5 real gaps between profile and role requirements.\n"
        "  - reverse_questions: exactly 2 smart questions for the student to ask.\n"
        "  - NEVER invent projects, skills, or experiences not in the student's profile."
    )


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class InterviewPrepService(BaseService):
    def __init__(self, db: AsyncSession, user_id: uuid.UUID) -> None:
        super().__init__(db, user_id)

    def _scope(self, stmt: Any) -> Any:
        raise NotImplementedError("Use stmt.where(InterviewPrep.user_id == self.user_id) directly")

    async def _load_profile(self) -> Profile | None:
        return (
            await self.db.execute(
                select(Profile).where(Profile.user_id == self.user_id)
            )
        ).scalar_one_or_none()

    async def generate(self, req: PrepRequest) -> InterviewPrepSchema:
        # Validate application_id belongs to this user if provided
        if req.application_id is not None:
            from app.models.application import Application
            app_row = (
                await self.db.execute(
                    select(Application).where(
                        Application.id == req.application_id,
                        Application.user_id == self.user_id,
                    )
                )
            ).scalar_one_or_none()
            if app_row is None:
                raise APIError(404, "APPLICATION_NOT_FOUND", "Application not found")

        profile = await self._load_profile()
        opp_type = req.opportunity_type
        is_research = opp_type == OpportunityType.research
        is_india = _is_india_region(req.region)
        company_type = _classify_company_type(req.company_name, opp_type)

        # Build profile context for the LLM
        skills: list[str] = list(profile.skills or []) if profile else []
        projects: list[dict[str, Any]] = list(profile.projects or []) if profile else []
        research_interests: list[str] = list(profile.research_interests or []) if profile else []

        project_techs = [t for p in projects for t in (p.get("tech") or [])]
        whitelist: set[str] = set(skills) | set(project_techs)
        whitelist_str = ", ".join(sorted(whitelist)) if whitelist else "no confirmed skills"
        project_names = [p.get("name", "") for p in projects if p.get("name")]
        project_names_str = (
            ", ".join(f"'{n}'" for n in project_names) if project_names else "no listed projects"
        )
        research_area = (
            req.research_area
            or (", ".join(research_interests[:3]) if research_interests else req.role)
        )

        instructions = _build_instructions(
            req=req,
            profile=profile,
            company_type=company_type,
            is_india=is_india,
            is_research=is_research,
            whitelist_str=whitelist_str,
            project_names_str=project_names_str,
            research_area=research_area,
        )
        profile_text = _profile_summary(profile)

        extracted: PrepExtract = await extract_structured(
            text=profile_text,
            schema=PrepExtract,
            instructions=instructions,
        )

        # Grounding guard: check project questions reference real projects
        if project_names:
            known_lower = _project_names_lower(projects)
            bad_qs = [q for q in extracted.questions if _question_mentions_unknown_project(q, known_lower)]
            if bad_qs:
                logger.warning(
                    "interview_prep: %d project question(s) may reference unknown projects; "
                    "removing from output",
                    len(bad_qs),
                )
                extracted.questions = [q for q in extracted.questions if q not in bad_qs]

        # Enforce floor on question count after filtering
        if len(extracted.questions) < 5:
            raise APIError(
                422,
                "prep_generation_failed",
                "Could not generate enough grounded questions for this profile.",
            )

        # Persist
        prep = InterviewPrep(
            user_id=self.user_id,
            application_id=req.application_id,
            company_name=req.company_name,
            role=req.role,
            opportunity_type=opp_type.value,
            region=req.region,
            company_type=company_type,
            questions=[q.model_dump() for q in extracted.questions],
            weak_spots=list(extracted.weak_spots),
            reverse_questions=list(extracted.reverse_questions),
        )
        self.db.add(prep)
        await self.db.commit()
        await self.db.refresh(prep)
        return coerce_prep_schema(prep)

    async def get(self, prep_id: uuid.UUID) -> InterviewPrepSchema:
        row = (
            await self.db.execute(
                select(InterviewPrep).where(
                    InterviewPrep.id == prep_id,
                    InterviewPrep.user_id == self.user_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise APIError(404, "PREP_NOT_FOUND", "Interview prep not found")
        return coerce_prep_schema(row)
