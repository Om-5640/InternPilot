"""Demo seed / simulation script.

Usage:
    uv run python scripts/seed_demo.py          # seed demo data
    uv run python scripts/seed_demo.py --reset  # delete & re-seed

Generates a realistic demo dataset to make the Ghost Shield, cohort response-
rate signal, and referral finder all visible without waiting 7+ days for real
outcome data.  All writes go through the existing services so seeded rows are
behaviourally identical to real rows.
"""
from __future__ import annotations

import asyncio
import hashlib
import random
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from sqlalchemy import delete, select  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models.artifact import Artifact  # noqa: E402
from app.models.company import Company  # noqa: E402
from app.models.contact import Contact, RelationshipType  # noqa: E402
from app.models.posting import Posting  # noqa: E402
from app.models.user import AuthProvider, User, UserRole  # noqa: E402
from app.schemas.profile import (  # noqa: E402
    EducationItem,
    ExperienceItem,
    ProfileUpdateRequest,
    ProjectItem,
)
from app.services.application_service import ApplicationService  # noqa: E402
from app.services.ghost_service import GHOST_THRESHOLD, GhostService  # noqa: E402
from app.services.profile_service import ProfileService  # noqa: E402
from app.services.tracker_service import TrackerService  # noqa: E402
from app.services.university_normalizer import canonicalize as _canonicalize_uni  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEMO_EMAIL_SUFFIX = "@demo.internpilot"
DEMO_POSTING_SOURCE = "demo_seed"
DEMO_CONTACT_SOURCE = "demo_seed"
DEMO_PASSWORD = "DemoPass123!"

_RESPONSIVE = "responsive"
_MIXED = "mixed"
_GHOST = "ghost"

NOW = datetime.now(UTC)

# days-ago and source_sightings drive age_score + repost_score per archetype
_ARCHETYPE_DAYS: dict[str, int] = {_RESPONSIVE: 10, _MIXED: 28, _GHOST: 75}
_ARCHETYPE_SIGHTINGS: dict[str, int] = {_RESPONSIVE: 1, _MIXED: 2, _GHOST: 3}

# Deterministic response probabilities
_ARCHETYPE_RESPOND_RATE: dict[str, float] = {_RESPONSIVE: 0.75, _MIXED: 0.30, _GHOST: 0.07}

# ---------------------------------------------------------------------------
# Company definitions
# ---------------------------------------------------------------------------

COMPANY_DEFS: list[dict[str, Any]] = [
    # ── responsive ──────────────────────────────────────────────────────────
    {"name": "Google",    "domain": "google.com",    "industry": "Technology",          "size": "10001+",    "archetype": _RESPONSIVE},
    {"name": "Stripe",    "domain": "stripe.com",    "industry": "FinTech",             "size": "1001-5000", "archetype": _RESPONSIVE},
    {"name": "Figma",     "domain": "figma.com",     "industry": "Design Tools",        "size": "501-1000",  "archetype": _RESPONSIVE},
    {"name": "Notion",    "domain": "notion.so",     "industry": "Productivity",        "size": "201-500",   "archetype": _RESPONSIVE},
    # ── mixed ───────────────────────────────────────────────────────────────
    {"name": "Microsoft", "domain": "microsoft.com", "industry": "Technology",          "size": "10001+",    "archetype": _MIXED},
    {"name": "Amazon",    "domain": "amazon.com",    "industry": "E-Commerce / Cloud",  "size": "10001+",    "archetype": _MIXED},
    {"name": "Lyft",      "domain": "lyft.com",      "industry": "Rideshare",           "size": "1001-5000", "archetype": _MIXED},
    # ── ghost-prone ─────────────────────────────────────────────────────────
    {"name": "PipelineTech",  "domain": "pipelinetech.io",  "industry": "SaaS",    "size": "11-50",   "archetype": _GHOST},
    {"name": "TalentPool Inc","domain": "talentpool.co",    "industry": "HR Tech", "size": "51-200",  "archetype": _GHOST},
    {"name": "InnovateCo",    "domain": "innovateco.tech",  "industry": "AdTech",  "size": "11-50",   "archetype": _GHOST},
]

# ---------------------------------------------------------------------------
# Posting templates (2 per company)
# ---------------------------------------------------------------------------

