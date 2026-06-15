"""Pydantic schemas for Module 6 — Referral / Warm-Intro Finder."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

if TYPE_CHECKING:
    from app.models.contact import Contact
    from app.models.referral import Referral


class ContactSchema(BaseModel):
    id: uuid.UUID
    name: str
    company_id: uuid.UUID
    company_name: str
    role: str | None
    grad_year: int | None
    university: str | None
    linkedin: str | None
    relationship: str  # "alumni" | "second_degree" | "unknown"


def coerce_contact_schema(c: Contact, company_name: str) -> ContactSchema:
    return ContactSchema(
        id=c.id,
        name=c.name,
        company_id=c.company_id,
        company_name=company_name,
        role=c.role,
        grad_year=c.grad_year,
        university=c.university,
        linkedin=c.linkedin,
        relationship=str(c.relationship),
    )


class ReferralSchema(BaseModel):
    id: uuid.UUID
    posting_id: uuid.UUID | None
    company_id: uuid.UUID
    contact: ContactSchema
    status: str
    intro_artifact_id: uuid.UUID | None
    created_at: datetime


def coerce_referral_schema(
    r: Referral,
    contact_schema: ContactSchema,
) -> ReferralSchema:
    return ReferralSchema(
        id=r.id,
        posting_id=r.posting_id,
        company_id=r.company_id,
        contact=contact_schema,
        status=str(r.status),
        intro_artifact_id=r.intro_artifact_id,
        created_at=r.created_at,
    )


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------


class FindCandidatesResponse(BaseModel):
    data: list[ContactSchema]


class CreateReferralRequest(BaseModel):
    posting_id: uuid.UUID | None = None
    company_id: uuid.UUID
    contact_id: uuid.UUID


class CreateReferralResponse(BaseModel):
    referral: ReferralSchema


class ListReferralsResponse(BaseModel):
    data: list[ReferralSchema]


class UpdateReferralRequest(BaseModel):
    status: str


class UpdateReferralResponse(BaseModel):
    referral: ReferralSchema


__all__: list[Any] = [
    "ContactSchema",
    "ReferralSchema",
    "coerce_contact_schema",
    "coerce_referral_schema",
    "FindCandidatesResponse",
    "CreateReferralRequest",
    "CreateReferralResponse",
    "ListReferralsResponse",
    "UpdateReferralRequest",
    "UpdateReferralResponse",
]
