"""Profile service — Module 1.

All queries are scoped to self.user_id (data isolation rule).
CPU-bound work (PDF/docx parsing, embeddings) runs via asyncio.to_thread.
"""
from __future__ import annotations

import asyncio
import io
import re
import uuid
from typing import Any

import httpx
from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import APIError
from app.llm.embeddings import embed
from app.llm.extract import extract_structured
from app.models.profile import Profile
from app.schemas.profile import (
    EducationItem,
    ExperienceItem,
    PreferencesUpdateRequest,
    ProfileUpdateRequest,
    ProjectItem,
    ResumeExtract,
)
from app.services.base import BaseService
from app.services.university_normalizer import canonicalize as _canonicalize_uni

_MAX_FILE_BYTES = 5 * 1024 * 1024  # 5 MB
_MIN_TEXT_LEN = 50


# ---------------------------------------------------------------------------
# Module-level helpers — easy to mock in tests
# ---------------------------------------------------------------------------

def _extract_pdf_text(data: bytes) -> str:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def _extract_docx_text(data: bytes) -> str:
    import docx

    doc = docx.Document(io.BytesIO(data))
    return "\n".join(para.text for para in doc.paragraphs)


def _parse_github_username(url: str) -> str:
    url = url.strip().rstrip("/")
    if "github.com/" in url:
        after = url.split("github.com/", 1)[1]
        username = after.split("/")[0]
    else:
        username = url.split("/")[0]
    if not username or not re.match(
        r"^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,37}[a-zA-Z0-9])?$", username
    ):
        raise APIError(
            422, "INVALID_GITHUB_URL", "Could not parse a valid GitHub username from the provided URL"
        )
    return username


def _profile_text(profile: Profile) -> str:
    parts: list[str] = []
    if profile.headline:
        parts.append(profile.headline)
    for skill in profile.skills or []:
        if isinstance(skill, str):
            parts.append(skill)
    for interest in profile.research_interests or []:
        if isinstance(interest, str):
            parts.append(interest)
    for proj in profile.projects or []:
        if isinstance(proj, dict):
            if proj.get("name"):
                parts.append(str(proj["name"]))
            for tech in proj.get("tech") or []:
                parts.append(str(tech))
    return " ".join(parts)