POSTING_TEMPLATES: dict[str, list[dict[str, Any]]] = {
    "Google": [
        {
            "title": "Software Engineering Intern – Core Infrastructure",
            "description": (
                "Join the team building the backbone of Google's cloud infrastructure. "
                "Work with distributed systems, contribute to reliability engineering, "
                "and improve performance at scale using Python, Go, and C++. "
                "You will own end-to-end features, write production code, and "
                "collaborate with senior engineers across SRE and infrastructure teams."
            ),
            "requirements": ["Python", "Go", "Distributed Systems", "Linux", "Data Structures", "Algorithms"],
            "location": "Mountain View, CA", "work_mode": "hybrid", "stipend": 9200,
        },
        {
            "title": "Machine Learning Intern – Ads Ranking",
            "description": (
                "Develop and deploy machine learning models that power Google Ads ranking. "
                "Use PyTorch and TensorFlow to design experiments, analyze large-scale "
                "datasets with SQL and BigQuery, and push improvements to production "
                "that impact billions of users globally."
            ),
            "requirements": ["Python", "PyTorch", "TensorFlow", "SQL", "Machine Learning", "Statistics"],
            "location": "New York, NY", "work_mode": "hybrid", "stipend": 9500,
        },
    ],
    "Stripe": [
        {
            "title": "Backend Engineer Intern – Payments Platform",
            "description": (
                "Help Stripe scale the global payments network. Build APIs in Go, "
                "improve reliability of payment flows, and work on fraud-detection "
                "pipelines backed by PostgreSQL and Redis. You will write production "
                "code from day one and participate in design reviews."
            ),
            "requirements": ["Go", "Python", "REST APIs", "PostgreSQL", "Distributed Systems"],
            "location": "San Francisco, CA", "work_mode": "hybrid", "stipend": 9000,
        },
        {
            "title": "Data Engineering Intern – Revenue Analytics",
            "description": (
                "Build the data pipelines that power Stripe's financial analytics. "
                "Use Python, Spark, and dbt to transform raw event streams into "
                "actionable insights. Work closely with finance and product analytics teams."
            ),
            "requirements": ["Python", "SQL", "Spark", "dbt", "Airflow", "Data Engineering"],
            "location": "Remote", "work_mode": "remote", "stipend": 8500,
        },
    ],
    "Figma": [
        {
            "title": "Frontend Engineer Intern",
            "description": (
                "Contribute to Figma's web editor used by millions of designers. "
                "Work in TypeScript and React to ship new UI features, improve canvas "
                "performance, and write WebGL rendering code. Strong CS fundamentals required."
            ),
            "requirements": ["TypeScript", "React", "JavaScript", "CSS", "WebGL", "Performance Optimization"],
            "location": "San Francisco, CA", "work_mode": "onsite", "stipend": 8800,
        },
        {
            "title": "Full-Stack Intern – Plugin Ecosystem",
            "description": (
                "Build infrastructure and tooling for Figma's plugin ecosystem. "
                "Own features from design to deployment using TypeScript, Node.js, and "
                "PostgreSQL. Collaborate with DevRel to improve the developer experience."
            ),
            "requirements": ["TypeScript", "Node.js", "React", "PostgreSQL", "REST APIs"],
            "location": "San Francisco, CA", "work_mode": "onsite", "stipend": 8500,
        },
    ],
    "Notion": [
        {
            "title": "Backend Engineer Intern – Real-Time Collaboration",
            "description": (
                "Work on the real-time sync engine powering collaborative editing in Notion. "
                "Use TypeScript, Rust, and CRDTs to build features used by 40M+ users. "
                "Ship production code and participate in on-call rotations."
            ),
            "requirements": ["TypeScript", "Rust", "PostgreSQL", "Redis", "Distributed Systems"],
            "location": "San Francisco, CA", "work_mode": "hybrid", "stipend": 8400,
        },
        {
            "title": "Data Science Intern – Growth Analytics",
            "description": (
                "Use SQL and Python to analyze user behavior, run A/B experiments, "
                "and build dashboards that inform product decisions. Partner with the "
                "growth and product teams to identify levers for retention and activation."
            ),
            "requirements": ["Python", "SQL", "Statistics", "A/B Testing", "pandas", "Tableau"],
            "location": "Remote", "work_mode": "remote", "stipend": 7800,
        },
    ],
    "Microsoft": [
        {
            "title": "Software Engineering Intern – Azure DevOps",
            "description": (
                "Join the Azure DevOps team building developer tools used by millions of teams. "
                "Work with C#, TypeScript, and Azure services to ship features that improve "
                "CI/CD pipelines. Write production-quality code and own features end-to-end."
            ),
            "requirements": ["C#", "TypeScript", "Azure", "REST APIs", "Git", "Unit Testing"],
            "location": "Redmond, WA", "work_mode": "hybrid", "stipend": 8200,
        },
        {
            "title": "Data Science Intern – Microsoft 365",
            "description": (
                "Apply machine learning and statistical modeling to improve Microsoft 365. "
                "Use Python and Azure ML to build models that personalize content "
                "recommendations and detect usage anomalies across the product suite."
            ),
            "requirements": ["Python", "Machine Learning", "SQL", "Azure", "scikit-learn", "Statistics"],
            "location": "Redmond, WA", "work_mode": "hybrid", "stipend": 8000,
        },
    ],
    "Amazon": [
        {
            "title": "Software Development Engineer Intern – AWS S3",
            "description": (
                "Build and scale the world's most used object-storage system. "
                "Work in Java and Python on distributed systems, contribute to S3's "
                "reliability roadmap, and own a feature from design doc to deployment."
            ),
            "requirements": ["Java", "Python", "Distributed Systems", "AWS", "Data Structures", "Algorithms"],
            "location": "Seattle, WA", "work_mode": "onsite", "stipend": 8700,
        },
        {
            "title": "Applied Scientist Intern – Alexa AI",
            "description": (
                "Research and implement NLP models to improve Alexa's natural language "
                "understanding. Use PyTorch and TensorFlow to train dialogue models, "
                "run experiments at scale, and publish results to internal research forums."
            ),
            "requirements": ["Python", "PyTorch", "NLP", "Machine Learning", "Statistics", "Research"],
            "location": "Seattle, WA", "work_mode": "onsite", "stipend": 9100,
        },
    ],
    "Lyft": [
        {
            "title": "Backend Engineer Intern – Marketplace",
            "description": (
                "Work on Lyft's marketplace platform that matches riders and drivers in "
                "real time. Build microservices in Python and Go, optimize dispatching "
                "algorithms backed by Kafka and Redis, and improve system reliability."
            ),
            "requirements": ["Python", "Go", "Kafka", "PostgreSQL", "Redis", "Microservices"],
            "location": "San Francisco, CA", "work_mode": "hybrid", "stipend": 7800,
        },
        {
            "title": "Data Analyst Intern – Driver Experience",
            "description": (
                "Analyze driver metrics and satisfaction data to identify friction points. "
                "Use SQL, Python, and Tableau to build executive dashboards and present "
                "data-driven findings to the product and operations teams."
            ),
            "requirements": ["SQL", "Python", "pandas", "Tableau", "Statistics", "A/B Testing"],
            "location": "San Francisco, CA", "work_mode": "hybrid", "stipend": 7200,
        },
    ],
    # ── ghost-prone: vague JDs, pipeline phrases, no requirements ────────────
    "PipelineTech": [
        {
            "title": "Software Engineer – General Applications",
            "description": (
                "We are always looking for talented engineers who want to join our growing team! "
                "We build the future of enterprise software and are looking for passionate "
                "individuals at all levels. Great opportunity for growth and development."
            ),
            "requirements": [],
            "location": "Remote", "work_mode": "remote", "stipend": None,
        },
        {
            "title": "Full Stack Developer – Expressions of Interest",
            "description": (
                "Building a pipeline of candidates for future opportunities. "
                "Expressions of interest welcome from developers at all experience levels. "
                "Join our talent community and be considered for upcoming engineering roles "
                "as we continue to grow our product teams."
            ),
            "requirements": [],
            "location": "Remote", "work_mode": "remote", "stipend": None,
        },
        # DECEPTIVE: recent, specific JD, strong skill match — Ghost Shield won't flag it.
        # Company has 0-17% cohort response rate -> Module 5 will demote it in rankings.
        {
            "title": "Machine Learning Engineer Intern",
            "description": (
                "Build and deploy ML models powering our enterprise analytics platform. "
                "Use Python and PyTorch to develop NLP pipelines, design controlled A/B "
                "experiments, and ship models to production on GCP. Work with senior engineers "
                "on feature engineering, model evaluation, and latency optimization at scale. "
                "Strong SQL and statistics fundamentals required."
            ),
            "requirements": ["Python", "PyTorch", "Machine Learning", "SQL", "GCP", "Statistics"],
            "location": "Remote", "work_mode": "remote", "stipend": 7000,
            "days_override": 8,    # recent -> age_score = 0.0
            "sightings_override": 1,  # single board -> repost_score = 0.0
        },
    ],
    "TalentPool Inc": [
        {
            "title": "Engineering Intern – Open Applications",
            "description": (
                "We are always on the lookout for bright, curious engineers. "
                "Building a pipeline of candidates for our internship program. "
                "Apply now to be considered for future roles — we review resumes on a rolling basis "
                "and will reach out when a matching position opens."
            ),
            "requirements": [],
            "location": "New York, NY", "work_mode": "any", "stipend": None,
        },
        {
            "title": "Product Engineer – Talent Community",
            "description": (
                "Join our talent community. Future opportunities will be shared with our "
                "pipeline of candidates on a rolling basis. Expressions of interest are welcome "
                "from engineers at all levels — we are not currently hiring but will notify you."
            ),
            "requirements": [],
            "location": "New York, NY", "work_mode": "any", "stipend": None,
        },
        # DECEPTIVE: recent, specific JD, strong skill match — Ghost Shield won't flag it.
        # Company has 0% cohort response rate -> Module 5 will demote it in rankings.
        {
            "title": "Backend Engineer Intern – Platform",
            "description": (
                "Join our platform team to build microservices in Go and Python. "
                "Design and maintain REST APIs backed by PostgreSQL and Redis, improve "
                "reliability of our data ingestion pipelines, and contribute to our "
                "Kubernetes-based infrastructure. Ship production code in your first week. "
                "Ideal for candidates with distributed systems experience."
            ),
            "requirements": ["Go", "Python", "PostgreSQL", "Redis", "REST APIs", "Kubernetes"],
            "location": "Remote", "work_mode": "remote", "stipend": 6500,
            "days_override": 6,    # recent -> age_score = 0.0
            "sightings_override": 1,  # single board -> repost_score = 0.0
        },
    ],
    "InnovateCo": [
        {
            "title": "Software Engineer Intern – Open Application",
            "description": (
                "Exciting opportunity to work at a fast-growing startup. "
                "We are always looking for passionate self-starters eager to learn and grow. "
                "Great culture, unlimited PTO, and remote-friendly environment. "
                "We review all applications and will be in touch if there is a match."
            ),
            "requirements": [],
            "location": "Remote", "work_mode": "remote", "stipend": 3000,
        },
        {
            "title": "Data Analyst – Growth Pipeline",
            "description": (
                "Building a pipeline of candidates for future opportunities in analytics and growth. "
                "Expressions of interest welcome from students passionate about data. "
                "We are not currently hiring but stay in our talent community for updates."
            ),
            "requirements": [],
            "location": "Remote", "work_mode": "remote", "stipend": None,
        },
    ],
}

