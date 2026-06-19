# InternPilot

**Stop applying into the void.**

> **Technical Report:** [DOCUMENTATION.md](DOCUMENTATION.md) — full architecture, every algorithm, engineering decisions with alternatives rejected, real metrics with provenance, and complete reproducibility instructions.

[![Live Demo](https://img.shields.io/badge/live%20demo-internpilot.pages.dev-22c55e?style=flat-square&logo=cloudflare)](https://internpilot.pages.dev)
[![Tests](https://img.shields.io/badge/tests-300%2F300%20passing-22c55e?style=flat-square)](#running-the-test-suite)
[![mypy](https://img.shields.io/badge/mypy-strict%20·%2076%20files-3178c6?style=flat-square)](https://mypy.readthedocs.io/)
[![ruff](https://img.shields.io/badge/ruff-clean-d7ff64?style=flat-square&labelColor=261230)](https://docs.astral.sh/ruff/)
[![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688?style=flat-square&logo=fastapi)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-17%20%2B%20pgvector-336791?style=flat-square&logo=postgresql)](https://www.postgresql.org/)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0%20async-D71F00?style=flat-square)](https://www.sqlalchemy.org/)
[![Deployed](https://img.shields.io/badge/backend-Render%20%2B%20Supabase-46E3B7?style=flat-square)](https://render.com)
[![Frontend](https://img.shields.io/badge/frontend-Cloudflare%20Pages%20SSR-F38020?style=flat-square&logo=cloudflare)](https://pages.cloudflare.com)

---

## The Problem

The internship application pipeline is broken at every layer — and the damage is measurable.

**Ghost jobs are endemic.** Academic research and platform studies consistently find that 20–30% of active job listings receive no meaningful recruiter action. They are reposted across boards to signal fake activity, left open for months with no interviews scheduled. Students spend hours crafting applications that will never be read.

**There is no fit signal.** A student cannot distinguish a 20% match from an 85% match before applying. Generic job boards surface every posting equally. The result is mass-blast behavior — 80 identical résumés fired into the void, no signal returned, no feedback on why.

**Materials are fabricated, not grounded.** AI-assisted cover letters routinely claim skills the applicant cannot demonstrate. This produces strong ATS scores against the JD but collapses in the interview — the only stage that actually matters.

**The referral path is invisible.** Warm introductions convert at 3–5× the rate of cold applications. Most applicants have no systematic way to find who their alumni network knows at a target company.

InternPilot treats job hunting as a **prediction problem.** Every posting is scored for ghost probability before it reaches any feed. Every company is scored for response likelihood using real cross-user outcome data. Every application draft is constrained to what the profile can truthfully claim. A self-grading evaluation loop measures its own prediction accuracy against real outcomes on a fixed held-out test set — and reports an honest learning curve as the cohort grows.

This is not a chatbot wrapper. The core intelligence is a multi-signal ranking engine with a feedback loop that improves as real outcomes accumulate.

---

## What Makes This Different

Three things the platform does that a prompt alone cannot.

### 1. Ghost-Job Shield — five signals, no LLM, O(n) per run

Every posting is scored by a weighted model of five independent signals before it can appear in any feed:

| Signal | Weight | Logic |
|--------|--------|-------|
| Posting age | 0.30 | Step function: 0–14 d → 0.0, 15–29 d → 0.2, 30–59 d → 0.5, 60–89 d → 0.7, ≥90 d → 1.0 |
| Cross-board repost | 0.20 | `source_sightings` counter: 1 board → 0.0, 2 boards → 0.4, 3+ boards → 0.8 |
| JD vagueness | 0.25 | Word count + requirement count + pipeline phrases − tech-term specificity bonus (42 terms) |
| Company ghost history | 0.15 | Rolling average ghost score across all company postings |
| Cohort non-response | 0.10 | Active only when ≥5 batchmates applied to the same company |

Ghost threshold: **0.38.** The repost signal uses a `source_sightings` integer incremented at ingestion — a single column update instead of a GROUP BY join on the hot read path. The five signals complement each other's blind spots: a fresh JD (age=0.0) with vague requirements and pipeline phrases can still cross the threshold entirely on vagueness. An old JD for a well-documented company with real cohort data can stay below it.

**Two-layer defense.** The Ghost Shield catches the obvious ghost: old, vague, multi-board. The response likelihood model catches the deceptive ghost — a recent, specific JD with a strong semantic match, but zero of N batchmates ever heard back. A posting can survive the Shield (ghost_score=0.18) but still rank near the bottom because its cohort response rate is 0/20. Both layers together catch what neither catches alone.

### 2. Cohort-Based Response Likelihood — collective intelligence with per-user privacy

After five or more users apply to the same company, real cross-user response rates feed directly into the ranking signal:

```
expected_value = match_score × response_likelihood × (1 − ghost_score)
```

Response likelihood (data-rich path, ≥5 cohort applications):
```
RL = 0.55 × cohort_response_rate + 0.35 × freshness + 0.10 × (1 − ghost_score)
```

Cold-start (< 5 cohort applications):
```
RL = 0.65 × freshness + 0.35 × (1 − ghost_history_score)
```

`CohortService` writes exactly **two scalars** to the `companies` table: `cohort_applied_count` and `responsiveness_score`. No individual user's application content, status, or `user_id` is ever read by another user's session. The minimum threshold of 5 prevents a single unlucky applicant from mislabeling a genuinely responsive company. The match explanation surfaces this signal in plain English — "Low reply rate: 0 of 6 batchmates heard back" — regardless of how high the semantic similarity score is.

### 3. Self-Improving Platform IQ — honest evaluation methodology

The platform grades its own predictions against real outcomes using a rigorous, audited methodology.

**Honesty by construction.** `predicted_response_prob` and `predicted_ghost` are snapshotted onto the `applications` row at creation time — before any outcome exists. `evaluate_now()` scores them against later outcomes; every evaluation pair is out-of-sample by construction, not by convention or documentation.

**Temporal split, not random.** All pairs are sorted by `recorded_at`. The most recent 30% form a fixed test set that is never trained on. A `LogisticRegression` calibrator is trained on 8 growing prefixes of the 70% training pool and scored against the fixed test set at each checkpoint. Train/test disjointness is `assert`ed in code — not logged, **asserted** — so the run aborts on leakage rather than silently producing inflated numbers.

**Platform IQ formula:**
```
IQ = 100 × (0.60 × (1 − Brier) + 0.40 × ghost_F1)
```

**Measured on the seed dataset** (364 application-outcome pairs, 14 simulated cohort users, 12 companies):

| Metric | Value |
|--------|-------|
| Platform IQ (full set, evaluate_now) | **66.7** |
| Response Brier score | 0.226 |
| Response AUC-ROC | 0.769 |
| Ghost F1 | 0.507 |
| IQ learning curve — start (n=31) | 75.1 / Brier 0.249 |
| IQ learning curve — end (n=255) | 80.3 / Brier 0.197 |

All numbers are real. Traced to `scripts/smoke_replay.py` run on the deterministic seed dataset (RNG seed=42). No invented benchmarks.

---

## Modules

All 12 modules are built, tested, and deployed. No planned-but-unshipped features in this table.

| Module | Status | What it does |
|--------|--------|--------------|
| 0 — Auth | **Shipped** | Signup/login, JWT (python-jose), Google OIDC, argon2 password hashing (Password Hashing Competition winner), per-user data isolation enforced at service layer |
| 1 — Career Twin | **Shipped** | Résumé parsing via LLM extraction (JSON prompt), GitHub connect, 384-dim profile embedding (local, free), `profile_strength` score (0–100), gap detection against top-50 matches |
| 2 — Ingestion | **Shipped** | 5 source adapters (Greenhouse, Ashby, Lever, RemoteOK, Remotive), SHA-1 dedup key, `source_sightings` counter incremented at ingest rather than aggregated at read time |
| 3+5 — Match & Rank | **Shipped** | pgvector HNSW cosine search, `match_score = 0.70×semantic + 0.30×skill`, two-path response likelihood, `expected_value` ranking key, deterministic match explanations (no LLM on critical path) |
| 4 — Ghost Shield | **Shipped** | 5-signal weighted model, no LLM calls, O(n) per run, two-layer defense with response likelihood catching deceptive posts |
| 6 — Application Assistant | **Shipped** | Cover letter / email / referral intro, profile whitelist, grounding guard with regeneration loop (not post-processing), ATS scoring (deterministic, no LLM), Job Decoder |
| 7 — Tracker / Outcomes | **Shipped** | Full status FSM: `saved → applied → viewed → responded → interview → offer / rejected / ghosted`, follow-up draft generation, Gmail sync (explicit consent-gated) |
| 8 — Referral Finder | **Shipped** | Alumni matching by company + canonical university name, deterministic canonicalization (30-entry alias map, 42 tests), LLM-drafted intro with same grounding guard |
| 10 — Research Vertical | **Shipped** | Research opportunity ranking via embedding match on `research_interests`, cold-email pitch generation with same anti-fabrication guard as applications, outreach tracking |
| 11 — Platform IQ | **Shipped** | Pipeline funnel, response rate, ghosts avoided, time saved, full learning curve (evaluate_now + build_history with temporal split) |
| 12 — Notifications | **Shipped** | 4 types: `followup_due`, `response`, `status_change`, `new_match`; idempotent generation (content-hash dedup), user-scoped |

**Test suite: 300 tests across 19 files.** Integration tests hit a real PostgreSQL + pgvector instance with real Alembic migrations applied at session start.

---

## Architecture

```mermaid
flowchart TD
    subgraph SRC["Ingestion — 5 sources"]
        G[Greenhouse] & A[Ashby] & RO[RemoteOK] & RV[Remotive] & LV[Lever]
    end

    SRC --> AGG["AggregationService\ndedup + normalize\nsource_sightings++"]
    AGG --> PG[("PostgreSQL 17 + pgvector\nHNSW index · Supabase")]

    subgraph TWIN["Career Twin — Module 1"]
        RES["Résumé / GitHub"] --> PROF["ProfileService\nLLM extraction\nskills · exp · projects"]
        PROF --> EMB["sentence-transformers\nall-MiniLM-L6-v2\ndim=384 · local · free"]
    end

    EMB -->|"profile.embedding"| PG
    AGG --> GHOST["GhostService\n5-signal weighted model\nno LLM · O(n)"]
    GHOST -->|"ghost_score · is_ghost"| PG

    PG --> MATCH["MatchingService\n0.70 × cosine + 0.30 × skill\nexpected_value ranking"]
    TWIN --> MATCH

    PG --> RL["Response Likelihood\ncohort ≥5: 0.55 rate + 0.35 fresh + 0.10 ghost-inv\ncold-start: 0.65 fresh + 0.35 ghost-hist-inv"]
    RL --> MATCH

    MATCH --> APPAS["ApplicationService\nLLM draft · whitelist\ngrounding guard · ATS"]
    APPAS --> PG

    PG --> TRACK["TrackerService\nstatus FSM · outcomes"]
    TRACK --> COHORT["CohortService\n2 scalars only\nnever cross-user rows"]
    COHORT -->|"responsiveness_score\ncohort_applied_count"| PG
    COHORT --> RL

    PG --> EVAL["EvaluationService\nevaluate_now · build_history\ntemporal 70/30 · asserted disjoint"]
    EVAL --> DASH["Dashboard · Platform IQ\npipeline funnel · iq_trend"]
```

Data flows from five aggregated sources through deduplication into PostgreSQL with a pgvector HNSW index. The Ghost Shield scores every posting independently — five pure signal functions, no external calls. The Career Twin produces a 384-dimensional profile vector via a local sentence-transformer. The matching engine blends cosine distance with skill overlap, multiplies by response likelihood and a ghost penalty, and ranks by `expected_value`. Application drafts are constrained by a profile whitelist with post-generation grounding checks and a regeneration pass if grounding falls below threshold. Outcomes flow through CohortService (aggregate counts only, never individual rows) back into the response likelihood model and into a calibration loop that produces the Platform IQ learning curve.

---

## Tech Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| Runtime | Python 3.12 | Async-native; walrus operator; improved type narrowing in mypy strict mode |
| API | FastAPI 0.115 + uvicorn[standard] | Async-native; Pydantic v2 validation; automatic OpenAPI at `/api/docs` |
| ORM | SQLAlchemy 2.0 async + asyncpg | True async `AsyncSession` everywhere; zero sync engine in the entire codebase |
| Database | PostgreSQL 17 + pgvector 0.8 | Relational integrity + HNSW approximate nearest-neighbor search in one engine |
| Validation | Pydantic v2 strict mode | Shape mismatches caught at system boundary, not at runtime |
| Embeddings | sentence-transformers all-MiniLM-L6-v2 (dim=384) | Local, in-process, zero API cost; `asyncio.to_thread` prevents event loop blocking |
| LLM | 5-provider fallback router (Gemini → Groq → OpenRouter → DeepSeek → Ollama) | Any single provider outage is transparent; Groq free tier handles dev; no hard-fail |
| Calibration | scikit-learn LogisticRegression | Lightweight Platt-scaling; temporal split; no GPU |
| Auth | python-jose JWT + passlib argon2 + google-auth OIDC | argon2 is memory-hard; Password Hashing Competition winner |
| Migrations | Alembic async (18 migrations) | Incremental, reviewed, never auto-applied in production |
| Package manager | uv | Deterministic lockfile; `uv sync --frozen --no-cache` in Docker |
| Types | mypy --strict (76 files) | Catches service-layer contract violations before tests; structural isolation enforcement |
| Tests | pytest + pytest-asyncio + httpx (300 tests) | Async-native; integration against real PostgreSQL + pgvector |
| Frontend | TanStack Start + React 19 + Vite 7 + Tailwind CSS | SSR-capable file-based routing; single `api-client.ts` seam |
| Frontend hosting | Cloudflare Pages (SSR Worker) | Edge-deployed SSR; nitro Cloudflare Pages preset; `nodejs_compat` flag |
| Backend hosting | Render.com (Docker) | Multi-stage build; CPU-only PyTorch (~200 MB vs 2 GB CUDA); `start.sh` applies migrations on boot |
| Database hosting | Supabase PostgreSQL + pgvector | Session Pooler for IPv4 compatibility; all 18 migrations applied |

---

## Key Engineering Decisions

### Multi-LLM fallback router

`app/llm/router.py` chains five providers. A provider whose API key is absent raises `_ProviderSkippedError` and is silently skipped. On 429, timeout, or any error, `BACKOFF_S = 0.5` is awaited and the next provider is tried automatically. The same `complete(messages) → str` interface is used in tests (providers mocked) and production (real keys). No test ever makes a real LLM API call. **Alternative rejected:** LiteLLM. A heavy dependency for a use case coverable in 200 lines introduced version-coupling risk without benefit.

### Local sentence-transformers + pgvector HNSW

`all-MiniLM-L6-v2` runs via `asyncio.to_thread` — CPU-bound, never blocks the event loop, zero API cost at any scale. Model is downloaded once on first call and held in memory for the process lifetime. **Why HNSW over IVFFlat:** IVFFlat requires centroid training on a minimum row count. HNSW builds incrementally and is immediately queryable from row one.

### Ghost Shield: weighted sum over a single heuristic

A pure age threshold flags seasonal programs, rolling applications, and genuinely active old postings. The vagueness signal catches fresh ghosts (age=0.0 but no requirements, pipeline phrases). The repost signal fires on the second board without needing age data. All five weights are named module-level constants — they can be changed, tested, and discussed without touching logic. **Alternative rejected:** A trained classifier. Ghost labels don't exist at launch. The weighted heuristic provides reasonable precision from day one.

### Anti-fabrication grounding guard with regeneration

`_grounding_score()` computes the fraction of JD requirements claimed in the draft that are backed by profile evidence. If below 0.70, `_find_unsupported_claims()` names the fabricated terms and a correction prompt forces regeneration with explicit exclusions. **Why regeneration over post-processing:** Removing skill names from generated prose produces grammatically broken sentences. A regeneration pass produces coherent prose that simply omits the unsupported claims.

### Data isolation: structural, not conventional

`BaseService` declares `_scope()` as `NotImplementedError`. Every service method calling it must add `.where(Model.user_id == self.user_id)` or the call fails at development time. `CohortService` and `EvaluationService` are explicitly not BaseService subclasses; their module docstrings document exactly which cross-user reads they perform and why. **Why structural over naming convention:** A convention is invisible in code review and silently omittable. A failing method call is not.

### Self-improving evaluation: temporal split with code-level disjointness assertion

A random 70/30 split would allow training on outcomes from week 4 while testing on outcomes from week 1 — future data predicting past. The temporal split by `recorded_at` ensures every test pair occurred after all training pairs. Train/test disjointness is `assert train_ids & test_ids == set()` at every prefix — not a log warning, an assertion that aborts the run if violated. LogisticRegression Platt-scales the cold-start probabilities to better calibration as labeled pairs accumulate.

---

## Results

All numbers are real, traced to source or test output. No invented benchmarks.

| Measurement | Value | Source |
|-------------|-------|--------|
| Test suite | **300 / 300 passing** | `uv run pytest` against live PostgreSQL + pgvector |
| mypy --strict | **0 errors, 76 source files** | `uv run mypy app` |
| ruff | **0 violations** | `uv run ruff check .` |
| Alembic migrations | **18** (0001–0018) | `alembic/versions/` |
| API endpoints | **54** | `@router.` decorators in `app/api/v1/*.py` |
| Service files | **17** | `app/services/*.py` |
| Platform IQ (364 pairs) | **66.7** | `EvaluationService.evaluate_now()` via `smoke_replay.py` |
| Response Brier score | **0.226** | same |
| Response AUC-ROC | **0.769** | same |
| Ghost F1 | **0.507** | same |
| IQ learning curve | **75.1 → 80.3** (8 checkpoints) | `EvaluationService.build_history()` |
| Brier improvement | **0.249 → 0.197** over 8 checkpoints | same |
| Ghost weights sum | **1.000** | `tests/test_ghost.py` verifies this |
| Demo users | 14 | `scripts/seed_demo.py` DEMO_USERS list |
| App-outcome pairs | 364 | `scripts/seed_demo.py` (26 postings × 14 users) |
| Alumni contacts seeded | 23 | `scripts/seed_demo.py` ALUMNI_CONTACTS |
| Research opportunities | 20 | `scripts/seed_research.py` |
| University alias entries | 30 | `app/services/university_normalizer.py` |
| Normalizer tests | 42 | `tests/test_university_normalizer.py` |

---

## Setup

### Prerequisites

- Python 3.12
- [uv](https://github.com/astral-sh/uv) — `pip install uv`
- Docker Desktop (for PostgreSQL + pgvector)
- Node.js 18+ and npm
- At least one LLM API key (Groq free tier is sufficient for all development)

### 1. Clone and configure

```bash
git clone https://github.com/Om-5640/InternPilot.git
cd InternPilot
cp .env.example .env
# Set DATABASE_URL, JWT_SECRET, and at least one LLM key (GROQ_API_KEY is free)
```

Key env vars:

```
DATABASE_URL=postgresql+asyncpg://postgres:testpass@localhost:5433/internpilot
JWT_SECRET=change-me-in-production-32-chars-min
GEMINI_API_KEY=
GROQ_API_KEY=
OPENROUTER_API_KEY=
GOOGLE_CLIENT_ID=
CORS_ORIGINS=http://localhost:5173
```

### 2. Start PostgreSQL with pgvector

```bash
docker run -d \
  --name internpilot-postgres \
  -e POSTGRES_PASSWORD=testpass \
  -p 5433:5432 \
  pgvector/pgvector:pg17
```

### 3. Install and migrate

```bash
uv sync --all-extras
uv run alembic upgrade head   # applies all 18 migrations; first one runs CREATE EXTENSION IF NOT EXISTS vector
```

### 4. Seed demo data

```bash
uv run python scripts/probe_refresh.py   # pull real postings from Greenhouse, Ashby, RemoteOK, Remotive
uv run python scripts/seed_demo.py       # 14 demo users + 364 application-outcome pairs (RNG seed=42)
uv run python scripts/seed_research.py  # 20 research opportunities with pgvector embeddings
uv run python scripts/smoke_replay.py   # replay Platform IQ learning curve — prints 8 checkpoints
```

### 5. Start the backend

```bash
uv run uvicorn app.main:app --reload
# API:  http://localhost:8000
# Docs: http://localhost:8000/api/docs
```

### 6. Start the frontend

```bash
cd frontend
npm install
npm run dev
# UI: http://localhost:5173
```

Open `http://localhost:5173/auth` to sign up. Set `VITE_USE_MOCKS=false` in `frontend/.env` to connect to the live backend.

### 7. Run the full test suite

```bash
docker exec internpilot-postgres psql -U postgres -c "CREATE DATABASE internpilot_test;"

TEST_DATABASE_URL=postgresql+asyncpg://postgres:testpass@localhost:5433/internpilot_test \
  uv run pytest

uv run mypy app        # 0 errors, strict mode, 76 files
uv run ruff check .    # 0 violations
```

### 8. End-to-end API smoke test

```bash
uv run python scripts/journey_smoke.py
# Expected: === ALL 12 STEPS PASSED ===
```

---

## Project Structure

```
app/
  main.py                   FastAPI app — lifespan, CORS, router mounts
  core/
    config.py               pydantic-settings; all secrets from env, never hardcoded
    database.py             async engine + get_db() dependency
    security.py             JWT create/verify + get_current_user
    errors.py               APIError → {error:{code,message}} with matching HTTP status
  models/                   13 SQLAlchemy ORM models (TimestampMixin on all: UUID id, created_at, updated_at)
  schemas/                  Pydantic v2 request/response schemas (one file per module)
  services/
    base.py                 BaseService — data-isolation scaffold (28 lines, structural enforcement)
    ghost_service.py        5-signal Ghost-Job Shield (no LLM, O(n))
    matching_service.py     Semantic ranking + response likelihood (Modules 3+5 co-located)
    cohort_service.py       Cross-user aggregate response rates (2 scalars only)
    application_service.py  Grounded generation + ATS + anti-fabrication regeneration loop
    evaluation_service.py   Platform IQ — evaluate_now + build_history (temporal split, asserted disjoint)
    research_service.py     Research opportunity ranking + cold-email pitch
    university_normalizer.py  Deterministic canonicalization (30 entries, pure function, 42 tests)
    ... (17 service files total)
  llm/
    router.py               5-provider fallback chain (Gemini→Groq→OpenRouter→DeepSeek→Ollama)
    embeddings.py           Local all-MiniLM-L6-v2, EMBEDDING_DIM=384
  api/v1/                   Thin routers — 54 endpoints, zero business logic
  sources/                  Ingestion adapters (Greenhouse, Ashby, Lever, RemoteOK, Remotive)
alembic/versions/           18 reviewed migrations (0001_initial → 0018_posting_decode_cache)
tests/                      300 tests across 19 files (integration against real PostgreSQL + pgvector)
scripts/
  seed_demo.py              14 users + 364 app-outcome pairs (deterministic RNG seed=42)
  seed_research.py          20 research opportunities with pgvector embeddings
  probe_refresh.py          Aggregate real postings from all 5 sources
  smoke_replay.py           Platform IQ learning curve (evaluate_now + build_history, 8 checkpoints)
  journey_smoke.py          12-step end-to-end API smoke test
frontend/
  src/lib/api-client.ts     Single HTTP client — mock/real via auth state or VITE_USE_MOCKS
  src/lib/mocks.ts          In-memory mock data for guest/unauthenticated mode
  src/routes/               TanStack Start file-based routes (11 routes)
  vite.config.ts            nitro cloudflare-pages preset for SSR Worker bundling
API_CONTRACT.md             Field-level API contract — single source of truth; change here first
CLAUDE.md                   Developer conventions — stack, patterns, module discipline, migration commands
```

---

## Live Deployment

| Component | Platform | Details |
|-----------|----------|---------|
| Frontend | Cloudflare Pages (SSR Worker) | TanStack Start + nitro Cloudflare Pages preset; `nodejs_compat` compatibility flag; edge-deployed |
| Backend | Render.com (Docker) | Multi-stage build; CPU-only PyTorch wheel (~200 MB vs 2 GB CUDA); `scripts/start.sh` runs `alembic upgrade head` then uvicorn on boot |
| Database | Supabase PostgreSQL 17 + pgvector | Session Pooler (IPv4) for Render free tier compatibility; all 18 migrations applied; pgvector extension in migration 0001 |

---

## Privacy and Safety

- **Per-user isolation.** Every service touching user-owned rows extends `BaseService` and filters on `self.user_id`. Cross-user reads are structurally impossible through the service layer — `_scope()` raises `NotImplementedError` if the filter is missing.
- **Cohort counts only.** `CohortService` propagates exactly two aggregate scalars. No individual application content, status, or `user_id` is accessible to any other user's session.
- **Anti-fabrication guard.** The LLM is constrained by a profile whitelist before generation and checked against it after. Below-threshold grounding triggers a rewrite with explicit unsupported-claim exclusions.
- **Human review before send.** Applications require explicit user action after reviewing the draft. Gmail sync requires an explicit consent flag in the user record.

---

## Acknowledgments

- [pgvector](https://github.com/pgvector/pgvector) — PostgreSQL as a vector store with HNSW indexing
- [sentence-transformers](https://www.sbert.net/) — local embedding model, zero API cost at any scale
- [Groq](https://groq.com/) — fast, free inference during development
- [FastAPI](https://fastapi.tiangolo.com/) and [SQLAlchemy](https://www.sqlalchemy.org/) — async-native Python stack
- [TanStack Start](https://tanstack.com/start) — SSR-capable React framework with file-based routing
- [Supabase](https://supabase.com/) — managed PostgreSQL with pgvector support