def _compute_strength_and_gaps(profile: Profile) -> tuple[int, list[str]]:
    """Deterministic 0-100 score + concrete gap list."""
    strength = 0
    gaps: list[str] = []

    # Headline — 10 pts
    if profile.headline:
        strength += 10
    else:
        gaps.append("Add a professional headline")

    # Skills — up to 20 pts (2 per skill, capped at 10 skills)
    skill_count = len(profile.skills or [])
    strength += min(skill_count * 2, 20)
    if skill_count < 5:
        gaps.append(f"Add at least 5 skills (currently {skill_count})")

    # Experience — 20 pts
    if profile.experience:
        strength += 20
    else:
        gaps.append("Add work or internship experience")

    # Education — 15 pts
    if profile.education:
        strength += 15
    else:
        gaps.append("Add your education history")

    # Projects — up to 20 pts (10 per project, capped at 2)
    proj_count = len(profile.projects or [])
    strength += min(proj_count * 10, 20)
    if proj_count < 2:
        gaps.append(f"Add at least 2 projects (currently {proj_count})")

    # GitHub — 5 pts
    if profile.github_url:
        strength += 5
    else:
        gaps.append("Connect your GitHub profile")

    # Preferences: domains — 5 pts
    prefs: dict[str, Any] = profile.preferences or {}
    if prefs.get("domains"):
        strength += 5
    else:
        gaps.append("Set target domains (e.g. software engineering, data science)")

    # Preferences: target companies — 5 pts
    if prefs.get("target_companies"):
        strength += 5
    else:
        gaps.append("Set target companies")

    return min(strength, 100), gaps


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class ProfileService(BaseService):
    def __init__(self, db: AsyncSession, user_id: uuid.UUID) -> None:
        super().__init__(db, user_id)

    # Data-isolation helper — all selects call this
    def _q(self) -> Any:
        return select(Profile).where(Profile.user_id == self.user_id)

    async def get_or_create(self) -> Profile:
        result = await self.db.execute(self._q())
        profile = result.scalar_one_or_none()
        if profile is None:
            profile = Profile(user_id=self.user_id)
            self.db.add(profile)
            await self.db.commit()
            await self.db.refresh(profile)
        return profile

    async def _save(self, profile: Profile) -> Profile:
        """Compute strength/gaps, persist, refresh, then recompute embedding."""
        profile.university_canonical = (
            _canonicalize_uni(profile.university) or None
            if profile.university
            else None
        )
        profile.profile_strength, profile.gaps = _compute_strength_and_gaps(profile)
        text = _profile_text(profile)
        if text.strip():
            vectors = await embed([text])
            if vectors:
                profile.embedding = vectors[0]
        self.db.add(profile)
        await self.db.commit()
        await self.db.refresh(profile)
        return profile

    # -----------------------------------------------------------------------
    # Resume upload
    # -----------------------------------------------------------------------

    async def parse_resume(self, file: UploadFile) -> Profile:
        content = await file.read()
        if len(content) > _MAX_FILE_BYTES:
            raise APIError(413, "FILE_TOO_LARGE", "File must be ≤ 5 MB")

        filename = file.filename or ""
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext == "pdf":
            text = await asyncio.to_thread(_extract_pdf_text, content)
        elif ext == "docx":
            text = await asyncio.to_thread(_extract_docx_text, content)
        else:
            raise APIError(
                415,
                "UNSUPPORTED_FILE_TYPE",
                "Only PDF and DOCX résumés are supported",
            )

        if len(text.strip()) < _MIN_TEXT_LEN:
            raise APIError(
                422,
                "unparseable_resume",
                "No text could be extracted from the file. It may be a scanned image PDF.",
            )

        extracted: ResumeExtract = await extract_structured(
            text=text,
            schema=ResumeExtract,
            instructions=(
                "Extract the candidate's professional information from this résumé.\n\n"
                "Rules:\n"
                "- university: extract the candidate's university/college name if present.\n"
                "- grad_year: extract the expected or actual graduation year as an integer "
                "(e.g. 2025, 2026). If not explicitly stated, infer from education entries.\n"
                "- research_interests: list any research areas, academic interests, or "
                "specialisations mentioned (e.g. 'machine learning', 'computer vision', "
                "'distributed systems'). Empty list if none found.\n"
                "- github_url: extract verbatim if present (e.g. 'github.com/username' → "
                "'https://github.com/username').\n"
                "- domains: infer 2-4 professional domains from skills and experience "
                "(e.g. 'software engineering', 'machine learning', 'data science', "
                "'backend development', 'frontend development', 'devops', 'mobile').\n"
                "- target_companies: suggest 4-6 companies that are a strong fit for "
                "this candidate's background and seniority level. Be specific — name real "
                "companies (e.g. 'Google', 'Stripe', 'Figma', 'Scale AI')."
            ),
        )

        profile = await self.get_or_create()

        if extracted.headline:
            profile.headline = extracted.headline
        if extracted.university:
            profile.university = extracted.university
        if extracted.grad_year:
            profile.grad_year = extracted.grad_year
        if extracted.research_interests:
            profile.research_interests = extracted.research_interests
        if extracted.skills:
            existing: set[str] = {s for s in (profile.skills or []) if isinstance(s, str)}
            profile.skills = list(existing | set(extracted.skills))
        if extracted.experience:
            profile.experience = [e.model_dump() for e in extracted.experience]
        if extracted.education:
            profile.education = [e.model_dump() for e in extracted.education]
        if extracted.projects:
            profile.projects = [p.model_dump() for p in extracted.projects]
        if extracted.github_url:
            profile.github_url = extracted.github_url
        if extracted.domains or extracted.target_companies:
            prefs: dict[str, Any] = dict(profile.preferences or {})
            if extracted.domains:
                prefs["domains"] = extracted.domains
            if extracted.target_companies:
                prefs["target_companies"] = extracted.target_companies
            profile.preferences = prefs

        return await self._save(profile)

    # -----------------------------------------------------------------------
    # GitHub pull
    # -----------------------------------------------------------------------

    async def pull_github(self, github_url: str) -> Profile:
        username = _parse_github_username(github_url)

        headers: dict[str, str] = {"Accept": "application/vnd.github+json"}
        if settings.GITHUB_TOKEN:
            headers["Authorization"] = f"Bearer {settings.GITHUB_TOKEN}"

        async with httpx.AsyncClient(headers=headers, timeout=15.0) as http:
            repos_resp = await http.get(
                f"https://api.github.com/users/{username}/repos",
                params={"sort": "stars", "per_page": "20"},
            )
            if repos_resp.status_code == 404:
                raise APIError(
                    404, "GITHUB_USER_NOT_FOUND", f"GitHub user '{username}' not found"
                )
            if repos_resp.status_code == 403:
                raise APIError(429, "GITHUB_RATE_LIMITED", "GitHub API rate limit exceeded")
            repos_resp.raise_for_status()

            repos: list[dict[str, Any]] = repos_resp.json()
            top = sorted(repos, key=lambda r: r.get("stargazers_count", 0), reverse=True)[:5]

            new_projects: list[dict[str, Any]] = []
            new_skills: set[str] = set()

            for repo in top:
                lang_resp = await http.get(
                    f"https://api.github.com/repos/{username}/{repo['name']}/languages"
                )
                langs: list[str] = (
                    list(lang_resp.json().keys()) if lang_resp.status_code == 200 else []
                )
                new_skills.update(langs)
                new_projects.append(
                    {
                        "name": repo["name"],
                        "description": repo.get("description"),
                        "tech": langs,
                        "url": repo.get("html_url", ""),
                    }
                )

        profile = await self.get_or_create()

        existing_names = {p["name"] for p in (profile.projects or []) if isinstance(p, dict)}
        merged_projects = list(profile.projects or [])
        for proj in new_projects:
            if proj["name"] not in existing_names:
                merged_projects.append(proj)

        existing_skills: set[str] = {s for s in (profile.skills or []) if isinstance(s, str)}
        profile.skills = list(existing_skills | new_skills)
        profile.projects = merged_projects
        profile.github_url = github_url

        return await self._save(profile)

    # -----------------------------------------------------------------------
    # PUT /api/profile
    # -----------------------------------------------------------------------

    async def update_profile(self, body: ProfileUpdateRequest) -> Profile:
        profile = await self.get_or_create()
        update = body.model_dump(exclude_unset=True)

        for field in ("headline", "university", "grad_year", "research_interests", "skills", "github_url"):
            if field in update:
                setattr(profile, field, update[field])

        if "experience" in update and update["experience"] is not None:
            items: list[ExperienceItem] = update["experience"]
            profile.experience = [
                i.model_dump() if isinstance(i, ExperienceItem) else i for i in items
            ]
        if "education" in update and update["education"] is not None:
            edu_items: list[EducationItem] = update["education"]
            profile.education = [
                i.model_dump() if isinstance(i, EducationItem) else i for i in edu_items
            ]
        if "projects" in update and update["projects"] is not None:
            proj_items: list[ProjectItem] = update["projects"]
            profile.projects = [
                i.model_dump() if isinstance(i, ProjectItem) else i for i in proj_items
            ]

        return await self._save(profile)

    # -----------------------------------------------------------------------
    # PUT /api/profile/preferences
    # -----------------------------------------------------------------------

    async def update_preferences(self, body: PreferencesUpdateRequest) -> Profile:
        profile = await self.get_or_create()
        update = body.model_dump(exclude_unset=True)

        current: dict[str, Any] = dict(profile.preferences or {})
        for field, value in update.items():
            # WorkMode enum → store as its string value
            current[field] = value.value if hasattr(value, "value") else value
        profile.preferences = current

        return await self._save(profile)

    # -----------------------------------------------------------------------
    # GET /api/profile/strength
    # -----------------------------------------------------------------------

    async def get_strength(self) -> tuple[int, list[str]]:
        profile = await self.get_or_create()
        return profile.profile_strength, list(profile.gaps or [])