# ---------------------------------------------------------------------------
# Demo users (5 varied personas)
# ---------------------------------------------------------------------------

DEMO_USERS: list[dict[str, Any]] = [
    {
        "name": "Alex Chen (Demo)",
        "email": "alex.ml" + DEMO_EMAIL_SUFFIX,
        "persona": "ML/AI",
        "university": "MIT",
        "grad_year": 2026,
        "research_interests": ["machine learning", "natural language processing", "computer vision"],
        "headline": "ML Engineering Student | PyTorch · Transformers · Python",
        "skills": ["Python", "PyTorch", "TensorFlow", "scikit-learn", "pandas", "numpy", "SQL", "Machine Learning", "Statistics", "CUDA"],
        "experience": [{"title": "ML Research Assistant", "org": "MIT CSAIL", "start": "2024-01", "end": "2025-01", "description": "Trained transformer models for NLP; reduced inference latency 30% via quantization using PyTorch."}],
        "projects": [{"name": "SentimentScope", "description": "Fine-tuned BERT for multi-label sentiment analysis; deployed as FastAPI service on GCP.", "tech": ["Python", "PyTorch", "FastAPI", "GCP", "Docker"]}],
        "education": [{"degree": "BS Computer Science", "institution": "MIT", "year": 2026}],
    },
    {
        "name": "Sam Patel (Demo)",
        "email": "sam.web" + DEMO_EMAIL_SUFFIX,
        "persona": "Web / Full-Stack",
        "university": "University of Toronto",
        "grad_year": 2026,
        "research_interests": [],
        "headline": "Full-Stack Engineer | React · TypeScript · Node.js",
        "skills": ["TypeScript", "JavaScript", "React", "Node.js", "PostgreSQL", "REST APIs", "CSS", "HTML", "Git", "Docker"],
        "experience": [{"title": "Software Engineering Intern", "org": "Shopify", "start": "2024-06", "end": "2024-09", "description": "Built React dashboard for real-time analytics; shipped REST APIs in Node.js serving 50k daily active users."}],
        "projects": [{"name": "TaskFlow", "description": "Full-stack project management app with real-time collaboration using React, Node.js, and PostgreSQL.", "tech": ["React", "TypeScript", "Node.js", "PostgreSQL", "WebSockets"]}],
        "education": [{"degree": "BEng Software Engineering", "institution": "University of Toronto", "year": 2026}],
    },
    {
        "name": "Jordan Kim (Demo)",
        "email": "jordan.data" + DEMO_EMAIL_SUFFIX,
        "persona": "Data / Analytics",
        "university": "UC Berkeley",
        "grad_year": 2026,
        "research_interests": ["data science", "causal inference", "applied statistics"],
        "headline": "Data Science Student | SQL · Python · Tableau",
        "skills": ["SQL", "Python", "pandas", "Tableau", "Statistics", "A/B Testing", "R", "dbt", "Spark", "Excel"],
        "experience": [{"title": "Data Analyst Intern", "org": "Airbnb", "start": "2024-06", "end": "2024-09", "description": "Built automated SQL pipelines in Snowflake; created Tableau executive dashboards for 200+ stakeholders."}],
        "projects": [{"name": "ChurnPredictor", "description": "Gradient boosting churn-prediction model with pandas and scikit-learn pipeline.", "tech": ["Python", "scikit-learn", "pandas", "SQL", "Tableau"]}],
        "education": [{"degree": "BS Data Science", "institution": "UC Berkeley", "year": 2026}],
    },
    {
        "name": "Casey Park (Demo)",
        "email": "casey.backend" + DEMO_EMAIL_SUFFIX,
        "persona": "Backend / Systems",
        "university": "IIT Bombay",
        "grad_year": 2025,
        "research_interests": ["distributed systems", "database internals"],
        "headline": "Backend Engineer | Go · Python · Distributed Systems",
        "skills": ["Go", "Python", "PostgreSQL", "Redis", "Kafka", "Docker", "Kubernetes", "Linux", "AWS", "Microservices"],
        "experience": [{"title": "Backend Engineering Intern", "org": "Zepto", "start": "2024-06", "end": "2024-09", "description": "Designed Kafka event-streaming pipeline in Go; processed 2M+ daily transactions with sub-50ms P99 latency."}],
        "projects": [{"name": "DistCache", "description": "Distributed key-value cache in Go with consistent hashing and Raft-based leader election.", "tech": ["Go", "Redis", "Docker", "Linux"]}],
        "education": [{"degree": "BTech Computer Science", "institution": "IIT Bombay", "year": 2025}],
    },
    {
        "name": "Riley Nguyen (Demo)",
        "email": "riley.fullstack" + DEMO_EMAIL_SUFFIX,
        "persona": "Full-Stack / Cloud",
        "university": "University of Melbourne",
        "grad_year": 2026,
        "research_interests": [],
        "headline": "Full-Stack & Cloud Student | Python · React · AWS",
        "skills": ["Python", "React", "TypeScript", "AWS", "PostgreSQL", "FastAPI", "Docker", "Terraform", "REST APIs", "GraphQL"],
        "experience": [{"title": "Software Engineering Intern", "org": "Canva", "start": "2024-03", "end": "2024-09", "description": "Developed FastAPI microservices on AWS ECS; built React dashboards for 300+ internal engineers."}],
        "projects": [{"name": "CloudNotes", "description": "Serverless note-taking app with React frontend and FastAPI backend on AWS Lambda + DynamoDB.", "tech": ["Python", "React", "FastAPI", "AWS", "TypeScript", "Docker"]}],
        "education": [{"degree": "BS Computer Science", "institution": "University of Melbourne", "year": 2026}],
    },
]

