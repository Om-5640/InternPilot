"""ApplicationService — Module 7: Application Assistant.

All queries are scoped to self.user_id — never leaks cross-user data.
LLM is used ONLY for decode() and draft(). ATS scoring is deterministic.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import APIError
from app.models.application import Application
from app.models.artifact import Artifact
from app.models.company import Company
from app.models.posting import Posting
from app.models.profile import Profile
from app.models.user import User
from app.schemas.application import (
    ApplicationSchema,
    ArtifactSchema,
    coerce_application_schema,
    coerce_artifact_schema,
)
from app.services.base import BaseService
from app.services.matching_service import _response_likelihood_placeholder

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ATS scoring helpers — deterministic, no LLM
# ---------------------------------------------------------------------------

_SUFFIX_RE = re.compile(r"\.[a-z]{1,3}$")


def _normalize_kw(kw: str) -> str:
    return _SUFFIX_RE.sub("", kw.strip().lower())


def _kw_found(keyword: str, content_lower: str) -> bool:
    kw_lower = keyword.strip().lower()
    if kw_lower in content_lower:
        return True
    norm = _normalize_kw(kw_lower)
    if norm and norm != kw_lower and norm in content_lower:
        return True
    # Multi-word → acronym ("Project Management Professional" → "pmp")
    words = kw_lower.split()
    if len(words) > 1:
        acronym = "".join(w[0] for w in words if w)
        if len(acronym) >= 2 and acronym in content_lower:
            return True
    return False


def _compute_ats(keywords: list[str], content: str) -> tuple[int, list[str]]:
    """Returns (score 0..100, missing_keywords)."""
    if not keywords:
        return 100, []
    content_lower = content.lower()
    missing = [kw for kw in keywords if not _kw_found(kw, content_lower)]
    score = round(100 * (len(keywords) - len(missing)) / len(keywords))
    return score, missing


# ---------------------------------------------------------------------------
# Grounding score helper — deterministic, no LLM
# ---------------------------------------------------------------------------


def _grounding_score(
    draft: str,
    requirements: list[str],
    profile_skills: list[str],
    project_techs: list[str],
    experience_text: str,
) -> float:
    """Fraction of JD requirements mentioned in draft that are backed by profile evidence."""
    draft_lower = draft.lower()
    # Requirements actually claimed in the draft
    claimed = [r.strip().lower() for r in requirements if r.strip().lower() in draft_lower]
    if not claimed:
        return 1.0

    evidence: set[str] = set()
    for s in profile_skills:
        evidence.add(s.strip().lower())
    for t in project_techs:
        evidence.add(t.strip().lower())
    exp_lower = experience_text.lower()

    grounded = sum(1 for c in claimed if c in evidence or c in exp_lower)
    return round(grounded / len(claimed), 4)


# ---------------------------------------------------------------------------
# JSON parser for LLM responses
# ---------------------------------------------------------------------------


def _parse_llm_json(text: str) -> dict[str, Any]:
    text = text.strip()
    # Strip markdown fences if present
    text = re.sub(r"^```[a-z]*\n?", "", text)
    text = re.sub(r"\n?```$", "", text.strip())
    return json.loads(text.strip())  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class ApplicationService(BaseService):
    def __init__(self, db: AsyncSession, user_id: uuid.UUID) -> None:
        super().__init__(db, user_id)

    def _scope(self, stmt: Any) -> Any:
        raise NotImplementedError("Use .where(Application.user_id == self.user_id) directly")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _get_posting(self, posting_id: uuid.UUID) -> Posting:
        row = (
            await self.db.execute(select(Posting).where(Posting.id == posting_id))
        ).scalar_one_or_none()
        if row is None:
            raise APIError(404, "POSTING_NOT_FOUND", "Posting not found")
        return row

    async def _get_posting_with_company(
        self, posting_id: uuid.UUID
    ) -> tuple[Posting, Company]:
        result = (
            await self.db.execute(
                select(Posting, Company)
                .join(Company, Posting.company_id == Company.id)
                .where(Posting.id == posting_id)
            )
        ).one_or_none()
        if result is None:
            raise APIError(404, "POSTING_NOT_FOUND", "Posting not found")
        return result[0], result[1]

    async def _get_profile(self) -> Profile | None:
        return (
            await self.db.execute(
                select(Profile).where(Profile.user_id == self.user_id)
            )
        ).scalar_one_or_none()

    async def _get_user(self) -> User:
        row = (
            await self.db.execute(select(User).where(User.id == self.user_id))
        ).scalar_one_or_none()
        if row is None:
            raise APIError(401, "UNAUTHORIZED", "User not found")
        return row

    async def _get_artifact_owned(self, artifact_id: uuid.UUID) -> Artifact:
        row = (
            await self.db.execute(
                select(Artifact).where(
                    Artifact.id == artifact_id,
                    Artifact.user_id == self.user_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise APIError(404, "ARTIFACT_NOT_FOUND", "Artifact not found")
        return row

    async def _get_application_owned(self, application_id: uuid.UUID) -> Application:
        row = (
            await self.db.execute(
                select(Application)
                .where(
                    Application.id == application_id,
                    Application.user_id == self.user_id,
                )
                .options(selectinload(Application.artifacts))
            )
        ).scalar_one_or_none()
        if row is None:
            raise APIError(404, "APPLICATION_NOT_FOUND", "Application not found")
        return row

    async def _build_app_schema(self, app: Application) -> ApplicationSchema:
        posting, company = await self._get_posting_with_company(app.posting_id)
        return coerce_application_schema(
            app,
            posting.id,
            posting.title,
            company.name,
            list(app.artifacts),
        )

    # ------------------------------------------------------------------
    # decode — ONE LLM call
    # ------------------------------------------------------------------

    async def decode(self, posting_id: uuid.UUID) -> dict[str, Any]:
        from app.llm.router import complete

        posting = await self._get_posting(posting_id)
        reqs_json = json.dumps(list(posting.requirements or []))
        prompt = (
            "Analyze this job description and return a JSON object with exactly these keys:\n"
            '- "requirements": list of specific skills/qualifications required (strings)\n'
            '- "keywords": list of important keywords and technologies for a résumé/cover letter (strings)\n'
            '- "summary": 1-2 sentence summary of what this role is really looking for\n\n'
            f"Job title: {posting.title}\n"
            f"Description: {posting.description[:3000]}\n"
            f"Listed requirements: {reqs_json}\n\n"
            "Return ONLY valid JSON. No markdown, no explanation."
        )
        try:
            response = await complete([{"role": "user", "content": prompt}])
            data = _parse_llm_json(response)
        except Exception as exc:
            logger.exception("decode LLM call failed: %s", exc)
            raise APIError(500, "DECODE_FAILED", "Failed to decode job description") from exc

        return {
            "requirements": [str(r) for r in data.get("requirements", [])],
            "keywords": [str(k) for k in data.get("keywords", [])],
            "summary": str(data.get("summary", "")),
        }

    # ------------------------------------------------------------------
    # ats_score — DETERMINISTIC, no LLM
    # ------------------------------------------------------------------

    async def ats_score(self, posting_id: uuid.UUID, content: str) -> dict[str, Any]:
        posting = await self._get_posting(posting_id)
        keywords = [str(r) for r in (posting.requirements or [])]
        score, missing = _compute_ats(keywords, content)
        return {"ats_score": score, "missing_keywords": missing}

    # ------------------------------------------------------------------
    # draft — LLM + ats_score + grounding_score
    # ------------------------------------------------------------------

    async def draft(
        self, posting_id: uuid.UUID, artifact_type: str, channel: str
    ) -> ArtifactSchema:
        from app.llm.router import complete

        posting, company = await self._get_posting_with_company(posting_id)
        profile = await self._get_profile()

        # Build profile context
        skills: list[str] = []
        project_techs: list[str] = []
        experience_text = ""
        headline = ""
        exp_bullets = ""
        proj_bullets = ""
        edu_bullets = ""

        if profile is not None:
            skills = [str(s) for s in (profile.skills or [])]
            headline = profile.headline or ""
            for proj in (profile.projects or []):
                if isinstance(proj, dict):
                    for t in proj.get("tech", []):
                        project_techs.append(str(t))
            exp_parts: list[str] = []
            for exp in (profile.experience or []):
                if isinstance(exp, dict):
                    line = f"{exp.get('title','?')} at {exp.get('org','?')}"
                    desc = exp.get("description", "")
                    if desc:
                        line += f": {desc}"
                        experience_text += " " + str(desc)
                    exp_parts.append(line)
            exp_bullets = "\n".join(f"  - {e}" for e in exp_parts)
            proj_parts: list[str] = []
            for proj in (profile.projects or []):
                if isinstance(proj, dict):
                    tech_str = ", ".join(str(t) for t in proj.get("tech", []))
                    line = f"{proj.get('name','?')}: {proj.get('description','')}"
                    if tech_str:
                        line += f" (tech: {tech_str})"
                    proj_parts.append(line)
            proj_bullets = "\n".join(f"  - {p}" for p in proj_parts)
            edu_parts: list[str] = []
            for edu in (profile.education or []):
                if isinstance(edu, dict):
                    edu_parts.append(
                        f"{edu.get('degree','?')} at {edu.get('institution','?')}"
                    )
            edu_bullets = "\n".join(f"  - {e}" for e in edu_parts)

        reqs_str = ", ".join(str(r) for r in (posting.requirements or []))
        system_msg = (
            "You are a career advisor for internship applicants. "
            "Generate tailored application documents grounded STRICTLY in the candidate's real experience. "
            "DO NOT invent, assume, or fabricate any skills, projects, or experience not explicitly listed. "
            "Mirror JD keywords ONLY where the candidate genuinely has them. "
            "Use specific bullets: action verb + tool/skill + scope/context + outcome (quantify where possible)."
        )
        user_msg = (
            f"Generate a {artifact_type} for this internship application.\n\n"
            f"JOB:\n"
            f"Title: {posting.title}\n"
            f"Company: {company.name}\n"
            f"Description: {posting.description[:2000]}\n"
            f"Requirements: {reqs_str}\n"
            f"Channel: {channel}\n\n"
            f"CANDIDATE PROFILE (authoritative — use nothing outside this):\n"
            f"Headline: {headline}\n"
            f"Skills: {', '.join(skills)}\n"
            f"Experience:\n{exp_bullets or '  (none listed)'}\n"
            f"Projects:\n{proj_bullets or '  (none listed)'}\n"
            f"Education:\n{edu_bullets or '  (none listed)'}\n\n"
            f"Output only the document text. No preamble, no explanation."
        )

        try:
            content_text = await complete(
                [
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg},
                ]
            )
        except Exception as exc:
            logger.exception("draft LLM call failed: %s", exc)
            raise APIError(500, "DRAFT_FAILED", "Failed to generate draft") from exc

        keywords = [str(r) for r in (posting.requirements or [])]
        ats, missing = _compute_ats(keywords, content_text)
        gs = _grounding_score(
            content_text,
            keywords,
            skills,
            project_techs,
            experience_text,
        )

        artifact = Artifact(
            user_id=self.user_id,
            application_id=None,
            type=artifact_type,
            content=content_text,
            ats_score=ats,
            missing_keywords=missing,
            grounding_score=gs,
            predicted_response=None,
            version=1,
        )
        self.db.add(artifact)
        await self.db.commit()
        await self.db.refresh(artifact)
        return coerce_artifact_schema(artifact)

    # ------------------------------------------------------------------
    # create_application — snapshot predictions at create-time
    # ------------------------------------------------------------------

    async def create_application(
        self, posting_id: uuid.UUID, channel: str, artifact_id: uuid.UUID
    ) -> ApplicationSchema:
        artifact = await self._get_artifact_owned(artifact_id)
        posting, company = await self._get_posting_with_company(posting_id)

        predicted_prob = _response_likelihood_placeholder(posting)
        predicted_ghost = bool(posting.is_ghost)

        app = Application(
            user_id=self.user_id,
            posting_id=posting_id,
            channel=channel,
            status="saved",
            predicted_response_prob=predicted_prob,
            predicted_ghost=predicted_ghost,
        )
        self.db.add(app)
        await self.db.flush()  # get app.id

        # Link artifact to this application
        artifact.application_id = app.id
        self.db.add(artifact)
        await self.db.commit()
        await self.db.refresh(app)
        await self.db.refresh(artifact)

        return coerce_application_schema(
            app, posting.id, posting.title, company.name, [artifact]
        )

    # ------------------------------------------------------------------
    # send — requires gmail consent; always sets status=applied
    # ------------------------------------------------------------------

    async def send(self, application_id: uuid.UUID, via: str) -> ApplicationSchema:
        user = await self._get_user()
        if not user.consent.get("gmail", False):
            raise APIError(
                403, "GMAIL_CONSENT_REQUIRED", "Gmail consent required to send via Gmail"
            )

        app = await self._get_application_owned(application_id)
        now = datetime.now(UTC)
        app.status = "applied"
        app.applied_at = now
        app.last_status_at = now
        self.db.add(app)
        await self.db.commit()
        await self.db.refresh(app)

        if via == "gmail":
            # Best-effort Gmail send — token storage is a Module 8 concern.
            # Status is already applied regardless of send success.
            logger.info(
                "Gmail send for application %s: OAuth token storage is Module 8 — "
                "application marked applied.",
                app.id,
            )

        return await self._build_app_schema(app)

    # ------------------------------------------------------------------
    # list_applications — paginated, optional status filter
    # ------------------------------------------------------------------

    async def list_applications(
        self,
        status: str | None,
        page: int,
        limit: int,
    ) -> dict[str, Any]:
        base_filter = [Application.user_id == self.user_id]
        if status:
            base_filter.append(Application.status == status)

        total = (
            await self.db.execute(
                select(func.count())
                .select_from(Application)
                .where(*base_filter)
            )
        ).scalar_one()

        apps = list(
            (
                await self.db.execute(
                    select(Application)
                    .where(*base_filter)
                    .options(selectinload(Application.artifacts))
                    .order_by(Application.created_at.desc())
                    .limit(limit)
                    .offset((page - 1) * limit)
                )
            ).scalars().all()
        )

        # Batch-load posting + company for all applications
        posting_ids = [a.posting_id for a in apps]
        posting_map: dict[uuid.UUID, tuple[Posting, Company]] = {}
        if posting_ids:
            rows = (
                await self.db.execute(
                    select(Posting, Company)
                    .join(Company, Posting.company_id == Company.id)
                    .where(Posting.id.in_(posting_ids))
                )
            ).all()
            posting_map = {p.id: (p, c) for p, c in rows}

        data = [
            coerce_application_schema(
                a,
                posting_map[a.posting_id][0].id,
                posting_map[a.posting_id][0].title,
                posting_map[a.posting_id][1].name,
                list(a.artifacts),
            )
            for a in apps
            if a.posting_id in posting_map
        ]
        return {"data": data, "page": page, "limit": limit, "total": int(total)}

    # ------------------------------------------------------------------
    # get_application
    # ------------------------------------------------------------------

    async def get_application(self, application_id: uuid.UUID) -> ApplicationSchema:
        app = await self._get_application_owned(application_id)
        return await self._build_app_schema(app)

    # ------------------------------------------------------------------
    # update_application — status and/or notes
    # ------------------------------------------------------------------

    async def update_application(
        self,
        application_id: uuid.UUID,
        status: str | None,
        notes: str | None,
    ) -> ApplicationSchema:
        app = await self._get_application_owned(application_id)
        if status is not None:
            app.status = status
            app.last_status_at = datetime.now(UTC)
        if notes is not None:
            app.notes = notes
        self.db.add(app)
        await self.db.commit()
        await self.db.refresh(app)
        # Reload artifacts after refresh
        app2 = await self._get_application_owned(application_id)
        return await self._build_app_schema(app2)

    # ------------------------------------------------------------------
    # update_artifact — edit content, bump version
    # ------------------------------------------------------------------

    async def update_artifact(
        self, artifact_id: uuid.UUID, content: str
    ) -> ArtifactSchema:
        artifact = await self._get_artifact_owned(artifact_id)
        artifact.content = content
        artifact.version = (artifact.version or 1) + 1

        # Re-score ATS if we have a linked application → posting
        if artifact.application_id is not None:
            app = (
                await self.db.execute(
                    select(Application).where(Application.id == artifact.application_id)
                )
            ).scalar_one_or_none()
            if app is not None:
                posting = await self._get_posting(app.posting_id)
                keywords = [str(r) for r in (posting.requirements or [])]
                ats, missing = _compute_ats(keywords, content)
                artifact.ats_score = ats
                artifact.missing_keywords = missing

        self.db.add(artifact)
        await self.db.commit()
        await self.db.refresh(artifact)
        return coerce_artifact_schema(artifact)
