from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class ResearchOpportunitySchema(BaseModel):
    id: uuid.UUID
    professor_name: str
    institution: str
    lab_name: str | None
    research_area: str
    description: str
    desired_skills: list[str]
    program: str | None
    region: str | None
    contact_email: str | None
    url: str | None
    source: str
    posted_at: str | None
    last_seen_at: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ResearchMatchSchema(BaseModel):
    opportunity: ResearchOpportunitySchema
    fit_score: float
    fit_explanation: str
    matched_skills: list[str]
    missing_skills: list[str]


class ResearchOutreachSchema(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    research_opportunity_id: uuid.UUID
    status: str
    pitch_artifact_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PitchRequest(BaseModel):
    opportunity_id: uuid.UUID


class CreateOutreachRequest(BaseModel):
    opportunity_id: uuid.UUID
    pitch_artifact_id: uuid.UUID | None = None


class UpdateOutreachRequest(BaseModel):
    status: str