# ---------------------------------------------------------------------------
# Alumni contacts (seeded into contacts_alumni — global reference data)
# ---------------------------------------------------------------------------

ALUMNI_CONTACTS: dict[str, list[dict[str, Any]]] = {
    "Google":    [
        {"name": "Maya Rodriguez",  "role": "SWE Intern -> FTE",      "grad_year": 2024, "university": "MIT",                    "relationship": "alumni"},
        {"name": "James Liu",       "role": "Software Engineer",       "grad_year": 2023, "university": "UC Berkeley",            "relationship": "alumni"},
        {"name": "Priya Singh",     "role": "ML Engineer",             "grad_year": 2022, "university": "IIT Bombay",             "relationship": "alumni"},
        {"name": "Daniel Okonkwo", "role": "SWE II",                  "grad_year": 2024, "university": "University of Lagos",    "relationship": "second_degree"},
    ],
    "Stripe":    [
        {"name": "Sophie Tan",     "role": "Backend Engineer",         "grad_year": 2024, "university": "University of Toronto",  "relationship": "alumni"},
        {"name": "Ethan Brooks",   "role": "Infrastructure Engineer",  "grad_year": 2023, "university": "Carnegie Mellon",        "relationship": "alumni"},
        {"name": "Nina Koval",     "role": "Data Engineer",            "grad_year": 2023, "university": "ETH Zurich",             "relationship": "alumni"},
    ],
    "Figma":     [
        {"name": "Leo Martinez",   "role": "Frontend Engineer",        "grad_year": 2024, "university": "UC Berkeley",            "relationship": "alumni"},
        {"name": "Grace Hwang",    "role": "Design Engineer",          "grad_year": 2023, "university": "University of Melbourne", "relationship": "alumni"},
        {"name": "Oliver Chen",    "role": "Full-Stack Engineer",      "grad_year": 2023, "university": "MIT",                    "relationship": "second_degree"},
    ],
    "Notion":    [
        {"name": "Avery Johnson",  "role": "Backend Engineer",         "grad_year": 2023, "university": "Stanford",               "relationship": "alumni"},
        {"name": "Zoe Kim",        "role": "Data Scientist",           "grad_year": 2024, "university": "University of Toronto",  "relationship": "alumni"},
    ],
    "Microsoft": [
        {"name": "Marcus Wright",  "role": "SWE",                     "grad_year": 2022, "university": "Georgia Tech",           "relationship": "alumni"},
        {"name": "Isabella Flores","role": "PM",                       "grad_year": 2023, "university": "UT Austin",              "relationship": "second_degree"},
        {"name": "Ryan O'Brien",   "role": "Cloud Engineer",           "grad_year": 2023, "university": "University of Waterloo", "relationship": "alumni"},
    ],
    "Amazon":    [
        {"name": "Natalie Xu",     "role": "SDE II",                  "grad_year": 2022, "university": "University of Washington", "relationship": "alumni"},
        {"name": "Kevin Park",     "role": "Applied Scientist",        "grad_year": 2023, "university": "IIT Delhi",              "relationship": "alumni"},
    ],
    "Lyft":      [
        {"name": "Aria Patel",     "role": "Backend Engineer",         "grad_year": 2023, "university": "IIT Bombay",             "relationship": "alumni"},
        {"name": "Dylan Torres",   "role": "Data Analyst",             "grad_year": 2024, "university": "UC San Diego",           "relationship": "second_degree"},
    ],
    "PipelineTech":   [],
    "TalentPool Inc": [],
    "InnovateCo":     [],
}


