"""ReferralService — Module 6: alumni candidate ranking + warm-intro drafting.

- find_candidates(): GLOBAL query (no user filter) — contacts are shared reference data.
- create_referral(), list_referrals(), update_status(): USER-SCOPED (BaseService isolation).
- LLM called only for intro drafting, with the same whitelist + guard-loop discipline as Module 7.
"""
from __future__ import annotations

import logging
import re
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError
from app.models.artifact import Artifact
from app.models.company import Company
from app.models.contact import Contact, RelationshipType
from app.models.posting import Posting
from app.models.profile import Profile
from app.models.referral import Referral, ReferralStatus
from app.schemas.referral import (
    ContactSchema,
    ReferralSchema,
    coerce_contact_schema,
    coerce_referral_schema,
)
from app.services.base import BaseService

logger = logging.getLogger(__name__)

_VALID_STATUSES = frozenset(s.value for s in ReferralStatus)

# Common tech terms used for fabrication detection (mirrors ghost_service._TECH_TERMS)
_TECH_TERMS: frozenset[str] = frozenset(
    {
        "python", "javascript", "typescript", "java", "go", "rust", "c++", "c#",
        "react", "vue", "angular", "node", "fastapi", "django", "flask",
        "postgresql", "mysql", "mongodb", "redis", "elasticsearch",
        "docker", "kubernetes", "terraform", "aws", "gcp", "azure",
        "pytorch", "tensorflow", "scikit-learn", "pandas", "numpy",
        "sql", "graphql", "rest", "grpc", "kafka", "rabbitmq",
        "git", "linux", "bash", "shell",
    }
)


# ---------------------------------------------------------------------------
# Ranking helpers
# ---------------------------------------------------------------------------


def _parse_batch_year(batch: str | None) -> int:
    """Parse a year from batch strings like '2024', 'S2024', 'F23', 'Fall 2025'."""
    if not batch:
        return 0
    digits = re.findall(r"\d+", batch)
    if not digits:
        return 0
    year = int(digits[-1])
    if year < 100:
        year += 2000
    return year


def _rank_contacts(
    contacts: list[Contact],
    *,
    student_university_canonical: str | None = None,
) -> list[Contact]:
    """Rank alumni: same-university (by canonical) first, then alumni > 2nd_degree > unknown; recent grad first."""
    rel_order = {
        RelationshipType.alumni: 1,
        RelationshipType.second_degree: 2,
        RelationshipType.unknown: 3,
    }

    def _key(c: Contact) -> tuple[int, int]:
        if (
            student_university_canonical
            and c.university_canonical
            and c.university_canonical == student_university_canonical
        ):
            rel_rank = 0
        else:
            rel_rank = rel_order.get(c.relationship, 3)
        return (rel_rank, -(c.grad_year or 0))

    return sorted(contacts, key=_key)


# ---------------------------------------------------------------------------
# Grounding helpers for intro drafting
# ---------------------------------------------------------------------------


def _intro_grounding_score(intro: str, whitelist_lower: set[str]) -> float:
    """Fraction of tech terms mentioned in intro that are covered by whitelist."""
    intro_lower = intro.lower()
    mentioned = [t for t in _TECH_TERMS if t in intro_lower]
    if not mentioned:
        return 1.0
    grounded = sum(
        1
        for t in mentioned
        if any(t in w or w in t for w in whitelist_lower)
    )
    return round(grounded / len(mentioned), 4)


