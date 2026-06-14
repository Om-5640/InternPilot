"""Base protocol and shared types for job-board source adapters."""
from __future__ import annotations

from typing import Protocol, TypedDict


class RawPosting(TypedDict):
    title: str
    company_name: str
    description: str
    source: str
    source_url: str
    location: str | None
    work_mode: str | None
    stipend: int | None
    posted_at: str | None
    requirements: list[str]


class Source(Protocol):
    name: str

    async def fetch(self) -> list[RawPosting]: ...