# ---------------------------------------------------------------------------
# Application assignment: 12 apps per user
# Base: 1 app to each of 10 companies (all 4 responsive + 3 mixed + 3 ghost)
# Extras: 2 more per user from the second posting of rotating companies,
# ensuring some companies cross MIN_COHORT_APPS=5 with room to spare.
# ---------------------------------------------------------------------------

_EXTRAS: list[list[tuple[str, int]]] = [
    [("Google", 1), ("Stripe", 1)],
    [("Figma", 1), ("Microsoft", 1)],
    [("Notion", 1), ("Amazon", 1)],
    [("Lyft", 1), ("PipelineTech", 1)],
    [("TalentPool Inc", 1), ("InnovateCo", 1)],
]

# Titles of deceptive postings used in summary callout
DECEPTIVE_TITLES: frozenset[str] = frozenset({
    "Machine Learning Engineer Intern",
    "Backend Engineer Intern – Platform",
})


def _assignment(user_idx: int) -> list[tuple[str, int]]:
    base: list[tuple[str, int]] = [
        ("Google", 0), ("Stripe", 0), ("Figma", 0), ("Notion", 0),
        ("Microsoft", 0), ("Amazon", 0), ("Lyft", 0),
        ("PipelineTech", 0), ("TalentPool Inc", 0), ("InnovateCo", 0),
        # deceptive postings — look clean but company never responds
        ("PipelineTech", 2), ("TalentPool Inc", 2),
    ]
    return base + _EXTRAS[user_idx % len(_EXTRAS)]


