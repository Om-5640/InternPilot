"""Seed alumni contacts from a CSV file.

Usage:
    uv run python scripts/seed_alumni.py path/to/alumni.csv

CSV format (header row required):
    name,company,role,grad_year,university,linkedin,relationship

    name         — full name  (required)
    company      — company name (required) — resolved or created by normalized_name
    role         — job title (optional)
    grad_year    — graduation year as a plain integer, e.g. 2024, 2025 (optional)
    university   — alumnus's university/college name (optional)
    linkedin     — LinkedIn profile URL (optional)
    relationship — "alumni" | "second_degree" | "unknown" (default: alumni)

Example CSV:
    name,company,role,grad_year,university,linkedin,relationship
    Alex Chen,Google,SWE Intern,2024,MIT,https://linkedin.com/in/alexchen,alumni
    Sam Patel,Meta,PM,2025,Stanford,,alumni
    Jordan Kim,Netflix,Data Scientist,2023,UC Berkeley,,second_degree
"""
from __future__ import annotations

import asyncio
import contextlib
import csv
import re
import sys
from pathlib import Path

# Ensure the project root is on sys.path when run as a script
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings  # noqa: E402
from app.models.base import Base  # noqa: E402, F401
from app.models.company import Company  # noqa: E402
from app.models.contact import Contact, RelationshipType  # noqa: E402
from app.services.university_normalizer import canonicalize as _canonicalize_uni  # noqa: E402


def _normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


async def _resolve_or_create_company(
    session: AsyncSession, name: str
) -> Company:
    normalized = _normalize(name)
    row = (
        await session.execute(
            select(Company).where(Company.normalized_name == normalized)
        )
    ).scalar_one_or_none()
    if row is not None:
        return row
    company = Company(
        name=name,
        normalized_name=normalized,
        ghost_history_score=0.0,
        responsiveness_score=1.0,
    )
    session.add(company)
    await session.flush()
    return company


async def seed(csv_path: str) -> None:
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    created = 0
    skipped = 0

    async with session_factory() as session:
        with open(csv_path, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                name = row.get("name", "").strip()
                company_name = row.get("company", "").strip()
                if not name or not company_name:
                    print(f"  SKIP (missing name/company): {row}")
                    skipped += 1
                    continue

                company = await _resolve_or_create_company(session, company_name)

                rel_raw = row.get("relationship", "alumni").strip().lower()
                try:
                    relationship = RelationshipType(rel_raw)
                except ValueError:
                    relationship = RelationshipType.alumni

                grad_year_raw = row.get("grad_year", "").strip()
                grad_year: int | None = None
                if grad_year_raw:
                    with contextlib.suppress(ValueError):
                        grad_year = int(grad_year_raw)

                uni_raw = row.get("university", "").strip() or None
                contact = Contact(
                    name=name,
                    company_id=company.id,
                    role=row.get("role", "").strip() or None,
                    grad_year=grad_year,
                    university=uni_raw,
                    university_canonical=_canonicalize_uni(uni_raw) or None if uni_raw else None,
                    linkedin=row.get("linkedin", "").strip() or None,
                    relationship=relationship,
                    source="csv_seed",
                )
                session.add(contact)
                created += 1
                print(f"  + {name} @ {company_name} ({relationship})")

        await session.commit()

    await engine.dispose()
    print(f"\nDone. Created {created} contacts, skipped {skipped} rows.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: uv run python scripts/seed_alumni.py path/to/alumni.csv")
        sys.exit(1)
    asyncio.run(seed(sys.argv[1]))
