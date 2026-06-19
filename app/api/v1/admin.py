"""Admin utilities — seed demo data, etc.

All endpoints require an X-Admin-Token header that must match
the ADMIN_SEED_TOKEN environment variable set on Render.
"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.llm.embeddings import embed
from app.models.company import Company
from app.models.contact import Contact, RelationshipType
from app.models.posting import Posting
from app.services.ghost_service import GhostService

logger = logging.getLogger(__name__)
router = APIRouter(tags=["admin"])

# ---------------------------------------------------------------------------
# Auth guard
# ---------------------------------------------------------------------------

def _check_token(request: Request) -> None:
    token = request.headers.get("X-Admin-Token", "")
    if not settings.ADMIN_SEED_TOKEN or token != settings.ADMIN_SEED_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid or missing X-Admin-Token header")


# ---------------------------------------------------------------------------
# Seed data (mirrors scripts/seed_demo.py — companies + postings + alumni)
# ---------------------------------------------------------------------------

SEED_SOURCE = "admin_seed"
NOW = datetime.now(UTC)

COMPANY_DEFS = [
    {"name": "Google",     "domain": "google.com",    "industry": "Technology",          "size": "10001+",    "archetype": "responsive"},
    {"name": "Stripe",     "domain": "stripe.com",    "industry": "FinTech",             "size": "1001-5000", "archetype": "responsive"},
    {"name": "Figma",      "domain": "figma.com",     "industry": "Design Tools",        "size": "501-1000",  "archetype": "responsive"},
    {"name": "Notion",     "domain": "notion.so",     "industry": "Productivity",        "size": "201-500",   "archetype": "responsive"},
    {"name": "Microsoft",  "domain": "microsoft.com", "industry": "Technology",          "size": "10001+",    "archetype": "mixed"},
    {"name": "Amazon",     "domain": "amazon.com",    "industry": "E-Commerce / Cloud",  "size": "10001+",    "archetype": "mixed"},
    {"name": "Snowflake",  "domain": "snowflake.com", "industry": "Cloud Data",          "size": "5001-10000","archetype": "responsive"},
    {"name": "Databricks", "domain": "databricks.com","industry": "Data / AI",           "size": "1001-5000", "archetype": "mixed"},
]

POSTING_TEMPLATES: dict[str, list[dict]] = {
    "Google": [
        {"title": "Software Engineering Intern – Core Infrastructure",
         "description": "Join the team building the backbone of Google's cloud infrastructure. Work with distributed systems, contribute to reliability engineering, and improve performance at scale using Python, Go, and C++. You will own end-to-end features, write production code, and collaborate with senior engineers across SRE and infrastructure teams.",
         "requirements": ["Python", "Go", "Distributed Systems", "Linux", "Data Structures", "Algorithms"],
         "location": "Mountain View, CA", "work_mode": "hybrid", "stipend": 9200, "days_ago": 10},
        {"title": "Machine Learning Intern – Ads Ranking",
         "description": "Develop and deploy machine learning models that power Google Ads ranking. Use PyTorch and TensorFlow to design experiments, analyze large-scale datasets with SQL and BigQuery, and push improvements to production that impact billions of users globally.",
         "requirements": ["Python", "PyTorch", "TensorFlow", "SQL", "Machine Learning", "Statistics"],
         "location": "New York, NY", "work_mode": "hybrid", "stipend": 9500, "days_ago": 8},
    ],
    "Stripe": [
        {"title": "Backend Engineer Intern – Payments Platform",
         "description": "Help Stripe scale the global payments network. Build APIs in Go, improve reliability of payment flows, and work on fraud-detection pipelines backed by PostgreSQL and Redis. You will write production code from day one and participate in design reviews.",
         "requirements": ["Go", "Python", "REST APIs", "PostgreSQL", "Distributed Systems"],
         "location": "San Francisco, CA", "work_mode": "hybrid", "stipend": 9000, "days_ago": 12},
        {"title": "Data Engineering Intern – Revenue Analytics",
         "description": "Build the data pipelines that power Stripe's financial analytics. Use Python, Spark, and dbt to transform raw event streams into actionable insights. Work closely with finance and product analytics teams.",
         "requirements": ["Python", "SQL", "Spark", "dbt", "Airflow", "Data Engineering"],
         "location": "Remote", "work_mode": "remote", "stipend": 8500, "days_ago": 6},
    ],
    "Figma": [
        {"title": "Frontend Engineer Intern",
         "description": "Contribute to Figma's web editor used by millions of designers. Work in TypeScript and React to ship new UI features, improve canvas performance, and write WebGL rendering code.",
         "requirements": ["TypeScript", "React", "JavaScript", "CSS", "WebGL"],
         "location": "San Francisco, CA", "work_mode": "onsite", "stipend": 8800, "days_ago": 5},
    ],
    "Notion": [
        {"title": "Backend Engineer Intern – Real-Time Collaboration",
         "description": "Work on the real-time sync engine powering collaborative editing in Notion. Use TypeScript, Rust, and CRDTs to build features used by 40M+ users. Ship production code and participate in on-call rotations.",
         "requirements": ["TypeScript", "Rust", "PostgreSQL", "Redis", "Distributed Systems"],
         "location": "San Francisco, CA", "work_mode": "hybrid", "stipend": 8400, "days_ago": 14},
        {"title": "Data Science Intern – Growth Analytics",
         "description": "Use SQL and Python to analyze user behavior, run A/B experiments, and build dashboards that inform product decisions. Partner with the growth and product teams to identify levers for retention and activation.",
         "requirements": ["Python", "SQL", "Statistics", "A/B Testing", "pandas", "Tableau"],
         "location": "Remote", "work_mode": "remote", "stipend": 7800, "days_ago": 9},
    ],
    "Microsoft": [
        {"title": "Software Engineering Intern – Azure DevOps",
         "description": "Join the Azure DevOps team building developer tools used by millions of teams. Work with C#, TypeScript, and Azure services to ship features that improve CI/CD pipelines.",
         "requirements": ["C#", "TypeScript", "Azure", "REST APIs", "Git"],
         "location": "Redmond, WA", "work_mode": "hybrid", "stipend": 8200, "days_ago": 20},
        {"title": "Data Science Intern – Microsoft 365",
         "description": "Apply machine learning and statistical modeling to improve Microsoft 365. Use Python and Azure ML to build models that personalize content recommendations and detect usage anomalies.",
         "requirements": ["Python", "Machine Learning", "SQL", "Azure", "scikit-learn", "Statistics"],
         "location": "Redmond, WA", "work_mode": "hybrid", "stipend": 8000, "days_ago": 18},
    ],
    "Amazon": [
        {"title": "Software Development Engineer Intern – AWS S3",
         "description": "Build and scale the world's most used object-storage system. Work in Java and Python on distributed systems, contribute to S3's reliability roadmap, and own a feature from design doc to deployment.",
         "requirements": ["Java", "Python", "Distributed Systems", "AWS", "Data Structures", "Algorithms"],
         "location": "Seattle, WA", "work_mode": "onsite", "stipend": 8700, "days_ago": 15},
        {"title": "Applied Scientist Intern – Alexa AI",
         "description": "Research and implement NLP models to improve Alexa's natural language understanding. Use PyTorch and TensorFlow to train dialogue models, run experiments at scale.",
         "requirements": ["Python", "PyTorch", "NLP", "Machine Learning", "Statistics"],
         "location": "Seattle, WA", "work_mode": "onsite", "stipend": 9100, "days_ago": 11},
    ],
    "Snowflake": [
        {"title": "Data Engineering Intern – Cloud Platform",
         "description": "Join Snowflake's Cloud Platform team to build the pipelines and tooling that power data warehousing for thousands of enterprises. Work in Python and SQL to design scalable data models and optimize query performance.",
         "requirements": ["Python", "SQL", "Data Engineering", "Cloud Computing", "dbt", "Airflow"],
         "location": "San Mateo, CA", "work_mode": "hybrid", "stipend": 9000, "days_ago": 7},
    ],
    "Databricks": [
        {"title": "ML Platform Engineer Intern",
         "description": "Help build the MLflow and Lakehouse AI infrastructure used by data teams worldwide. Work in Python and Scala to improve experiment tracking, model registry, and deployment tooling.",
         "requirements": ["Python", "Machine Learning", "MLflow", "Spark", "SQL", "Docker"],
         "location": "San Francisco, CA", "work_mode": "hybrid", "stipend": 8800, "days_ago": 13},
        {"title": "Data Science Intern – Platform Analytics",
         "description": "Use Python and SQL to analyse usage patterns across the Databricks platform, run A/B experiments to improve onboarding, and build dashboards that guide product decisions.",
         "requirements": ["Python", "SQL", "Statistics", "A/B Testing", "pandas", "Spark"],
         "location": "San Francisco, CA", "work_mode": "hybrid", "stipend": 8400, "days_ago": 16},
    ],
}

ALUMNI_CONTACTS: dict[str, list[dict]] = {
    "Google":    [{"name": "Maya Rodriguez", "role": "SWE Intern → FTE", "grad_year": 2024, "university": "MIT", "relationship": "alumni"},
                  {"name": "James Liu", "role": "Software Engineer", "grad_year": 2023, "university": "UC Berkeley", "relationship": "alumni"}],
    "Stripe":    [{"name": "Sophie Tan", "role": "Backend Engineer", "grad_year": 2024, "university": "University of Toronto", "relationship": "alumni"},
                  {"name": "Nina Koval", "role": "Data Engineer", "grad_year": 2023, "university": "ETH Zurich", "relationship": "alumni"}],
    "Figma":     [{"name": "Leo Martinez", "role": "Frontend Engineer", "grad_year": 2024, "university": "UC Berkeley", "relationship": "alumni"}],
    "Notion":    [{"name": "Avery Johnson", "role": "Backend Engineer", "grad_year": 2023, "university": "Stanford", "relationship": "alumni"}],
    "Microsoft": [{"name": "Marcus Wright", "role": "SWE", "grad_year": 2022, "university": "Georgia Tech", "relationship": "alumni"}],
    "Amazon":    [{"name": "Natalie Xu", "role": "SDE II", "grad_year": 2022, "university": "University of Washington", "relationship": "alumni"}],
    "Snowflake": [{"name": "Yuki Tanaka", "role": "Data Engineer", "grad_year": 2023, "university": "UC Berkeley", "relationship": "alumni"}],
    "Databricks":[{"name": "Fatima Al-Amin", "role": "ML Engineer", "grad_year": 2023, "university": "MIT", "relationship": "second_degree"}],
}


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


async def _resolve_company(db: AsyncSession, cdef: dict) -> Company:
    norm = _norm(cdef["name"])
    row = (await db.execute(select(Company).where(Company.normalized_name == norm))).scalar_one_or_none()
    if row is not None:
        return row
    c = Company(
        name=cdef["name"], normalized_name=norm,
        domain=cdef.get("domain"), industry=cdef.get("industry"), size=cdef.get("size"),
        ghost_history_score=0.0, responsiveness_score=1.0, cohort_applied_count=0,
    )
    db.add(c)
    await db.flush()
    return c


async def _seed_posting(db: AsyncSession, company: Company, tmpl: dict, idx: int) -> bool:
    domain = company.domain or (_norm(company.name) + ".io")
    source_url = f"https://{domain}/careers/seed-{_norm(company.name)}-{idx}"
    existing = (await db.execute(select(Posting).where(Posting.source_url == source_url))).scalar_one_or_none()
    if existing is not None:
        return False

    days_ago = tmpl.get("days_ago", 10)
    posted_dt = (NOW - timedelta(days=days_ago)).isoformat()
    dedup_key = hashlib.sha1(source_url.encode()).hexdigest()[:64]

    p = Posting(
        company_id=company.id,
        title=tmpl["title"],
        description=tmpl["description"],
        requirements=tmpl.get("requirements", []),
        location=tmpl.get("location"),
        work_mode=tmpl.get("work_mode", "any"),
        stipend=tmpl.get("stipend"),
        source=SEED_SOURCE,
        source_url=source_url,
        posted_at=posted_dt,
        last_seen_at=posted_dt,
        status="active",
        ghost_score=0.0,
        is_ghost=False,
        dedup_key=dedup_key,
        source_sightings=1,
    )

    embed_text = f"{p.title} at {company.name}. {p.description[:800]}"
    try:
        vectors = await embed([embed_text])
        if vectors:
            p.embedding = vectors[0]
    except Exception as exc:  # noqa: BLE001
        logger.warning("seed embed failed: %s", exc)

    db.add(p)
    await db.flush()
    return True


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.post("/admin/seed")
async def seed_demo(request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    """Seed demo companies, postings (with embeddings), and alumni contacts.

    Requires header: X-Admin-Token: <ADMIN_SEED_TOKEN env var>
    Safe to call multiple times — skips rows that already exist.
    """
    _check_token(request)

    companies: dict[str, Company] = {}
    for cdef in COMPANY_DEFS:
        companies[cdef["name"]] = await _resolve_company(db, cdef)
    await db.commit()

    new_postings = 0
    for cname, templates in POSTING_TEMPLATES.items():
        co = companies[cname]
        for i, tmpl in enumerate(templates):
            created = await _seed_posting(db, co, tmpl, i)
            if created:
                new_postings += 1
    await db.commit()

    # Alumni contacts
    new_contacts = 0
    for cname, contacts in ALUMNI_CONTACTS.items():
        co = companies[cname]
        for cdata in contacts:
            exists = (await db.execute(
                select(Contact).where(Contact.name == cdata["name"], Contact.company_id == co.id)
            )).scalar_one_or_none()
            if exists is None:
                db.add(Contact(
                    name=cdata["name"], company_id=co.id,
                    role=cdata.get("role"), grad_year=cdata.get("grad_year"),
                    university=cdata.get("university"),
                    relationship=RelationshipType(cdata.get("relationship", "alumni")),
                    source=SEED_SOURCE,
                ))
                new_contacts += 1
    await db.commit()

    # Ghost rescore
    await GhostService(db).rescore_all()

    total_postings = (await db.execute(select(Posting))).scalars().all()

    return {
        "companies_seeded": len(companies),
        "new_postings": new_postings,
        "new_contacts": new_contacts,
        "total_postings_in_db": len(total_postings),
        "message": "Seed complete. Reload your match feed.",
    }