# ---------------------------------------------------------------------------
# Outcome generator (deterministic via seeded rng)
# ---------------------------------------------------------------------------

def _pick_outcome(archetype: str, rng: random.Random) -> tuple[str, bool, float | None]:
    rate = _ARCHETYPE_RESPOND_RATE[archetype]
    if rng.random() < rate:
        if archetype == _RESPONSIVE:
            r = rng.random()
            if r < 0.50:
                return "responded", True, rng.uniform(24, 72)
            elif r < 0.82:
                return "interview", True, rng.uniform(48, 120)
            else:
                return "offer", True, rng.uniform(72, 168)
        elif archetype == _MIXED:
            if rng.random() < 0.75:
                return "responded", True, rng.uniform(72, 200)
            else:
                return "interview", True, rng.uniform(120, 300)
        else:
            return "responded", True, rng.uniform(200, 500)
    return "no_response", False, None


def _artifact_content(udef: dict[str, Any], title: str, company: str) -> str:
    skills = ", ".join(udef["skills"][:4])
    short_name = udef["name"].replace(" (Demo)", "")
    return (
        f"Dear {company} Recruiting Team,\n\n"
        f"I am a {udef['persona']} student at Drexel University applying for the "
        f"{title} role. My background in {skills} aligns well with your team's focus. "
        f"I would be excited to contribute and grow at {company}.\n\n"
        f"Best regards,\n{short_name}"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


async def _resolve_or_create_company(session: AsyncSession, cdef: dict[str, Any]) -> Company:
    norm = _normalize(cdef["name"])
    row = (await session.execute(select(Company).where(Company.normalized_name == norm))).scalar_one_or_none()
    if row is not None:
        return row
    c = Company(
        name=cdef["name"],
        normalized_name=norm,
        domain=cdef.get("domain"),
        industry=cdef.get("industry"),
        size=cdef.get("size"),
        ghost_history_score=0.0,
        responsiveness_score=1.0,
        cohort_applied_count=0,
    )
    session.add(c)
    await session.flush()
    return c


async def _get_or_create_posting(
    session: AsyncSession,
    company: Company,
    tmpl: dict[str, Any],
    archetype: str,
    idx: int,
) -> Posting:
    domain = company.domain or (_normalize(company.name) + ".io")
    slug = _normalize(company.name) + f"-{idx}"
    source_url = f"https://{domain}/careers/demo-{slug}"

    existing = (await session.execute(select(Posting).where(Posting.source_url == source_url))).scalar_one_or_none()
    if existing is not None:
        return existing

    # Deceptive postings override age and sightings to look like fresh, clean listings.
    days_ago = tmpl.get("days_override", _ARCHETYPE_DAYS[archetype])
    sightings = tmpl.get("sightings_override", _ARCHETYPE_SIGHTINGS[archetype])
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
        source=DEMO_POSTING_SOURCE,
        source_url=source_url,
        posted_at=posted_dt,
        last_seen_at=posted_dt,
        status="active",
        ghost_score=0.0,
        is_ghost=False,
        dedup_key=dedup_key,
        source_sightings=sightings,
    )
    session.add(p)
    await session.flush()
    return p


async def _ghost_snapshot(session: AsyncSession) -> tuple[int, int, dict[str, tuple[float, bool]]]:
    """Return (total, flagged, {title_50: (score, is_ghost)}).

    Uses populate_existing so we always read DB-committed values without
    expiring other objects (like company_map entries) in the identity map.
    """
    postings = (
        await session.execute(
            select(Posting).execution_options(populate_existing=True)
        )
    ).scalars().all()
    flagged = sum(1 for p in postings if p.is_ghost)
    details = {p.title[:50]: (round(p.ghost_score, 3), p.is_ghost) for p in postings}
    return len(postings), flagged, details


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------