def _find_fabricated_tech(intro: str, whitelist_lower: set[str]) -> list[str]:
    """Return tech terms in intro that are NOT covered by profile whitelist."""
    intro_lower = intro.lower()
    return [
        t
        for t in _TECH_TERMS
        if t in intro_lower and not any(t in w or w in t for w in whitelist_lower)
    ]


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class ReferralService(BaseService):
    def __init__(self, db: AsyncSession, user_id: uuid.UUID) -> None:
        super().__init__(db, user_id)

    def _scope(self, stmt: Any) -> Any:
        raise NotImplementedError(
            "Use stmt.where(Referral.user_id == self.user_id) directly"
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _get_profile(self) -> Profile | None:
        return (
            await self.db.execute(
                select(Profile).where(Profile.user_id == self.user_id)
            )
        ).scalar_one_or_none()

    async def _resolve_company_id(
        self,
        company_id: uuid.UUID | None,
        posting_id: uuid.UUID | None,
    ) -> uuid.UUID:
        if company_id is not None:
            return company_id
        if posting_id is not None:
            posting = await self.db.get(Posting, posting_id)
            if posting is None:
                raise APIError(404, "POSTING_NOT_FOUND", "Posting not found")
            return posting.company_id
        raise APIError(400, "MISSING_PARAMETER", "company_id or posting_id required")

    async def _load_referral_row(
        self, referral_id: uuid.UUID
    ) -> tuple[Referral, Contact, Company]:
        row = (
            await self.db.execute(
                select(Referral, Contact, Company)
                .join(Contact, Referral.contact_id == Contact.id)
                .join(Company, Contact.company_id == Company.id)
                .where(
                    Referral.id == referral_id,
                    Referral.user_id == self.user_id,
                )
            )
        ).first()
        if row is None:
            raise APIError(404, "REFERRAL_NOT_FOUND", "Referral not found")
        return row[0], row[1], row[2]

    def _build_schema(
        self, referral: Referral, contact: Contact, company: Company
    ) -> ReferralSchema:
        contact_schema = coerce_contact_schema(contact, company.name)
        return coerce_referral_schema(referral, contact_schema)

    # ------------------------------------------------------------------
    # find_candidates — GLOBAL (no user filter)
    # ------------------------------------------------------------------

    async def find_candidates(
        self,
        company_id: uuid.UUID | None = None,
        posting_id: uuid.UUID | None = None,
    ) -> list[ContactSchema]:
        resolved_company_id = await self._resolve_company_id(company_id, posting_id)

        rows = (
            await self.db.execute(
                select(Contact, Company)
                .join(Company, Contact.company_id == Company.id)
                .where(Contact.company_id == resolved_company_id)
            )
        ).all()

        if not rows:
            return []

        contacts = [r[0] for r in rows]
        company_name = rows[0][1].name

        # Use the student's own canonical university to boost same-alumni contacts in ranking
        profile = await self._get_profile()
        student_canonical = profile.university_canonical if profile else None

        ranked = _rank_contacts(contacts, student_university_canonical=student_canonical)
        return [coerce_contact_schema(c, company_name) for c in ranked]

    # ------------------------------------------------------------------
    # create_referral — drafts warm-intro, saves artifact + referral
    # ------------------------------------------------------------------

    async def create_referral(
        self,
        company_id: uuid.UUID,
        contact_id: uuid.UUID,
        posting_id: uuid.UUID | None = None,
    ) -> ReferralSchema:
        from app.llm.router import complete

        # Load contact + company
        row = (
            await self.db.execute(
                select(Contact, Company)
                .join(Company, Contact.company_id == Company.id)
                .where(Contact.id == contact_id)
            )
        ).first()
        if row is None:
            raise APIError(404, "CONTACT_NOT_FOUND", "Contact not found")
        contact: Contact = row[0]
        company: Company = row[1]

        # Load posting if provided
        posting: Posting | None = None
        if posting_id is not None:
            posting = await self.db.get(Posting, posting_id)
            if posting is None:
                raise APIError(404, "POSTING_NOT_FOUND", "Posting not found")

        # Load profile for grounding
        profile = await self._get_profile()
        skills: list[str] = list(profile.skills or []) if profile else []
        project_techs: list[str] = (
            [tech for proj in (profile.projects or []) for tech in proj.get("tech", [])]
            if profile
            else []
        )
        experience_entries = list(profile.experience or []) if profile else []
        experience_text = " ".join(
            f"{e.get('title', '')} {e.get('description', '')}"
            for e in experience_entries
        )

        whitelist = set(skills) | set(project_techs)
        whitelist_lower = {w.strip().lower() for w in whitelist}

        # Build system prompt with explicit whitelist
        if whitelist:
            allowed_str = ", ".join(sorted(whitelist))
            whitelist_rule = (
                f"VERIFIED SKILL WHITELIST: {allowed_str}. "
                "You may ONLY reference technologies and skills from this list. "
                "If a skill is not on this list, omit it — never claim a skill the "
                "candidate cannot demonstrate."
            )
        else:
            whitelist_rule = (
                "No confirmed skills — write only what the experience bullets describe. "
                "Do not infer or assume any technical skills."
            )

        student_uni = getattr(profile, "university", None) if profile else None
        intro_context = f"a student at {student_uni}" if student_uni else "a student"
        connection_context = (
            f"the shared {student_uni} alumni connection"
            if student_uni
            else "the alumni connection"
        )

        system_msg = (
            f"You are a career advisor helping {intro_context} write a warm, "
            "respectful, and concise referral request to a fellow alumnus. "
            f"{whitelist_rule} "
            f"The message must: (1) open with {connection_context}, "
            "(2) name the specific role and company, "
            "(3) cite 2-3 fit points grounded ONLY in the verified whitelist, "
            "(4) make ONE clear, low-commitment ask and explicitly offer an easy out — "
            "'advice or a forward' as alternatives — acknowledging they may not know the "
            "hiring manager and that a referral is a reputational bet for them. "
            "Keep it under 150 words, warm and respectful."
        )

        role_line = f"Role: {posting.title}" if posting else f"Company: {company.name}"
        contact_grad = contact.grad_year
        contact_uni = contact.university
        contact_line = (
            f"Alumnus: {contact.name}"
            + (f" (class of {contact_grad})" if contact_grad else "")
            + (f" from {contact_uni}" if contact_uni else "")
            + (f", {contact.role} at {company.name}" if contact.role else f" at {company.name}")
        )
        skills_line = (
            f"Your verified skills: {', '.join(sorted(whitelist))}"
            if whitelist
            else "No confirmed skills yet."
        )
        exp_summary = experience_text[:500] if experience_text else "No experience listed."

        user_msg = (
            f"{contact_line}\n"
            f"{role_line}\n"
            f"{skills_line}\n"
            f"Your experience context: {exp_summary}\n\n"
            "Write the warm-intro email. Subject line + body. "
            "End with an easy out: acknowledge they may not know the hiring manager "
            "and offer advice/a forward as alternatives to a direct referral."
        )

        intro_text = await complete([
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ])

        # Guard loop: if fabricated tech terms detected, retry once
        gs = _intro_grounding_score(intro_text, whitelist_lower)
        if gs < 0.7 and whitelist_lower:
            fabricated = _find_fabricated_tech(intro_text, whitelist_lower)
            if fabricated:
                names = ", ".join(fabricated)
                retry_msg = (
                    f"Your draft mentioned {names}. "
                    "The candidate does NOT have these skills — they are not on the "
                    "verified whitelist. Remove every reference to these skills and rewrite "
                    "using ONLY the whitelist. Output only the corrected intro."
                )
                try:
                    intro_text = await complete([
                        {"role": "system", "content": system_msg},
                        {"role": "user", "content": user_msg},
                        {"role": "assistant", "content": intro_text},
                        {"role": "user", "content": retry_msg},
                    ])
                    gs = _intro_grounding_score(intro_text, whitelist_lower)
                except Exception as exc:
                    logger.warning("referral intro retry failed, keeping first: %s", exc)

        # Save intro as Artifact
        artifact = Artifact(
            user_id=self.user_id,
            application_id=None,
            type="referral_intro",
            content=intro_text,
            ats_score=None,
            missing_keywords=[],
            grounding_score=gs,
            predicted_response=None,
            version=1,
        )
        self.db.add(artifact)
        await self.db.flush()

        # Create Referral
        referral = Referral(
            user_id=self.user_id,
            posting_id=posting_id,
            company_id=company_id,
            contact_id=contact_id,
            status=ReferralStatus.suggested,
            intro_artifact_id=artifact.id,
        )
        self.db.add(referral)
        await self.db.commit()
        await self.db.refresh(referral)

        return self._build_schema(referral, contact, company)

    # ------------------------------------------------------------------
    # list_referrals — user-scoped
    # ------------------------------------------------------------------

    async def list_referrals(self) -> list[ReferralSchema]:
        rows = (
            await self.db.execute(
                select(Referral, Contact, Company)
                .join(Contact, Referral.contact_id == Contact.id)
                .join(Company, Contact.company_id == Company.id)
                .where(Referral.user_id == self.user_id)
                .order_by(Referral.created_at.desc())
            )
        ).all()
        return [
            self._build_schema(row[0], row[1], row[2])
            for row in rows
        ]

    # ------------------------------------------------------------------
    # update_status — user-scoped
    # ------------------------------------------------------------------

    async def update_status(
        self,
        referral_id: uuid.UUID,
        status: str,
    ) -> ReferralSchema:
        if status not in _VALID_STATUSES:
            raise APIError(
                400,
                "INVALID_STATUS",
                f"status must be one of {sorted(_VALID_STATUSES)}",
            )
        referral, contact, company = await self._load_referral_row(referral_id)
        referral.status = ReferralStatus(status)
        self.db.add(referral)
        await self.db.commit()
        await self.db.refresh(referral)
        return self._build_schema(referral, contact, company)
