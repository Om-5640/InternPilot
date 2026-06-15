from __future__ import annotations

from pydantic import BaseModel


class PipelineCounts(BaseModel):
    saved: int = 0
    applied: int = 0
    viewed: int = 0
    responded: int = 0
    interview: int = 0
    offer: int = 0
    rejected: int = 0
    ghosted: int = 0


class DashboardSummary(BaseModel):
    pipeline: PipelineCounts
    response_rate: float
    ghosts_avoided: int
    time_saved_hours: float
    platform_iq: float
    iq_trend: list[float]


class DigestResponse(BaseModel):
    new_matches: int
    followup_due: int
    recent_responses: int
    ghosts_avoided: int
    platform_iq: float
