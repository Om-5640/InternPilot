# InternPilot

**Stop applying into the void.**

[![Tests](https://img.shields.io/badge/tests-316%2F316%20passing-22c55e?style=flat-square)](#running-the-test-suite)
[![mypy](https://img.shields.io/badge/mypy-strict-3178c6?style=flat-square)](https://mypy.readthedocs.io/)
[![ruff](https://img.shields.io/badge/ruff-clean-d7ff64?style=flat-square&labelColor=261230)](https://docs.astral.sh/ruff/)
[![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-17-336791?style=flat-square&logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![pgvector](https://img.shields.io/badge/pgvector-0.8-336791?style=flat-square)](https://github.com/pgvector/pgvector)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0%20async-D71F00?style=flat-square)](https://www.sqlalchemy.org/)
[![Pydantic](https://img.shields.io/badge/Pydantic-v2-E92063?style=flat-square&logo=pydantic&logoColor=white)](https://docs.pydantic.dev/)
[![Docker](https://img.shields.io/badge/Docker-required-2496ED?style=flat-square&logo=docker&logoColor=white)](https://www.docker.com/)
[![React](https://img.shields.io/badge/React-TanStack%20Start-61DAFB?style=flat-square&logo=react&logoColor=black)](https://tanstack.com/start)
[![Vite](https://img.shields.io/badge/Vite-7-646CFF?style=flat-square&logo=vite&logoColor=white)](https://vitejs.dev/)
[![License](https://img.shields.io/badge/license-MIT-green?style=flat-square)](LICENSE)

---

## TL;DR

Most intern applicants fire résumés into a void of ghost jobs, vague listings, and zero signal. InternPilot is a full-stack AI internship-search platform that treats job hunting as a prediction problem. It scores every posting for ghost probability before it reaches the feed, estimates how likely any given company is to respond using real cross-user outcome data, and generates application materials anchored strictly to what your profile can truthfully claim. A self-grading evaluation loop measures its own prediction accuracy against real outcomes and reports an honest learning curve as the cohort grows.

This is not a chatbot wrapper. The core intelligence is a multi-signal ranking engine with a feedback loop.

---

## Why this isn't a wrapper

Three things the platform does that a prompt alone cannot.

### Ghost-Job Shield

A five-signal weighted model scores every posting for ghost probability before it surfaces in any feed — no LLM call, no guessing:

| Signal | Weight | Logic |
|--------|--------|-------|
| Posting age | 0.30 | Step function: 0–14 d → 0, 15–29 d → 0.2, 30–59 d → 0.5, 60–89 d → 0.7, 90+ d → 1.0 |
| Cross-board repost | 0.20 | `source_sightings` integer: 1 board → 0.0, 2 boards → 0.4, 3+ boards → 0.8 |
| JD vagueness | 0.25 | Word count + requirement count + pipeline phrases − tech-term specificity bonus |
| Company ghost history | 0.15 | Rolling average ghost score across all company postings |
| Cohort non-response | 0.10 | Active only once ≥ 5 batchmates have applied to the same company |

Ghost threshold: **0.38**. The repost signal uses a per-posting `source_sightings` counter incremented at ingestion, avoiding cross-table GROUP BY joins on the hot read path.

### Cohort-Based Response Likelihood

After five or more users apply to the same company, a cross-user response rate feeds directly into the ranking signal. This catches the deceptive posting — semantic match looks great, but zero of N batchmates heard back, so it ranks low. The ranking key is:

```
expected_value = match_score × response_likelihood × (1 − ghost_score)
```

Response likelihood on the data-rich path (≥ 5 cohort applications):

```
RL = 0.55 × cohort_response_rate  +  0.35 × freshness  +  0.10 × (1 − ghost_score)
```

Cold-start (< 5 cohort applications):

```
RL = 0.65 × freshness  +  0.35 × (1 − ghost_history_score)
```

Individual application rows never cross user boundaries. Only aggregate counts — `cohort_applied_count` and `responsiveness_score` on the `companies` table — are shared. See `app/services/cohort_service.py` for the isolation guarantee.

### Self-Improving Platform IQ

The platform grades its own predictions against real outcomes using a rigorous, honest methodology.

**evaluate_now** scores every `(application, outcome)` pair against the response probability and ghost flag that were snapshotted before the outcome was known. Every pair is out-of-sample by construction.

**build_history** runs a fixed-test-set learning curve: all pairs are split 70/30 by `recorded_at` (temporal order). The 30% test set is fixed and never trained on. A `LogisticRegression` calibrator is trained on 8 growing prefixes of the 70% pool, and Brier score on the fixed test set is measured at each checkpoint. Train/test disjointness is asserted in code at every prefix — not trusted, asserted.

**Platform IQ formula** (evaluate_now):

```
IQ = 100 × (0.6 × (1 − Brier) + 0.4 × ghost_F1)
```

**Measured results on the seed dataset** (364 application-outcome pairs, 14 simulated users, 12 companies):

| Metric | Value |
|--------|-------|
| Platform IQ (full set) | **66.7** |
| Response Brier score | 0.226 |
| Response AUC | 0.769 |
| Ghost F1 | 0.507 |
| Learning curve start (n=31) | IQ 75.1, Brier 0.249 |
| Learning curve end (n=255) | IQ 80.3, Brier 0.197 |

The learning curve IQ (75–80) tracks only the calibration component on the fixed test set; the lower full-set IQ (66.7) reflects the ghost F1 drag at current data volume. Both numbers are real — no invented benchmarks.

---

## Architecture

```mermaid
flowchart TD
    subgraph Ingestion["Ingestion (5 sources)"]
        A1[Greenhouse] & A2[Ashby] & A3[Lever] & A4[RemoteOK] & A5[Remotive]
        --> B[Aggregation\nDedup + Normalize]
    end

    B --> C[(PostgreSQL\n+ pgvector\nHNSW index)]

    subgraph Profile["Career Twin"]
        P1[Resume / GitHub] --> P2[Profile + Skills]
        P2 --> P3[Local Embeddings\nall-MiniLM-L6-v2 dim=384]
    end

    C --> D{Ghost Shield\nage + repost + vague\ncompany + cohort}
    P3 --> E[Semantic Match\n0.7 x sim + 0.3 x skill]
    C --> E

    D --> F[Response Likelihood\ncohort 0.55 + fresh 0.35\n+ ghost-inv 0.10]
    E --> F
    F --> G[expected_value\n= match x RL x 1-ghost]

    G --> H[Application Assistant\nGrounded Gen + ATS\nanti-fabrication guard]
    H --> I[Tracker / Outcomes\nsaved to applied\nto responded to ghosted]

    I --> J[Cross-user Cohort\ncounts only - privacy-safe]
    J --> F

    I --> K[Self-Improving Loop\nLogReg calibrator\nfixed 70/30 split\nBrier to IQ curve]
    K --> L[Platform IQ Dashboard\nglobal learning curve]
```

Data flows from five aggregated job sources through a deduplication and normalization layer into PostgreSQL with a pgvector HNSW index. The Ghost Shield scores every posting independently — no LLM, five pure signals — before any posting can surface in the feed. A user's Career Twin (profile + local embeddings at dim=384) is compared against posting embeddings via cosine distance; the semantic score is blended 70/30 with skill overlap, then multiplied by response likelihood and a ghost penalty to produce `expected_value` — the ranking key. Application materials are generated by the LLM fallback router with a grounding check that prevents the model from claiming skills not in the profile. Outcomes (responded, rejected, ghosted) flow back through CohortService that updates company-level response rates while keeping individual rows isolated. Those rates feed back into the response likelihood model and into a calibration loop that produces the Platform IQ learning curve.

---

## Engineering decisions that matter

### Multi-LLM fallback router (Gemini → Groq → OpenRouter → DeepSeek → Ollama)

Defined in `app/llm/router.py`. A provider whose API key is absent is silently skipped; on 429, timeout, or any error, the next provider is tried automatically. In practice this means Groq's free tier handles most calls, Gemini is the quality backstop, and the system never hard-fails on a single provider outage. The same `complete(messages)` interface works identically in tests and production.

### Local sentence-transformers + pgvector HNSW

`all-MiniLM-L6-v2` (dim=384) runs in-process via `asyncio.to_thread`, so embedding calls never block the event loop and there is no external embedding API cost at any scale. Vectors are stored in pgvector and indexed with HNSW for sub-millisecond cosine-distance lookup. The model is downloaded on first call and held in memory for the process lifetime.

### Ghost-Job Shield: the repost trick

Most ghost-detection schemes require aggregating posting appearances across sources at query time. InternPilot instead increments a `source_sightings` integer on the `postings` table at ingestion time — a single column update versus a GROUP BY join on the hot read path. The signal degrades gracefully: the first sighting contributes zero ghost weight; it only activates on the second board appearance.

### Collective intelligence with per-user isolation

CohortService updates two columns on the `companies` table — `cohort_applied_count` and `responsiveness_score` — by counting applications and responded outcomes across all users. No individual user's `user_id`, application content, or outcome is ever read by another user's session. The BaseService pattern in `app/services/base.py` enforces this structurally: every service method touching user-owned rows filters on `self.user_id`.

### Two-layer ghost defense

The Ghost Shield catches postings that are obviously dead. The response likelihood model catches the deceptive posting — matches perfectly on skills and semantics, but cohort data shows the company never responds. A posting can survive the Shield (`ghost_score=0.2`) but still rank near zero because its cohort response rate is 0/20. Users see this explained in plain English in the `match_explanation` field.

### Anti-fabrication grounding guard

The Application Assistant whitelists every LLM generation against the candidate's verified profile skills, project technologies, and experience text. After generation, `_grounding_score()` computes the fraction of JD requirements claimed in the draft that are actually present in the profile. If grounding is below threshold, `_find_unsupported_claims()` names the fabricated terms, the prompt is rewritten with an explicit exclusion list, and the model regenerates — up to a configured retry limit. Only the final draft with its grounding score is stored.

### Self-improving Platform IQ: honest methodology

`app/services/evaluation_service.py` documents its honesty contract in the module docstring. Key invariant: predictions (`predicted_response_prob`, `predicted_ghost`) are snapshotted on the `applications` table at creation time — before any outcome exists. `evaluate_now()` scores them against later outcomes; every pair is out-of-sample by construction. `build_history()` asserts train/test disjointness at every prefix with a hard `assert` — not a log warning, an assertion that aborts the run if violated.

### Contract-first decoupling

`API_CONTRACT.md` is the single source of truth for every field name, type, and endpoint shape. The frontend's `api-client.ts` is the only file that talks to the backend; a single `VITE_USE_MOCKS` env flag switches between real FastAPI and in-memory fixtures. This means UI and backend can develop independently, with integration requiring only shape reconciliation.

### Deterministic university-name normalization

Alumni matching across users requires that "IIT Delhi", "Indian Institute of Technology Delhi", and "IIT-Delhi" resolve to the same institution. `app/services/university_normalizer.py` provides a 30-entry alias map plus punctuation and article normalization. Canonicalization is pure (no external calls, no LLM) and deterministic — same input, same output, always.

---

## Feature tour

**Career Twin — profile construction.** Upload a résumé (AI-parsed) or connect GitHub. Skills, experience, projects, and research interests form the profile vector that drives all ranking and generation. A `profile_strength` score (0–100) surfaces gaps.

**Discover — ranked feed.** `/matches` ranks every active posting by `expected_value`. Ghost postings are filtered by default; each match surfaces a `match_explanation` string that calls out the cohort signal when response rate is low.

**Ghost Shield — detail view.** `GET /api/postings/:id/ghost` returns the decomposed signal list, ghost score, and cohort stats. Ghost data is embedded in every `Match` and `Posting` response.

**Apply — Application Assistant.** `POST /api/applications/draft` generates a cover letter, email, or referral intro grounded to the candidate's profile, with `ats_score` (0–100) and `grounding_score` (0–1). The Job Decoder (`/applications/decode`) extracts structured requirements from any JD before drafting.

**Refer — warm-intro finder.** `GET /api/referrals/candidates?posting_id=...` surfaces alumni contacts at the target company. A referral intro artifact is drafted via the LLM router and attached to the referral record.

**Track — application tracker.** Applications move through statuses: `saved → applied → viewed → responded → interview → offer / rejected / ghosted`. Follow-up drafts are available per application. Gmail sync (with user consent) auto-detects replies and creates outcome records.

**Interview Prep.** `POST /api/interview-prep` generates questions with category, difficulty, and ideal answer outlines; weak spots from the profile; and reverse questions for the interviewer. The system classifies the company type and tailors round structure accordingly.

**Research Vertical.** A dedicated ranking feed for research internships (`/research/opportunities`) scores opportunities using the same 70/30 semantic+skill formula, matching on `research_interests`. Cold-email pitch generation (`/research/pitch`) uses the same anti-fabrication guard as application drafts.

**Platform IQ Dashboard.** `GET /api/dashboard` returns pipeline breakdown, response rate, ghosts avoided, time saved, and the global Platform IQ with its IQ trend — a real learning curve, not a vanity metric.

---

## The self-improving loop

The evaluation pipeline runs in two modes, both in `app/services/evaluation_service.py`.

**evaluate_now** is the global snapshot: score all `(application, outcome)` pairs. Predictions were written at application creation; outcomes arrive later. Result: response Brier score, ROC-AUC, ghost precision/recall/F1, and Platform IQ = `100 × (0.6 × (1−Brier) + 0.4 × ghost_F1)`. On the seed dataset: IQ 66.7, Brier 0.226, AUC 0.769, ghost F1 0.507.

**build_history** is the learning curve: sort all pairs by `recorded_at`, fix the last 30% as the test set, train a logistic calibrator on 8 growing prefixes of the 70% pool, measure Brier on the fixed test set at each checkpoint. On the seed data: Brier improves 0.249 → 0.197 over 8 checkpoints (n=31 to n=255). The IQ trend on the dashboard is this curve: `IQ_k = 100 × (1 − Brier_k)`. Ghost F1 is excluded from the trend because the ghost shield is rule-based, not trained — including it would make the curve look better without reflecting any learning.

---

## Privacy and safety

- **Per-user data isolation.** Every service touching user-owned rows (applications, outcomes, referrals, research outreach, notifications) extends `BaseService` and filters on `self.user_id`. Cross-user reads are structurally impossible through the service layer.
- **Cohort counts only.** CohortService propagates two aggregate scalars to the `companies` table. No individual user's application content, status, or outcome is accessible to any other user.
- **Anti-fabrication guard.** The LLM is constrained by a profile whitelist and checked post-generation. Grounding score below threshold triggers a rewrite with explicit exclusions before the artifact is stored.
- **Human review before send.** `/applications/:id/send` requires explicit user action after reviewing the draft. Gmail send requires explicit consent (`PUT /api/auth/consent { gmail: true }`).

---

## Tech stack

| Layer | Choice | Why |
|-------|--------|-----|
| Runtime | Python 3.12 | Async-native; CPU-bound work (embeddings, calibration) offloaded via `asyncio.to_thread` |
| API | FastAPI 0.115 + uvicorn[standard] | Async-native, Pydantic v2 validation, automatic OpenAPI |
| ORM | SQLAlchemy 2.0 async + asyncpg | True async; no sync engine anywhere |
| Database | PostgreSQL 17 + pgvector 0.8 | Relational integrity + cosine-distance vector search in one engine |
| Validation | Pydantic v2 strict mode | Catches shape mismatches at the boundary, not at runtime |
| Embeddings | sentence-transformers all-MiniLM-L6-v2 (dim=384) | Free, local, fast; zero embedding API cost |
| LLM | 5-provider fallback router | Resilience + near-zero cost (Groq free tier handles most dev calls) |
| Calibration | scikit-learn LogisticRegression | Lightweight; training set is a few hundred to a few thousand rows |
| Auth | python-jose JWT + passlib argon2 + Google OIDC | argon2 is the current best practice for password hashing |
| Migrations | Alembic async (14 migrations) | Incremental, reviewed, never auto-applied in production |
| Linting | ruff | Fast; enforces imports, naming, and style in one pass |
| Types | mypy --strict (80 files) | Catches service-layer contract violations before tests do |
| Tests | pytest + pytest-asyncio + httpx (316 tests) | Async-native; integration tests hit a real PostgreSQL instance |
| Frontend | TanStack Start + Vite + React | SSR-capable; single `api-client.ts` seam for mock/real switching |

---

## Results — what we measured

All numbers are real, traced to `uv run pytest` or direct database queries on the seed dataset. There are no invented benchmarks.

| Measurement | Value | Source |
|-------------|-------|--------|
| Test suite | 316 / 316 passing | `uv run pytest` |
| mypy | 0 errors (strict, 80 files) | `uv run mypy app` |
| ruff | 0 violations | `uv run ruff check .` |
| Alembic migrations | 14 (0001–0014) | `alembic/versions/` |
| API endpoints | 53 | `grep "^@router\." app/api/v1/*.py` |
| Platform IQ (full set, 364 pairs) | **66.7** | `EvaluationService.evaluate_now()` |
| Response Brier (full set) | 0.226 | same |
| Response AUC | 0.769 | same |
| Ghost F1 | 0.507 | same |
| IQ learning curve — start (n=31) | 75.1 | `EvaluationService.build_history()` |
| IQ learning curve — end (n=255) | 80.3 | same |
| Brier improvement over learning curve | 0.249 → 0.197 | same |
| Seed: demo users | 14 | `scripts/seed_demo.py` |
| Seed: application-outcome pairs | 364 | `scripts/seed_demo.py` |
| Seed: research opportunities | 20 | `scripts/seed_research.py` |
| Ghost weights | age(0.30) + repost(0.20) + vague(0.25) + co.(0.15) + cohort(0.10) | `ghost_service.py` |

---

## Getting started

### Prerequisites

- Python 3.12
- [uv](https://github.com/astral-sh/uv) — `pip install uv`
- Docker Desktop
- Node.js 18+ and npm
- At least one LLM API key (Groq free tier is sufficient for development)

### 1. Clone and configure

```bash
git clone https://github.com/Om-5640/InternPilot.git
cd InternPilot

cp .env.example .env
# Edit .env — at minimum set DATABASE_URL, JWT_SECRET, and one LLM key
```

### 2. Start PostgreSQL with pgvector

```bash
docker run -d \
  --name internpilot-postgres \
  -e POSTGRES_PASSWORD=testpass \
  -p 5433:5432 \
  pgvector/pgvector:pg17
```

### 3. Install Python dependencies and run migrations

```bash
uv sync --all-extras
uv run alembic upgrade head
```

### 4. Seed demo data (recommended)

This gives you 14 demo users, 364 application-outcome pairs, and 20 research opportunities — enough to exercise the Ghost Shield, cohort signal, and the Platform IQ learning curve.

```bash
uv run python scripts/probe_refresh.py   # aggregate real postings (Greenhouse, Ashby, RemoteOK, Remotive)
uv run python scripts/seed_demo.py       # 14 demo users + 364 application-outcome pairs
uv run python scripts/seed_research.py  # 20 research opportunities across IITs, IISc, MIT, Stanford, CMU, ETH, UTokyo, KTH, TIFR, ISI
uv run python scripts/smoke_replay.py   # replay Platform IQ learning curve
```

### 5. Start the backend

```bash
uv run uvicorn app.main:app --reload
# API:  http://localhost:8000
# Docs: http://localhost:8000/docs
```

### 6. Start the frontend

```bash
cd frontend
npm install
npm run dev
# UI: http://localhost:5173
```

Open `http://localhost:5173/auth` and sign up with any email.

### 7. End-to-end smoke test

```bash
uv run python scripts/journey_smoke.py
# Walks 12 journey steps against the live backend and asserts every response shape
```

---

## Running the test suite

Tests require a live PostgreSQL instance with pgvector. Keep the test database separate from the dev database.

```bash
# Create the test database once
docker exec internpilot-postgres psql -U postgres -c "CREATE DATABASE internpilot_test;"

# Run all 316 tests
TEST_DATABASE_URL=postgresql+asyncpg://postgres:testpass@localhost:5433/internpilot_test \
  uv run pytest

# Type-check (strict)
uv run mypy app

# Lint
uv run ruff check .
```

---

## Project structure

```
app/
  main.py                   FastAPI app — lifespan, CORS, router mounts
  core/
    config.py               pydantic-settings; all secrets from env
    database.py             async engine + get_db() dependency
    security.py             JWT create/verify + get_current_user
    errors.py               APIError + global exception handlers
  models/                   SQLAlchemy ORM models (14 tables)
  schemas/                  Pydantic v2 request/response schemas
  services/
    ghost_service.py        5-signal Ghost-Job Shield (no LLM)
    matching_service.py     Semantic ranking + response likelihood (Modules 3+5)
    cohort_service.py       Cross-user aggregate response rates
    application_service.py  Grounded generation + ATS + anti-fabrication guard
    evaluation_service.py   Platform IQ — evaluate_now + build_history
    research_service.py     Research opportunity ranking + pitch generation
    university_normalizer.py  Deterministic name canonicalization
    ...                     (16 service files total)
  llm/
    router.py               5-provider fallback chain
    embeddings.py           Local all-MiniLM-L6-v2, EMBEDDING_DIM=384
  api/v1/                   Thin routers (53 endpoints, no business logic)
  sources/                  Ingestion adapters (Greenhouse, Ashby, Lever, RemoteOK, Remotive)
alembic/versions/           14 reviewed migrations (0001_initial → 0014_research)
tests/                      316 tests across 20 test files
scripts/
  probe_refresh.py          Aggregate real postings from all 5 sources
  seed_demo.py              14 demo users + 364 application-outcome pairs
  seed_research.py          20 research opportunities with pgvector embeddings
  smoke_replay.py           Replay Platform IQ learning curve
  journey_smoke.py          End-to-end 12-step API smoke test
frontend/
  src/lib/api-client.ts     Single HTTP client — mock/real via VITE_USE_MOCKS
  src/routes/               TanStack Start file-based routes
API_CONTRACT.md             Field-level API contract — change here first
CLAUDE.md                   Developer conventions — stack, patterns, module discipline
```

**Engineering artifacts worth reading:** [`API_CONTRACT.md`](API_CONTRACT.md) defines every field name and endpoint shape — the contract is the law, add to it before adding to the code. [`CLAUDE.md`](CLAUDE.md) documents the conventions for adding new modules.

---

## Roadmap

- **Live outcome ingestion.** Gmail OAuth sync is wired at `/api/integrations/gmail/sync` — connecting to a real inbox will start populating real outcomes and improve the IQ curve beyond the seed data.
- **Research vertical expansion.** The 20 seeded research opportunities are a starting point. A live paper-fetch integration (Semantic Scholar / arXiv) would make pitch generation more specific to recent work.
- **Response Likelihood v2.** Once real outcome volume reaches ~500 pairs, replacing the logistic calibrator with a gradient-boosted model is a natural next step.
- **Lever source activation.** `app/sources/lever.py` is implemented. It is excluded from the default refresh loop pending slug discovery tooling.

---

## Screenshots / Demo

<!-- Drop screenshots or a Loom / YouTube link here -->

| Screen | What to see |
|--------|-------------|
| `/feed` | Ranked match feed with ghost scores and match explanations |
| `/assistant` | Cover letter draft with ATS score and grounding score |
| `/dashboard` | Pipeline funnel + Platform IQ learning curve |
| `/pitch` | Research cold-email generator |

---

## Acknowledgments

- [pgvector](https://github.com/pgvector/pgvector) — PostgreSQL as a vector store
- [sentence-transformers](https://www.sbert.net/) — local embedding model, no API cost
- [Groq](https://groq.com/) — fast, free inference during development
- [FastAPI](https://fastapi.tiangolo.com/) and [SQLAlchemy](https://www.sqlalchemy.org/) — async-native Python stack