async def _reset_demo(session: AsyncSession) -> None:
    await session.execute(delete(Contact).where(Contact.source == DEMO_CONTACT_SOURCE))
    await session.execute(delete(User).where(User.email.like(f"%{DEMO_EMAIL_SUFFIX}")))
    await session.execute(delete(Posting).where(Posting.source == DEMO_POSTING_SOURCE))
    await session.commit()
    print("  Cleared demo users, postings, contacts (cascade: apps / outcomes / artifacts / referrals).")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    do_reset = "--reset" in sys.argv

    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    rng = random.Random(42)

    async with factory() as db:

        # ── 0. reset ────────────────────────────────────────────────────────
        if do_reset:
            print("Resetting demo data...")
            await _reset_demo(db)

        # ── 1. companies ────────────────────────────────────────────────────
        print("Seeding companies...")
        company_map: dict[str, Company] = {}
        for cdef in COMPANY_DEFS:
            company_map[cdef["name"]] = await _resolve_or_create_company(db, cdef)
        await db.commit()
        print(f"  {len(company_map)} companies ready")

        # ── 2. postings ─────────────────────────────────────────────────────
        print("Seeding postings...")
        posting_map: dict[tuple[str, int], Posting] = {}
        for cname, templates in POSTING_TEMPLATES.items():
            co = company_map[cname]
            arch = next(cd["archetype"] for cd in COMPANY_DEFS if cd["name"] == cname)
            for i, tmpl in enumerate(templates):
                posting_map[(cname, i)] = await _get_or_create_posting(db, co, tmpl, arch, i)
        await db.commit()
        print(f"  {len(posting_map)} postings ready")

        # ── 3. alumni contacts ──────────────────────────────────────────────
        print("Seeding alumni contacts...")
        contact_n = 0
        for cname, contacts in ALUMNI_CONTACTS.items():
            co = company_map[cname]
            for cdata in contacts:
                uni_raw = cdata.get("university")
                db.add(Contact(
                    name=cdata["name"],
                    company_id=co.id,
                    role=cdata.get("role"),
                    grad_year=cdata.get("grad_year"),
                    university=uni_raw,
                    university_canonical=_canonicalize_uni(uni_raw) or None if uni_raw else None,
                    linkedin=cdata.get("linkedin"),
                    relationship=RelationshipType(cdata.get("relationship", "alumni")),
                    source=DEMO_CONTACT_SOURCE,
                ))
                contact_n += 1
        await db.commit()
        print(f"  {contact_n} contacts")

        # ── 4. baseline ghost rescore (pre-cohort) ──────────────────────────
        print("Running baseline ghost rescore (pre-cohort)...")
        ghost_svc = GhostService(db)
        await ghost_svc.rescore_all()
        total_b, flagged_b, snap_before = await _ghost_snapshot(db)
        print(f"  BEFORE cohort signal: {flagged_b}/{total_b} postings flagged")

        # ── 5. demo users + profiles + applications + outcomes ───────────────
        print("\nSeeding users, profiles, applications, outcomes...")
        n_users = n_apps = n_outcomes = 0

        for u_idx, udef in enumerate(DEMO_USERS):
            # skip if user already exists
            existing_u = (await db.execute(select(User).where(User.email == udef["email"]))).scalar_one_or_none()
            if existing_u is not None:
                print(f"  SKIP {udef['email']} (already exists)")
                continue

            user = User(
                name=udef["name"],
                email=udef["email"],
                password_hash=hash_password(DEMO_PASSWORD),
                role=UserRole.student,
                auth_provider=AuthProvider.password,
                consent={"gmail": False, "github": False, "alumni_data": True},
            )
            db.add(user)
            await db.flush()
            n_users += 1

            # profile with embedding (ProfileService._save computes strength + vector)
            profile_svc = ProfileService(db, user.id)
            await profile_svc.update_profile(ProfileUpdateRequest(
                headline=udef["headline"],
                university=udef.get("university"),
                grad_year=udef.get("grad_year"),
                research_interests=udef.get("research_interests", []),
                skills=udef["skills"],
                experience=[ExperienceItem(**e) for e in udef["experience"]],
                projects=[ProjectItem(**p) for p in udef["projects"]],
                education=[EducationItem(**e) for e in udef["education"]],
            ))

            app_svc = ApplicationService(db, user.id)
            tracker_svc = TrackerService(db, user.id)

            for cname, p_idx in _assignment(u_idx):
                posting = posting_map[(cname, p_idx)]
                co = company_map[cname]
                arch = next(cd["archetype"] for cd in COMPANY_DEFS if cd["name"] == cname)

                # artifact (no LLM — placeholder text)
                artifact = Artifact(
                    user_id=user.id,
                    application_id=None,
                    type="cover_letter",
                    content=_artifact_content(udef, posting.title, co.name),
                    ats_score=rng.randint(55, 92),
                    missing_keywords=[],
                    grounding_score=round(rng.uniform(0.70, 1.0), 2),
                    version=1,
                )
                db.add(artifact)
                await db.flush()

                # create_application snapshots predicted_ghost + predicted_response_prob
                app_schema = await app_svc.create_application(posting.id, "web", artifact.id)
                n_apps += 1

                # record_outcome fires CohortService.recompute_company_response internally
                otype, responded, hours = _pick_outcome(arch, rng)
                await tracker_svc.record_outcome(
                    application_id=app_schema.id,
                    outcome_type=otype,
                    responded=responded,
                    time_to_response_hours=hours,
                    source="demo_seed",
                )
                n_outcomes += 1

            print(f"  + {udef['name']}: {len(_assignment(u_idx))} apps + outcomes")

        # ── 6. final ghost rescore (with cohort signal) ─────────────────────
        print("\nRunning final ghost rescore (with cohort signal)...")
        await ghost_svc.rescore_all()
        total_a, flagged_a, snap_after = await _ghost_snapshot(db)
        print(f"  AFTER  cohort signal: {flagged_a}/{total_a} postings flagged")

        # ── 7. collect company response stats ───────────────────────────────
        company_stats: list[dict[str, Any]] = []
        for cdef in COMPANY_DEFS:
            co = company_map[cdef["name"]]
            if co.cohort_applied_count >= 5:
                company_stats.append({
                    "name": cdef["name"],
                    "archetype": cdef["archetype"],
                    "applied": co.cohort_applied_count,
                    "responsiveness": round(co.responsiveness_score, 3),
                    "ghost_history": round(co.ghost_history_score, 3),
                })

    await engine.dispose()

    # ── 8. print summary ─────────────────────────────────────────────────────
    width = 62
    print("\n" + "=" * width)
    print("DEMO SEED SUMMARY")
    print("=" * width)
    print(f"Demo users created : {n_users}")
    print(f"Applications       : {n_apps}")
    print(f"Outcomes recorded  : {n_outcomes}")
    print(f"Alumni contacts    : {contact_n}")

    print("\nPER-COMPANY RESPONSE RATES (>= MIN_COHORT_APPS=5):")
    print(f"  {'Company':<18} {'Arch':<12} {'Applied':>7} {'Resp%':>6} {'GhostHist':>9}")
    print(f"  {'-'*18} {'-'*12} {'-'*7} {'-'*6} {'-'*9}")
    for s in company_stats:
        resp_pct = f"{s['responsiveness']*100:.0f}%"
        print(f"  {s['name']:<18} {s['archetype']:<12} {s['applied']:>7} {resp_pct:>6} {s['ghost_history']:>9.3f}")

    print(f"\nGHOST DISTRIBUTION (threshold = {GHOST_THRESHOLD})")
    print(f"  BEFORE cohort signal: {flagged_b}/{total_b} postings flagged as ghost")
    print(f"  AFTER  cohort signal: {flagged_a}/{total_a} postings flagged as ghost")

    all_titles = sorted(set(snap_before) | set(snap_after))
    print(f"\n  {'Posting (50 chars)':<51} {'BEFORE':>6}  {'AFTER':>6}  {'Delta':>6}  Flag")
    print(f"  {'-'*51} {'-'*6}  {'-'*6}  {'-'*6}  ----")
    for t in all_titles:
        b_score, _ = snap_before.get(t, (0.0, False))
        a_score, a_flag = snap_after.get(t, (0.0, False))
        delta = a_score - b_score
        flag_str = "[GHOST]" if a_flag else ""
        print(f"  {t:<51} {b_score:>6.3f}  {a_score:>6.3f}  {delta:>+6.3f}  {flag_str}")

    print()
    reclassified = flagged_a - flagged_b
    if reclassified == 0:
        print(f"No reclassifications — GHOST_THRESHOLD={GHOST_THRESHOLD} is stable.")
    elif reclassified > 0:
        print(f"{reclassified} posting(s) newly flagged after cohort signal raised ghost scores.")
    else:
        print(f"{abs(reclassified)} posting(s) cleared after cohort signal improved responsiveness.")

    # Threshold recommendation
    max_clean = max((a for t, (a, f) in snap_after.items() if not f), default=0.0)
    min_ghost = min((a for t, (a, f) in snap_after.items() if f), default=1.0)
    margin = min_ghost - max_clean
    if margin > 0.15:
        rec = f"Good headroom ({margin:.3f} gap). GHOST_THRESHOLD={GHOST_THRESHOLD} is appropriate."
    else:
        midpoint = round((max_clean + min_ghost) / 2, 2)
        if midpoint == GHOST_THRESHOLD:
            rec = (
                f"Narrow margin ({margin:.3f}) but threshold is already at the midpoint "
                f"({GHOST_THRESHOLD}). No adjustment needed."
            )
        else:
            rec = f"Narrow margin ({margin:.3f}). Consider tuning GHOST_THRESHOLD to {midpoint}."
    print(f"\nThreshold assessment: {rec}")

    # ── Deceptive posting callout ───────────────────────────────────────────
    print(f"\n{'='*width}")
    print("DECEPTIVE POSTINGS — what the Ghost Shield misses (Module 5's territory)")
    print(f"{'='*width}")
    print("These postings look completely clean: recent, specific JD, strong skill match.")
    print("Ghost Shield score is well below 0.38 — they will NOT be flagged.")
    print("But their company's cohort response rate is 0% -> Module 5 demotes them in rankings.")
    print()
    print(f"  {'Posting':<40} {'Company':<16} {'GhostScore':>10}  {'Co.Resp%':>8}  Note")
    print(f"  {'-'*40} {'-'*16} {'-'*10}  {'-'*8}  ----")
    for cdef in COMPANY_DEFS:
        if cdef["archetype"] != _GHOST:
            continue
        co = company_map[cdef["name"]]
        resp_pct = f"{co.responsiveness_score*100:.0f}%"
        for title in DECEPTIVE_TITLES:
            key = title[:50]
            if key not in snap_after:
                continue
            a_score, a_flag = snap_after[key]
            # Only print if this posting belongs to this company (check by title prefix match)
            templates = POSTING_TEMPLATES.get(cdef["name"], [])
            if not any(t["title"] == title for t in templates):
                continue
            flag_note = "[GHOST]" if a_flag else "not flagged — Shield blind spot"
            print(f"  {title:<40} {cdef['name']:<16} {a_score:>10.3f}  {resp_pct:>8}  {flag_note}")
    print()
    print('Demo script: "This role matches you 91% — ranked #22 because 0/5 batchmates heard back."')
    print(f"{'='*width}")


if __name__ == "__main__":
    asyncio.run(main())
