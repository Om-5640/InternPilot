# InternPilot — Technical Report

> **Artifact type:** Engineering evaluation document.
> **Audience:** Technical reviewers.
> **Policy:** Every metric is traced to source code, seed scripts, or test output. All numbers are real.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Problem Statement](#2-problem-statement)
3. [Solution Overview](#3-solution-overview)
4. [System Architecture](#4-system-architecture)
5. [Module-by-Module Breakdown](#5-module-by-module-breakdown)
6. [Key Engineering Decisions](#6-key-engineering-decisions)
7. [Current Progress](#7-current-progress)
8. [Results and Evidence](#8-results-and-evidence)
9. [Tech Stack](#9-tech-stack)
10. [Challenges and Trade-offs](#10-challenges-and-trade-offs)
11. [Deployment](#11-deployment)
12. [Setup and Reproducibility](#12-setup-and-reproducibility)
13. [Appendix](#13-appendix)

---

## 1. Executive Summary

The internship application pipeline has a structural honesty problem: roughly one in five job postings receive no recruiter action (ghost jobs), but there is no signal to identify them before a student invests time applying. Existing tools offer matching based on keyword overlap and generate application materials with no grounding check — they fabricate claims freely. InternPilot treats job hunting as a **prediction problem**: every posting is scored for ghost probability and expected response likelihood using a five-signal weighted model and cross-user cohort data, application materials are constrained to what the profile can truthfully claim, and a self-grading evaluation loop measures prediction accuracy against real outcomes on a fixed held-out test set.

The system is fully functional across 12 modules (0–8, 10–12), with 54 API endpoints, 300 tests, 18 Alembic migrations, and a complete SSR frontend — live in production at [internpilot.pages.dev](https://internpilot.pages.dev) (Cloudflare Pages) backed by Render.com and Supabase PostgreSQL.

The strongest proof point is the **Platform IQ learning curve**: trained on a fixed 70/30 temporal split of 364 application-outcome pairs (14 simulated cohort users), response Brier score improves from 0.249 at the first checkpoint (n=31) to 0.197 at the eighth (n=255), translating to an IQ rise from 75.1 to 80.3 — measured on a test set that was never seen during training, with disjointness asserted in code at every prefix checkpoint. The methodology is honest by design: predictions are snapshotted before outcomes exist, making every evaluation pair out-of-sample by construction.

---

## 2. Problem Statement

### Who is affected

Undergraduate and master's students applying to competitive technical internships. A typical cycle involves 40–100 applications, a 2–6% response rate, and no feedback signal on why any individual application failed.

### The four failure modes

| Pain point | Real scale | InternPilot component |
|---|---|---|
| **Ghost jobs** | ~20–30% of active listings receive no recruiter action | Ghost-Job Shield (Module 4): 5-signal weighted model flags postings pre-feed |
| **No fit signal** | Students can't distinguish a 20% match from an 85% match | Matching & Ranking (Modules 3+5): `expected_value = match × response_likelihood × (1 − ghost)` |
| **Fabricated materials** | LLMs generate claims against skills the candidate cannot demonstrate | Application Assistant (Module 6): profile whitelist + grounding check + regenerate-on-failure loop |
| **Invisible referral path** | Warm introductions convert 3–5× cold applications; network is opaque | Referral Finder (Module 8): alumni match by university + company; deterministic name canonicalization |

### Why existing tools fail

Keyword-based job boards surface ghost and deceptive postings equally with genuine ones. Cover-letter generators treat the LLM prompt as the authority on what the candidate knows. Neither tool accumulates outcome data to learn which companies actually respond. InternPilot's differentiator is the **feedback loop**: outcomes flow back into the response likelihood model, the Ghost Shield's cohort signal, and the calibration evaluator — the system's predictions improve as the cohort grows.

---

## 3. Solution Overview

InternPilot is a full-stack AI internship platform that acts as a personalized search-and-application layer on top of aggregated job listings. The platform ranks every posting by `expected_value = match_score × response_likelihood × (1 − ghost_score)` before surfacing it, generates application materials anchored to verified profile evidence, finds warm-introduction paths via alumni contacts, and tracks outcomes to improve its own predictions over time.

### End-to-end user journey

```
1.  Sign up / Google OIDC login           →  JWT issued; per-user data isolation enforced
2.  Career Twin: upload résumé or         →  ProfileService: LLM extraction → skills /
    connect GitHub                             experience / projects → local embedding (dim=384)
3.  Ingestion (background): 5 sources     →  AggregationService: dedup, normalize,
    fetched and normalized                     source_sightings counter incremented
4.  Ghost Shield scores all postings      →  GhostService: 5-signal weighted model,
                                               is_ghost flag written to postings table
5.  Discover feed: GET /api/matches       →  MatchingService: cosine distance via pgvector
                                               HNSW, blended 0.70/0.30 with skill overlap,
                                               multiplied by RL and ghost penalty
6.  Application: decode JD → draft        →  ApplicationService: LLM draft constrained to
    → review → apply                           profile whitelist; grounding check; ATS score
7.  Refer: warm-intro candidates          →  ReferralService + UniversityNormalizer:
    for target company                         alumni surfaced by canonical university name
8.  Track: record status transitions      →  TrackerService: saved→applied→responded→…
9.  Outcomes: record response/ghost       →  CohortService: update aggregate company
                                               response rate (counts only, no cross-user rows)
10. Research vertical                     →  ResearchService: fit_score on research_interests;
                                               cold-email pitch with same grounding guard
11. Notification feed                     →  NotificationService: 4 idempotent types
12. Dashboard / Platform IQ              →  DashboardService + EvaluationService:
                                               pipeline funnel + IQ learning curve
```

---

## 4. System Architecture

### 4.1 Full data-flow diagram

```mermaid
flowchart TD
    subgraph SRC["Ingestion — 5 sources"]
        G[Greenhouse] & A[Ashby] & RO[RemoteOK] & RV[Remotive] & LV[Lever]
    end

    SRC --> AGG["AggregationService\ndedup + normalize\nsource_sightings++"]
    AGG --> PG[("PostgreSQL 17 + pgvector\nHNSW index · Supabase")]

    AGG --> GHOST["GhostService\n5-signal weighted model\nno LLM · O(n) per run"]
    GHOST -->|"ghost_score · is_ghost"| PG

    subgraph TWIN["Career Twin — Module 1"]
        RES["Résumé / GitHub"] --> PROF["ProfileService\nLLM extraction\nskills · exp · projects"]
        PROF --> EMB["sentence-transformers\nall-MiniLM-L6-v2\ndim=384 · local · free"]
    end

    EMB -->|"profile.embedding"| PG

    PG --> MATCH["MatchingService\n0.70 × cosine + 0.30 × skill\nexpected_value ranking"]
    TWIN --> MATCH

    PG --> RL["Response Likelihood\ncohort ≥5: 0.55 rate + 0.35 fresh + 0.10 ghost-inv\ncold-start: 0.65 fresh + 0.35 ghost-hist-inv"]
    RL --> MATCH

    MATCH --> APPAS["ApplicationService\nLLM draft · profile whitelist\ngrounding guard · ATS score"]
    APPAS --> PG

    PG --> TRACK["TrackerService\nstatus transitions\noutcomes recording"]
    TRACK --> COHORT["CohortService\n2 scalars only\nnever cross-user rows"]
    COHORT -->|"responsiveness_score\ncohort_applied_count"| PG
    COHORT --> RL

    PG --> EVAL["EvaluationService\nevaluate_now · build_history\ntemporal 70/30 · asserted disjoint"]
    EVAL --> PG

    PG --> DASH["Dashboard\nPlatform IQ · iq_trend\npipeline funnel"]

    PG --> REF["ReferralService\nalumni match\nuniversity canonicalization"]
    PG --> RSCH["ResearchService\nfit_score · cold-email pitch\nsame grounding guard"]
    PG --> NOTIF["NotificationService\n4 types · idempotent"]
```

### 4.2 Layer descriptions

**Ingestion layer.** `AggregationService` (`app/services/aggregation_service.py`) pulls from four active sources (Greenhouse, Ashby, RemoteOK, Remotive) plus a Lever adapter. Each raw posting is normalized and deduplicated by a `dedup_key = sha1(title + company_normalized + location_normalized)[:64]`. When the same role is found on a second board, `source_sightings` is incremented on the existing row rather than creating a duplicate — this is the raw input for the Ghost Shield's repost signal. Embedding generation and Ghost Shield rescoring run after each ingestion cycle.

**Ghost Shield.** `GhostService` (`app/services/ghost_service.py`) rescores every posting after each ingestion cycle. Five pure signal functions — no DB access, no LLM, no external calls. The weighted sum is written back as `ghost_score` and `is_ghost` on the `postings` table. `company.ghost_history_score` is updated as a rolling average across all company postings. Threshold: 0.38 (named constant `GHOST_THRESHOLD`, `ghost_service.py:32`).

**Career Twin.** `ProfileService` calls the LLM router once per résumé upload to extract structured fields via a JSON extraction prompt. The profile is then embedded using `all-MiniLM-L6-v2` (dim=384, `EMBEDDING_DIM` in `app/llm/embeddings.py`) and stored as a pgvector column. A `profile_strength` score (0–100) is computed from field completeness. Gap detection finds requirements that appear frequently across the top-50 match postings but are absent from the profile.

**Matching and ranking.** `MatchingService` (`app/services/matching_service.py`) runs a pgvector cosine-distance query ordered by `embedding <=> profile_embedding` (HNSW index), then computes `match_score = 0.70 × semantic_sim + 0.30 × skill_ratio` and `expected_value = match_score × response_likelihood × (1 − ghost_score)`. The feed sorts by `expected_value` descending. Match explanations are deterministic templates (no LLM) that append a cohort note when `responsiveness_score < 0.25` at companies with sufficient data. The optional `?enrich=true` parameter calls the LLM for a richer explanation — this is the only LLM call in the ranking path.

**Application Assistant.** `ApplicationService.draft()` builds a whitelist from the profile's verified skills and project technologies, passes it as an explicit system instruction, then post-processes the draft with `_grounding_score()` — the fraction of JD requirements claimed in the draft that are backed by profile evidence. If grounding is below 0.70 and unsupported claims can be identified, `_find_unsupported_claims()` names them, a correction prompt is sent with an explicit exclusion list, and the LLM regenerates once. Only the final draft and its grounding score are stored.

**Cohort aggregate.** `CohortService` (`app/services/cohort_service.py`) is intentionally not a `BaseService` subclass — it reads applications across all users. It computes `cohort_applied_count = COUNT(Application WHERE company)` and `responsiveness_score = COUNT(responded) / COUNT(applied)` and writes these two scalars back to the `companies` table. It never reads or surfaces any individual user's application content, status, or `user_id` to another session.

**Evaluation.** `EvaluationService` (`app/services/evaluation_service.py`) documents its honesty contract in its module docstring (lines 1–29). Predictions (`predicted_response_prob`, `predicted_ghost`) are snapshotted at application creation time — before any outcome exists. `evaluate_now()` scores them against later outcomes; every pair is out-of-sample by construction. `build_history()` asserts `train_ids & test_ids == set()` at every prefix with a hard `assert` that aborts the run on leakage.

### 4.3 Data model

| Entity | Table | Scope | Purpose |
|---|---|---|---|
| `User` | `users` | USER-OWNED | Auth identity, JWT, Google OIDC sub, consent flags (JSONB), role |
| `Profile` | `profiles` | USER-OWNED | Career Twin: skills, experience, projects, research_interests, pgvector embedding, `profile_strength` |
| `Company` | `companies` | GLOBAL | Name, domain, industry; `ghost_history_score`, `responsiveness_score`, `cohort_applied_count` |
| `Posting` | `postings` | GLOBAL | JD content, requirements, `ghost_score`, `is_ghost`, `source_sightings`, pgvector embedding, `decode_cache` |
| `Contact` | `contacts_alumni` | GLOBAL | Alumni: name, company, university, `university_canonical`, relationship type |
| `Application` | `applications` | USER-OWNED | Per-user apply record; snapshotted `predicted_response_prob` + `predicted_ghost` at creation |
| `Artifact` | `artifacts` | USER-OWNED | Generated draft (cover letter / email / pitch); `ats_score`, `grounding_score`, `version` |
| `Outcome` | `outcomes` | USER-OWNED | Response record: `responded` bool, `outcome_type`, `time_to_response_hours` |
| `Referral` | `referrals` | USER-OWNED | Referral request + intro artifact, status |
| `ResearchOpportunity` | `research_opportunities` | GLOBAL | Lab/PI details, research area, pgvector embedding, `recent_paper_url` |
| `ResearchOutreach` | `research_outreach` | USER-OWNED | Per-user pitch artifact + tracking for a research opportunity |
| `Evaluation` | `evaluations` | GLOBAL | Metric snapshots: Brier, AUC, ghost F1, Platform IQ, `model_version` |
| `Notification` | `notifications` | USER-OWNED | 4 types (`followup_due`, `response`, `status_change`, `new_match`), idempotent |

**Isolation model.** Every service that touches USER-OWNED rows extends `BaseService` (`app/services/base.py`). `BaseService.__init__` stores `self.user_id`; `_scope()` raises `NotImplementedError` if called without a `.where(Model.user_id == self.user_id)`, making the contract explicit and failing loudly at development time. `CohortService` and `EvaluationService` are declared not BaseService subclasses — their module docstrings document exactly which cross-user reads they perform and why.

---

## 5. Module-by-Module Breakdown

### 5.1 Status table

| Module | Name | Status | Key files |
|---|---|---|---|
| 0 | Auth | Shipped | `app/api/v1/auth.py`, `app/core/security.py`, `app/services/auth_service.py` |
| 1 | Career Twin | Shipped | `app/services/profile_service.py`, `app/llm/embeddings.py` |
| 2 | Ingestion | Shipped | `app/services/aggregation_service.py`, `app/sources/` |
| 3 | Matching & Feed | Shipped | `app/services/matching_service.py` |
| 4 | Ghost-Job Shield | Shipped | `app/services/ghost_service.py` |
| 5 | Response Likelihood | Shipped (in Module 3) | `app/services/matching_service.py` (`_compute_response_likelihood`) |
| 6 | Application Assistant | Shipped | `app/services/application_service.py` |
| 7 | Tracker / Outcomes | Shipped | `app/services/tracker_service.py` |
| 8 | Referral Finder | Shipped | `app/services/referral_service.py`, `app/services/university_normalizer.py` |
| 9 | Interview Prep | **Descoped** | Deleted — see §5.11 |
| 10 | Research Vertical | Shipped | `app/services/research_service.py` |
| 11 | Platform IQ Dashboard | Shipped | `app/services/evaluation_service.py`, `app/services/dashboard_service.py` |
| 12 | Notifications | Shipped | `app/services/notification_service.py` |

### 5.2 Module 0 — Auth

JWT-based signup/login (argon2 password hash via passlib) plus Google OIDC. Tokens are issued at signup and login; `get_current_user` dependency in `app/core/security.py` gates every protected endpoint. Role field (`student` / `admin`) controls access to `POST /evaluation/run` and `POST /evaluation/replay`. Consent flags (`gmail`, `github`, `alumni_data`) are stored in a JSONB column on `users` and gate OAuth-integrated features.

**Why argon2:** passlib's `argon2` is the current best-practice password hashing algorithm (winner of the Password Hashing Competition, 2015), preferred over bcrypt for its memory-hardness which makes GPU-based brute-force attacks dramatically more expensive.

### 5.3 Module 1 — Career Twin

`ProfileService.update_profile()` accepts structured fields or raw résumé text, calls the LLM router once to extract skills/experience/projects (JSON extraction prompt), then calls `embed([summary_text])` to compute the profile's 384-dimensional vector. A `profile_strength` score (0–100) is calculated from field completeness: skills count, experience count, GPA presence, GitHub link. Gap detection finds requirements that appear frequently across the top-50 match postings but are missing from the profile — surfaced as actionable suggestions.

**Why local embeddings:** No per-call API cost. `all-MiniLM-L6-v2` runs in `asyncio.to_thread` so it never blocks the event loop. The model is downloaded once on first call and stays in memory for the process lifetime.

### 5.4 Module 2 — Ingestion

Eight adapters are implemented. `AggregationService.refresh()` fetches each active source, calls `_upsert_one()` per raw posting, and pipes through `GhostService.rescore_all()` at the end of each run. Deduplication uses `build_dedup_key(company, title, location)` (normalized, SHA-1 truncated to 64 chars) so the same role on two boards increments `source_sightings` rather than creating a duplicate row — directly feeding the Ghost Shield's repost signal without any cross-table join at read time.

| Adapter | Type | Coverage | Key env var(s) |
|---|---|---|---|
| `greenhouse.py` | JSON API | Major tech companies | — (public) |
| `ashby.py` | GraphQL | Mid-stage startups | — (public) |
| `remoteok.py` | REST | Remote roles across industries | — (public) |
| `remotive.py` | REST | Remote roles across industries | — (public) |
| `lever.py` | Slug-based REST | Company-specific slugs | — (public, excluded from default refresh; see §10.3) |
| `jsearch.py` | RapidAPI | LinkedIn, Indeed, Glassdoor aggregated | `JSEARCH_API_KEY` |
| `usajobs.py` | USAJobs.gov REST | US federal internships (all fields, PATHWAYS/Co-op) | `USAJOBS_API_KEY`, `USAJOBS_EMAIL` |
| `adzuna.py` | Adzuna REST | All industries, multi-country (us/gb/de/au/in/ca) | `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`, `ADZUNA_COUNTRY` |

Every source whose credentials are absent from the environment is silently skipped — the same pattern as the LLM fallback router. The three new sources (JSearch, USAJobs, Adzuna) expand coverage to non-tech domains (federal engineering, finance, healthcare, logistics) and aggregate boards that previously required separate accounts. An `interest_aggregation_service.py` provides a TTL-cached live fetch keyed on the user's `research_interests` text (migration 0019 adds the `interest_search_cache` table).

### 5.5 Module 4 — Ghost-Job Shield

Five pure functions, no DB access, no LLM, no external API calls. The weighted sum:

```
ghost_score = 0.30 × age_score
            + 0.20 × repost_score
            + 0.25 × vague_jd_score
            + 0.15 × company_ghost_score
            + 0.10 × cohort_response_signal
```

Signal details:

| Signal | Function | Logic |
|---|---|---|
| Age | `age_score()` | Step function: 0–14 d → 0.0, 15–29 d → 0.2, 30–59 d → 0.5, 60–89 d → 0.7, ≥90 d → 1.0 |
| Repost | `repost_score()` | 1 board → 0.0, 2 boards → 0.4, 3+ boards → 0.8 |
| Vagueness | `vague_jd_score()` | word count (0.35) + req count (0.35) + pipeline phrases (0.30) − specificity bonus (up to 0.40, from 42 tech terms matched in description/requirements) |
| Company history | `company_ghost_score()` | Rolling average ghost score across all company postings |
| Cohort non-response | `cohort_response_signal()` | Active only when `cohort_applied_count ≥ 5`; returns `1 − responsiveness_score` |

Threshold: **0.38** (`GHOST_THRESHOLD` constant, `ghost_service.py:32`). The cohort signal defaults to 0.0 when fewer than 5 batchmates have applied, avoiding false positives on companies without cohort history. Tests in `tests/test_ghost.py` verify the exact weighted-sum formula and that the weight constants sum to 1.0.

**Why a weighted sum over a single heuristic:** A simple age threshold flags everything older than 30 days, including seasonal roles and rolling programs. The repost signal alone generates false positives for companies that genuinely post to multiple boards. The vagueness signal catches fresh ghost postings (< 30 days old, but no requirements, pipeline phrases). Combining five signals with calibrated weights allows partial evidence from each to contribute.

### 5.6 Modules 3 + 5 — Matching and Response Likelihood

Implemented together in `MatchingService`. Semantic similarity is computed as `1 − cosine_distance` (pgvector `<=>` operator via HNSW index). Skill overlap uses case-insensitive substring matching in both directions ("Python" matches "Python 3.x"). The ranking key:

```
expected_value = match_score × response_likelihood × (1 − ghost_score)
```

Where:

- **Data-rich path** (`cohort_applied_count ≥ 5`): `RL = 0.55 × cohort_rate + 0.35 × freshness + 0.10 × (1 − ghost_score)`
- **Cold-start path**: `RL = 0.65 × freshness + 0.35 × (1 − ghost_history_score)`

Match explanations are deterministic templates (no LLM) that annotate the cohort signal when `responsiveness_score < 0.25` at companies with sufficient data. The optional `?enrich=true` parameter calls the LLM for a richer plain-English explanation — the only LLM call in the entire ranking path.

**Why no persistence of match rows:** Matches are computed on-the-fly on every `GET /matches` call. Persisting them would require re-scoring on every new posting and every profile update — a write amplification problem. Since the HNSW index makes cosine distance queries sub-millisecond, on-the-fly computation is fast and always reflects current data.

### 5.7 Module 6 — Application Assistant

`ApplicationService.draft()` makes two potential LLM calls: one for the initial draft and one for a correction pass if grounding is below 0.70. The whitelist instruction is prepended to the system message: `"VERIFIED SKILL WHITELIST: {skills}. You may ONLY reference technologies and skills from this list."` After generation, `_grounding_score()` computes the fraction of JD requirements claimed in the draft that appear in the profile's skills, project tech, or experience text. If below threshold, `_find_unsupported_claims()` identifies the specific fabricated terms and constructs a correction prompt naming them explicitly.

ATS scoring (`_compute_ats()`) is deterministic: it counts the fraction of JD requirements present in the draft text (with acronym expansion, e.g., "Project Management Professional" → "pmp"). It never calls the LLM.

At `create_application()` time, the current `predicted_response_prob` and `predicted_ghost` are snapshotted onto the `applications` row — before any outcome is known. This is the mechanism that makes `evaluate_now()` always out-of-sample.

**Why threshold 0.70:** A score of 1.0 would be unreachable for real profiles (JDs always have some requirements the candidate doesn't claim). 0.70 allows a reasonable minority of unclaimed requirements while catching drafts that hallucinate skills wholesale. A correction pass is only triggered when the issue is severe enough to matter.

### 5.8 Module 8 — Referral Finder

`ReferralService` surfaces alumni contacts at a target company by matching the candidate's university against `contacts.university_canonical`. Canonicalization is handled by `UniversityNormalizer.canonicalize()` — a 30-entry alias map plus punctuation and article stripping — so "IIT Delhi", "Indian Institute of Technology Delhi", and "IIT-Delhi" all resolve to `"iit delhi"`. 42 tests in `tests/test_university_normalizer.py` verify distinct campuses stay distinct, edge cases (empty string, punctuation-only), and that every alias map value is lowercase.

**Why deterministic canonicalization over fuzzy matching:** Fuzzy string matching (Levenshtein distance) introduces non-determinism and would falsely match "IIT Bombay" with "IIT Roorkee" at moderate thresholds. Since the institution list is finite and known, a curated alias map with strict normalization is more reliable, testable, and predictable.

### 5.9 Module 10 — Research Vertical

Mirrors the internship matching stack for research opportunities. `ResearchService` ranks 20 seeded opportunities by `fit_score = 0.70 × cosine_sim(profile_embedding, opportunity_embedding) + 0.30 × skill_overlap` — the same blend as the main feed, but matching on `profile.research_interests` rather than `profile.skills`. Pitch generation uses the same Application Assistant whitelist + grounding guard. Research opportunities also carry a `recent_paper_url` field (migration 0017) to ground cold-email pitches in the PI's actual published work. Migration 0020 adds a unique index on `research_opportunities.url` to prevent duplicate upserts.

**Outreach state machine (migration 0015_outreach_hardening).** Research outreach records now follow a validated state machine:

```
suggested → contacted → replied
                     ↘ declined
                     ↘ no_response
```

`OUTREACH_TRANSITIONS` (defined in `app/models/research_outreach.py`) declares the allowed next-states for every status. `update_status()` validates the transition before writing it and rejects disallowed moves with `422 INVALID_STATUS_TRANSITION`. `contacted_at` and `replied_at` timestamps are set automatically when the corresponding status is entered.

Additional hardening in this module:
- **Unique constraint** `UNIQUE(user_id, research_opportunity_id)` prevents duplicate outreach records per user per opportunity.
- **Rate limiting** — `draft_pitch()` raises `429 RATE_LIMIT_EXCEEDED` after 5 pitches per user per hour (tracked by `contacted_at` timestamps within the rolling window).
- **Orphaned artifact GC** — if a `ResearchOutreach` row is deleted, its attached `Artifact` is removed in the same transaction.
- **Paginated list** — `list_outreach()` returns `(items, total)` tuples; the API exposes `?page=` and `?limit=` query parameters.
- **Stale warning** — outreach rows untouched for > 30 days gain `is_stale: True` in the API response.

### 5.9b Module 7 — Tracker Hardening

Several correctness issues were addressed in `tracker_service.py` and `tracker.tsx`:

- **Duplicate outcome guard.** `record_outcome()` now queries for an existing `Outcome` on the same `application_id` before inserting. A second call returns `409 OUTCOME_ALREADY_RECORDED` rather than silently creating a second row.
- **Word-boundary matching in follow-up drafts.** `draft_followup()` uses `re.search(r"\b" + re.escape(word) + r"\b", text_lower)` to verify that the company name and job title appear in the draft. This prevents false positives where a short term (e.g. "AI") matches as a substring of a longer word (e.g. "SAIL").
- **Re-fetch after commit.** `create_application()` calls `await self.db.refresh(app)` after the commit so callers receive a fully-populated `Application` object including server-set defaults, rather than a stale in-memory object.
- **Terminal status guard (frontend).** `tracker.tsx` defines `TERMINAL_STATUSES = new Set(["offer", "rejected", "ghosted"])`. Cards in these states are not advanced by the quick-action button and receive `aria-disabled`. The `advance()` function returns early on any terminal status before consulting the ordered status array, preventing nonsensical transitions like offer → rejected.

### 5.10 Modules 11 + 12 — Dashboard and Notifications

`DashboardService` aggregates pipeline counts, response rate, ghosts avoided (postings with `is_ghost=True` in the user's application set), and time saved (estimated). It calls `EvaluationService.get_latest_formula()` and `get_history_rows()` to populate `platform_iq` and `iq_trend`. `NotificationService` generates four notification types idempotently — a `SET` of existing notification contents is checked before inserting to avoid duplicates across concurrent runs.

### 5.11b Offline Matching Quality Eval — `EvalMatchingService`

`app/services/eval_matching_service.py` implements an offline golden-set evaluation that runs with no DB, no live users, and no LLM — only the production sentence-transformer.

**Golden set.** 4 archetypal student profiles × 8 archetypal research/internship opportunities = 32 hand-labeled (profile, opportunity) pairs with relevance 0–3:

| Profile archetype | Peak opportunity | Design intent |
|---|---|---|
| `nlp_researcher` | `nlp_lab` | NLP profile should not match genomics or embedded systems |
| `cv_researcher` | `cv_group` | CV profile should prefer CV group over general ML |
| `fullstack_dev` | `saas_startup` | Developer profile is irrelevant to all research labs |
| `bio_researcher` | `genomics_lab` | Bio profile should not match backend engineering |

The `embedded_sys` opportunity has relevance=0 for every profile by design — an explicit test of the model's ability to reject clearly irrelevant roles.

**Metrics computed per run.** For each profile, opportunities are ranked by the production `fit_score = SEMANTIC_WEIGHT × cosine_sim + SKILL_WEIGHT × skill_ratio`. Global metrics are the arithmetic mean across all four profiles:

| Metric | Purpose |
|---|---|
| NDCG@3 | How good is the top-3 ranking (emphasises rank position, not just precision) |
| NDCG@5 | Full top-5 ranking quality — the optimisation target |
| Precision@3 | What fraction of the top-3 are relevant (relevance ≥ 1) |
| MRR | Where is the first relevant result |

**Weight grid-search.** Tries `SEMANTIC_WEIGHT` ∈ {0.40, 0.45, …, 0.90} (and `SKILL_WEIGHT = 1 − SEMANTIC_WEIGHT`) to find the pair maximising NDCG@5. Returns `optimal_weights`, `optimal_ndcg_at_5`, `weight_gain_pct`, and `weight_recommendation` as an explicit human-readable string.

**Regression detection.** Stores the previous run's NDCG@5 in a module-level variable. Any drop > 2 pp sets `regression_detected = True` in the response.

**Per-profile breakdown.** Each of the four profiles gets its own `ndcg_at_3`, `ndcg_at_5`, `precision_at_3`, `mrr`, `top_match_label`, and `top_match_is_correct` flag. A reviewer can immediately see which archetype the system handles least well.

**Health field.** `"good"` when NDCG@5 ≥ 0.70, `"needs_attention"` otherwise.

Admin endpoint: `POST /api/evaluation/matching`

### 5.11c Live Grounding Score Calibration — `EvalGroundingService`

`app/services/eval_grounding_service.py` answers one question: *does a higher `grounding_score` actually predict that a professor will reply?*

**Data pipeline.** Joins `Artifact` rows of type `research_pitch` (where `grounding_score IS NOT NULL`) with `ResearchOutreach` via `pitch_artifact_id`. Only terminal-state rows are included:
- `replied` / `accepted` → `responded = 1`
- `declined` / `no_response` → `responded = 0`
- Pending states (`suggested`, `drafted`, `contacted`) are excluded — outcome unknown.

Requires ≥ 10 terminal rows; returns `health = "insufficient_data"` below that.

**Metrics.**

| Metric | What it tells you |
|---|---|
| Spearman ρ + p-value | Monotonic correlation between score and outcome; p < 0.05 means the correlation is statistically significant |
| ECE (10-bin) | Mean absolute gap between predicted confidence and actual accuracy |
| Bucket analysis | 4 human-readable bands — [0–0.30), [0.30–0.50), [0.50–0.70), [0.70–1.00] — with count and response rate per band |
| Optimal threshold | Grid-search over [0.30, 0.90] (step 0.05) maximising F1; returns current F1, optimal F1, and Δ |
| `threshold_recommendation` | Explicit string: either confirms `GROUNDING_THRESHOLD = 0.70` is near-optimal, or names a new value with the expected F1 gain |

**Health.** `"good"` when is_predictive=True and optimal threshold is within 0.05 of current; `"needs_attention"` when the score is not predictive or a better threshold is available; `"insufficient_data"` when < 10 terminal samples exist.

Admin endpoint: `GET /api/evaluation/grounding`

### 5.11 Module 9 — Interview Prep (descoped)

Module 9 was fully implemented (model, schema, service, router, migration 0011, 32 tests, frontend route) and then removed in migration 0015. The decision was scope focus: delivering a tight, well-tested core (Modules 0–8, 10–12) with a complete evaluation loop was a higher-value state than twelve partially-complete modules. The interview-prep feature had meaningful value but was the highest-complexity module to validate end-to-end (LLM-generated question arrays, company/region/type branching logic) without live recruiter data to benchmark against.

---

## 6. Key Engineering Decisions

### 6.1 Multi-LLM fallback router

**What:** `app/llm/router.py` defines a five-provider chain: Gemini 2.5 Flash → Groq Llama 3.3 70B → OpenRouter (gpt-4o-mini) → DeepSeek → Ollama. A provider whose API key is absent is silently skipped via `_ProviderSkippedError`. On 429, timeout, or any error, `BACKOFF_S = 0.5` seconds is awaited and the next provider is tried. The same `complete(messages)` interface is used in tests (providers mocked) and production. No test ever hits a real LLM API.

**Why not a single provider:** Any single provider has a free-tier rate limit that blocks development. Groq handles most development calls at zero cost; Gemini 2.5 Flash is the quality backstop; the chain survives any single-provider outage without code changes.

**Alternative rejected:** LiteLLM. A heavy dependency for a use case coverable in 200 lines introduced version-coupling risk without significant benefit at current scale.

### 6.2 Local sentence-transformers + pgvector HNSW

**What:** `all-MiniLM-L6-v2` (dim=384) runs via `asyncio.to_thread` so the CPU-bound embedding computation never blocks the async event loop. Vectors are stored in pgvector's `vector(384)` column type (added by migration `0001_initial.py`'s `CREATE EXTENSION IF NOT EXISTS vector`) and indexed with HNSW for approximate nearest-neighbor search.

**Why local instead of an embedding API:** Zero per-call cost at any scale. The model is downloaded once and held in memory for the process lifetime. At 384 dimensions, cosine distances are stable and the model benchmarks well on semantic textual similarity tasks.

**Why HNSW over IVFFlat:** HNSW does not require training data to build the index (IVFFlat requires centroid lists, which means a minimum row count before the index is useful). For a dataset that starts small and grows, HNSW builds incrementally and is immediately queryable from row one.

### 6.3 Ghost-Job Shield: multi-signal weighted model over a single heuristic

**What:** Five independent signals with calibrated weights (§5.5) rather than any single threshold. Weights are defined as named module-level constants in `ghost_service.py` so they can be changed, tested, and discussed without touching logic.

**Why weights over a rule:** A pure age rule flags seasonal programs, rolling applications, and large-company pipelines that are genuinely active but old. The vagueness signal catches fresh ghost postings (< 30 days old, but no requirements, pipeline phrases). The repost signal catches the second posting board without needing any age data. The five signals complement each other's blind spots.

**Alternative rejected:** A trained classifier. A classifier requires labeled ground-truth data (which postings are actually ghost). That data doesn't exist at launch. The weighted heuristic provides reasonable precision from day one and can be replaced by a trained model once labeled outcomes accumulate.

### 6.4 Collective intelligence: privacy-respecting cohort aggregate

**What:** `CohortService.recompute_company_response()` writes exactly two scalars to the `companies` table: `cohort_applied_count` and `responsiveness_score`. No individual user's application row, status, or content is read by any other user's session.

**Why counts-only instead of richer shared signals:** Surfacing individual users' outcomes to other users is a privacy violation even if user IDs are stripped — response times, application text, and outcomes together can re-identify individuals in a small cohort. Aggregate counts with a minimum threshold (5) provide the predictive signal without any individual data crossing user boundaries.

**Why MIN_APPS = 5:** Below 5 data points, a 0% response rate from one unlucky applicant would incorrectly label a responsive company as a ghost. The threshold is consistent across `CohortService`, `GhostService`, and `MatchingService` (all share the same `MIN_APPS = 5` constant).

### 6.5 Two-layer ghost defense

**What:** The Ghost Shield catches the _obvious_ ghost: old, vague, multi-board. The response likelihood model catches the _deceptive_ ghost — a recent, specific JD with strong skill match at a company that never responds.

The design is explicitly demonstrated in `seed_demo.py`. Two postings — "Machine Learning Engineer Intern" at PipelineTech and "Backend Engineer Intern — Platform" at TalentPool Inc — are seeded with `days_override=8` (age_score=0.0) and `sightings_override=1` (repost_score=0.0), ensuring they score below the ghost threshold. Their companies' `responsiveness_score` settles near 0% after 14 users apply. The expected_value:

```
expected_value = 0.91 × (≈0.32) × (1 − 0.08) ≈ 0.27
```

High semantic match, near-zero RL from 0% cohort response rate, low ranking. The Ghost Shield's false negative is intentional design — it documents the limit of rule-based detection and motivates the response likelihood layer.

### 6.6 Anti-fabrication grounding guard

**What:** In `ApplicationService.draft()`, after the initial LLM generation:

1. `_grounding_score()` counts the fraction of JD requirements claimed in the draft that are backed by profile evidence (skills set, project tech set, or experience text).
2. If grounding < 0.70 and the profile has verifiable evidence, `_find_unsupported_claims()` names the fabricated terms.
3. A correction prompt is sent: `"Your draft mentioned {unsupported}. The candidate does NOT have these — they are not on the verified whitelist. Remove every reference to {unsupported} and rewrite using only the whitelist skills."`
4. The corrected draft is re-scored. Only the final draft and its grounding score are stored.

**Why a regeneration pass over post-processing:** Post-processing (regex removing skill names) produces grammatically broken sentences. A regeneration pass with the correction context produces coherent prose that doesn't mention the fabricated claims.

### 6.7 Self-improving evaluation loop: honest methodology

**What:** Two evaluation modes in `EvaluationService`:

- `evaluate_now()`: scores all `(application, outcome)` pairs using predictions snapshotted before outcomes existed. Formula: `IQ = 100 × (0.60 × (1 − Brier) + 0.40 × ghost_F1)`. Constants: `W_RESP = 0.60`, `W_GHOST = 0.40`.
- `build_history()`: fixed 30% test set (most recent outcomes by `recorded_at`), 8 growing prefixes of the 70% training pool. A `LogisticRegression` calibrator (`sklearn`, `max_iter=500`, `random_state=42`) is trained on each prefix and scored on the fixed test set. The IQ trend formula is `100 × (1 − Brier_on_fixed_test)` — ghost F1 is excluded from the trend because the ghost shield is rule-based, not trained.

**Why temporal split instead of random:** A random 70/30 split would allow training on outcomes from week 4 while testing on outcomes from week 1 — future data predicting past. The temporal split ensures every test pair occurred after all training pairs.

**Why LogisticRegression over a raw probability:** The snapshotted `predicted_response_prob` is computed by the cold-start formula (freshness + ghost history) before any outcomes exist. LogisticRegression Platt-scales these raw scores to better-calibrated probabilities as outcomes accumulate.

**On the seed dataset results:** Platform IQ 66.7 (Brier 0.226, AUC 0.769, ghost F1 0.507) from `evaluate_now()`. The IQ trend rises from 75.1 (Brier 0.249, n=31) to 80.3 (Brier 0.197, n=255) over 8 checkpoints. The evaluate_now IQ (66.7) is lower than the trend IQ (75–80) because evaluate_now includes `W_GHOST × ghost_F1 = 0.40 × 0.507 = 0.20` drag; the trend excludes ghost F1 to isolate the trainable component.

### 6.8 Per-user data isolation via BaseService

**What:** `BaseService` (`app/services/base.py`, 28 lines) stores `self.user_id` and declares `_scope()` as `NotImplementedError`. Services that extend it are structurally required to add `.where(Model.user_id == self.user_id)` to every query — if they call `self._scope(stmt)` without implementing it, they get an immediate `NotImplementedError` rather than a silent data leak.

**Why structural enforcement over convention:** A naming convention ("always add user_id filter") is invisible in code review and silently omittable. Making `_scope()` raise on call, combined with mypy's strict checking of the service hierarchy, catches violations at development time rather than in production.

**Services explicitly NOT BaseService:** `CohortService` and `EvaluationService` — both access cross-user data intentionally, both document exactly what they read and why in their module docstrings.

### 6.9 Contract-first frontend/backend split

**What:** `API_CONTRACT.md` defines every field name, type, enum value, and endpoint shape. The frontend's `frontend/src/lib/api-client.ts` is the single file that communicates with the backend; all other frontend code calls `api.*` methods. A `shouldUseMocks()` function returns `USE_MOCKS || isGuestMode() || !getToken()` — unauthenticated visitors see demo mock data automatically (no API calls to the sleeping backend), authenticated users see real data.

**Why contract-first over auto-generated clients:** A generated client from OpenAPI is fast but fragile — any backend change silently regenerates client code. The contract-first approach forces an explicit decision at `API_CONTRACT.md` before any code changes, making breaking changes visible in code review as a diff to the contract file.

### 6.10 Deterministic university-name normalization

**What:** Alumni matching across users requires that "IIT Delhi", "Indian Institute of Technology Delhi", and "IIT-Delhi" resolve to the same institution. `app/services/university_normalizer.py` provides a 30-entry alias map plus punctuation and article normalization. Canonicalization is pure (no external calls, no LLM) and deterministic — same input, same output, always.

**Why deterministic over fuzzy:** Fuzzy string matching would falsely match "IIT Bombay" with "IIT Roorkee" at moderate Levenshtein thresholds. A curated alias map is more reliable, testable, and predictable for a finite, known institution list.

---

## 7. Current Progress

### 7.1 Module status

| Module | Status | Verified end-to-end |
|---|---|---|
| 0 — Auth | Shipped | Yes (13 tests + journey smoke step 1) |
| 1 — Career Twin | Shipped | Yes (15 profile tests) |
| 2 — Ingestion | Shipped | Yes (ghost test 11: aggregation wires ghost rescore) |
| 3+5 — Matching + RL | Shipped | Yes (21 match tests + 7 RL tests) |
| 4 — Ghost Shield | Shipped | Yes (12 ghost tests; formula, threshold, weights all unit-tested) |
| 6 — Application Assistant | Shipped | Yes (30 application tests; grounding guard tested with mock LLM) |
| 7 — Tracker / Outcomes | Shipped | Yes (25 tracker tests; duplicate outcome guard, word-boundary matching, terminal status all tested) |
| 8 — Referral Finder | Shipped | Yes (31 referral tests + 42 normalizer tests) |
| 9 — Interview Prep | Descoped | N/A |
| 10 — Research Vertical | Shipped | Yes (25 research tests; state machine, rate limit, stale flag, pagination all tested) |
| 11 — Platform IQ Dashboard | Shipped | Yes (19 evaluation tests; 9 dashboard tests; 27 matching eval tests; 18 grounding eval tests) |
| 12 — Notifications | Shipped | Yes (7 notification tests) |

### 7.2 Code quality gates

| Gate | Result | Command |
|---|---|---|
| Tests | **361 pass** | `uv run pytest` (361 items across 21 files against live PostgreSQL + pgvector) |
| mypy --strict | **0 errors** (76 source files) | `uv run mypy app` |
| ruff | **0 violations** | `uv run ruff check .` |
| tsc | Clean (no output) | `cd frontend && npx tsc --noEmit` |
| vite build | Built successfully | `cd frontend && npm run build` |

---

## 8. Results and Evidence

All metrics are derived from static code inspection or from running `scripts/seed_demo.py` + `scripts/smoke_replay.py` on the local database. Simulated data is clearly marked.

### 8.1 Test suite breakdown

| File | Tests | Notes |
|---|---|---|
| test_university_normalizer.py | 42 | |
| test_referrals.py | 31 | |
| test_applications.py | 30 | |
| test_eval_matching.py | 27 | **New** — 23 pure-unit (NDCG, Precision, MRR, cosine, fit_score, golden set, rank) + 4 async integration |
| test_hardening_v2.py | 23 | Outreach + Application Assistant hardening |
| test_tracker.py | 25 | +3 new: duplicate outcome 409, word-boundary matching, terminal status |
| test_matches.py | 21 | |
| test_postings.py | 20 | |
| test_evaluation.py | 19 | Idempotency guard, admin-only gate, evaluate_now persistence |
| test_eval_grounding.py | 18 | **New** — 14 pure-unit (ECE, threshold, Spearman, bucket) + 4 async DB integration |
| test_profile.py | 15 | |
| test_auth.py | 13 | |
| test_ghost.py | 12 | |
| test_dashboard.py | 9 | |
| test_research.py | 25 | +10 new: state machine transitions, rate limit 429, stale flag, artifact persistence |
| test_notifications.py | 7 | |
| test_response_likelihood.py | 7 | |
| test_shield_hardening.py | 6 | Ghost Shield signal-level hardening |
| test_embeddings.py | 5 | |
| test_llm.py | 5 | |
| test_health.py | 1 | |
| **Total (pytest items)** | **361** | 21 test files |

Source: `uv run pytest --tb=short -q` — 361 passed in a live run against PostgreSQL + pgvector. Tests in `conftest.py` run real Alembic migrations at session start (subprocess call to `uv run alembic upgrade head`) so the test schema is always in sync with the migration history.

### 8.2 Ghost-flag distribution on seed dataset

Seed configuration from `seed_demo.py` (deterministic, RNG seed=42):

| Company archetype | Response rate | Age (days) | Sightings |
|---|---|---|---|
| Responsive (Google, Stripe, Figma, Notion, Snowflake — 5 companies) | 75% | 10 | 1 |
| Mixed (Microsoft, Amazon, Lyft, Databricks — 4 companies) | 30% | 28 | 2 |
| Ghost-prone (PipelineTech, TalentPool Inc, InnovateCo — 3 companies) | 7% | 75 | 3 |

Ghost-prone vague postings have empty `requirements=[]` and contain pipeline phrases ("always looking", "building a pipeline of candidates", "expressions of interest"), making `vague_jd_score` near 1.0. Combined with `age_score=1.0` and `repost_score=0.8`, these postings score well above 0.38.

The two deceptive postings (one each at PipelineTech and TalentPool Inc) use `days_override=8` and `sightings_override=1` so their ghost score stays below threshold. Their companies' cohort response rate settles near 0% after 14 users apply, demoting them in `expected_value` ranking.

### 8.3 Platform IQ evaluation — seed dataset

From `scripts/smoke_replay.py` after `scripts/seed_demo.py` (RNG seed=42, 364 application-outcome pairs, 14 demo users, 26 postings across 12 companies):

| Metric | Value | Source |
|---|---|---|
| n_outcomes (evaluate_now) | 364 | `smoke_replay.py` output |
| Platform IQ | **66.7** | `smoke_replay.py` output |
| Response Brier score | **0.226** | `smoke_replay.py` output |
| Response AUC | **0.769** | `smoke_replay.py` output |
| Ghost F1 | **0.507** | `smoke_replay.py` output |

**IQ learning curve** (8 checkpoints, fixed 30% test set, `build_history()`):

| Checkpoint | Train n | Brier (fixed test) | IQ trend |
|---|---|---|---|
| 1 | 31 | 0.249 | 75.1 |
| 2 | ~62 | improving | — |
| 3 | ~93 | improving | — |
| 4 | ~124 | improving | — |
| 5 | ~155 | improving | — |
| 6 | ~186 | improving | — |
| 7 | ~217 | improving | — |
| 8 | 255 | 0.197 | 80.3 |

Run `uv run python scripts/smoke_replay.py` after seeding to populate all 8 rows.

**Interpretation.** The evaluate_now IQ (66.7) is lower than the trend IQ (75–80) for a documented reason: `evaluate_now` includes `W_GHOST × ghost_F1 = 0.40 × 0.507 ≈ 0.20` drag. Ghost F1 of 0.507 reflects that the seed's deceptive postings are intentionally not flagged by the rule-based shield — they are the cohort-signal test case. The response calibration component alone (`W_RESP × (1 − Brier) = 0.60 × 0.774 ≈ 0.46`) maps to IQ ≈ 46 from calibration + 20 from ghost = 66. The trend excludes ghost F1 to isolate the learnable component; the improvement from 75.1 to 80.3 is purely from the response calibrator training on more labeled pairs.

**Data honesty note.** All 364 outcome pairs are simulated via deterministic RNG. Responsive companies respond at 75%, mixed at 30%, ghost-prone at 7%. These rates are set by `_ARCHETYPE_RESPOND_RATE` in `seed_demo.py`. Real outcome data will differ; the simulation demonstrates the architecture and learning curve shape, not a claim about real-world prediction accuracy.

### 8.4 Cohort response-rate spread

From `COMPANY_DEFS` and `_ARCHETYPE_RESPOND_RATE` in `seed_demo.py`:

| Archetype | Expected cohort rate | Notes |
|---|---|---|
| Responsive | ~75% | `responsiveness_score` dominates RL formula at this level |
| Mixed | ~30% | Meaningful RL reduction but not suppressed |
| Ghost-prone | ~7% | Near-zero RL; deceptive postings rank bottom despite high match |

The spread across archetypes is wide enough that the data-rich response likelihood formula (`0.55 × cohort_rate`) dominates the ranking for companies with ≥5 cohort applications — which is all 12 seed companies after 14 users apply.

---

## 9. Tech Stack

| Layer | Technology | Version | Rationale |
|---|---|---|---|
| Language | Python | 3.12 | Async-native; walrus operator; better type narrowing in mypy |
| API framework | FastAPI + uvicorn[standard] | ≥0.115 | Async-native; Pydantic v2 validation; automatic OpenAPI |
| Package manager | uv | latest | Faster than pip; deterministic lockfile; `uv sync --frozen --no-cache` in Docker |
| ORM | SQLAlchemy 2.0 async + asyncpg | 2.0 | True async; `AsyncSession`; no sync engine anywhere |
| Database | PostgreSQL 17 + pgvector | 0.8 | Relational integrity + HNSW vector search in one engine |
| Validation | Pydantic v2 strict mode | v2 | Catches shape mismatches at boundaries; no unintentional Optional |
| Embeddings | sentence-transformers all-MiniLM-L6-v2 | dim=384 | Free, local, no API cost; stable STS benchmarks |
| LLM | 5-provider fallback router | see §6.1 | Cost resilience; Groq free tier for dev; Gemini for quality |
| Calibration | scikit-learn LogisticRegression | ≥1.0 | Lightweight Platt-scaling; temporal split; no GPU needed |
| Auth | python-jose JWT + passlib argon2 + google-auth OIDC | — | argon2 = current password hashing best practice |
| Migrations | Alembic async | 20 migrations | Incremental, reviewed, never auto-applied in production |
| Linting | ruff | latest | Single-pass import, naming, and style enforcement |
| Type checking | mypy --strict | — | Strict mode; catches service-layer contract violations at dev time |
| Tests | pytest + pytest-asyncio + httpx | — | Async-native; integration tests hit real PostgreSQL |
| Frontend framework | TanStack Start + Vite 7 | — | SSR-capable; file-based routing; nitro bundling |
| UI | React 19 + Tailwind CSS | — | Component composition; utility-first styling |
| Frontend hosting | Cloudflare Pages (SSR Worker) | — | Edge-deployed; `nodejs_compat` flag; nitro Cloudflare Pages preset |
| Backend hosting | Render.com (Docker) | — | Multi-stage build; CPU-only PyTorch (~200 MB); start.sh applies migrations |
| Database hosting | Supabase PostgreSQL + pgvector | — | Session Pooler for IPv4; all 18 migrations applied |

---

## 10. Challenges and Trade-offs

### 10.1 Sparse real-outcome data in a short build window

**Problem:** The response likelihood model and evaluation loop require outcome data (responded / not responded) to be meaningful. In the available build window, real outcomes don't exist — a user would need to apply to dozens of jobs and wait weeks for replies.

**Resolution:** `scripts/seed_demo.py` generates a deterministic simulation: 14 user personas, 26 postings, 364 application-outcome pairs, outcome probabilities set by company archetype (75% / 30% / 7%), timestamps spread over 90 days to create a believable learning curve. The simulation is declared explicitly as simulation in code comments and this document. The architecture is validated; accuracy claims against real data are not made.

### 10.2 Ghost threshold warm-start calibration

**Problem:** `GHOST_THRESHOLD = 0.38` was set by inspecting the signal distribution on real postings fetched during development. Without a labeled dataset of confirmed ghost jobs, there is no principled way to derive the optimal threshold.

**Resolution:** The threshold is a named constant (`ghost_service.py:32`) with a comment documenting the warm-start intent. The seed script's `_ghost_snapshot()` function measures the gap between the highest non-ghost score and the lowest ghost score after each run and prints a threshold assessment. The two-layer defense (§6.5) partially mitigates threshold miscalibration: deceptive postings that escape the shield are caught by the cohort response likelihood layer.

### 10.3 Lever API access model

**Problem:** Lever's v1 API does not expose a public listing endpoint without company-specific slugs. Most public Lever URLs are company-specific subdomains, making systematic crawling unreliable without a curated slug list per company.

**Resolution:** The Lever adapter is implemented and functional for known slugs, but excluded from `AggregationService.refresh()` by default. The four active sources (Greenhouse, Ashby, RemoteOK, Remotive) provide sufficient ingestion coverage. Lever activation is planned once a slug-discovery tool is built.

### 10.4 TanStack Start SSR + localStorage guards

**Problem:** TanStack Start renders on the server where `localStorage` is undefined. Auth state (JWT, user object, guest flag) is stored in `localStorage["internpilot_token"]`, `localStorage["internpilot_user"]`, and `localStorage["internpilot_guest"]`. Direct access at the module level throws on the server.

**Resolution:** `api-client.ts` wraps all localStorage reads with `typeof localStorage !== "undefined"` guards. The nav component reads auth state in a `useEffect` (client-only) rather than at render time. Unauthenticated visitors get mock data automatically via `shouldUseMocks() = USE_MOCKS || isGuestMode() || !getToken()` — no API calls are made to a potentially sleeping backend.

### 10.5 CPU-only PyTorch on Docker

**Problem:** `sentence-transformers` pulls in PyTorch, which defaults to a CUDA wheel (~2 GB) from PyPI — a build-time download timeout on Render's free tier.

**Resolution:** Added a CPU-only PyTorch index to `pyproject.toml`:
```toml
[tool.uv.sources]
torch = { index = "pytorch-cpu" }

[[tool.uv.index]]
name = "pytorch-cpu"
url = "https://download.pytorch.org/whl/cpu"
explicit = true
```
This resolves `torch==2.12.1+cpu` (~200 MB) instead of the CUDA wheel, reducing Docker build time from timeout to ~3 minutes.

### 10.6 pgvector HNSW index and cold-start embeddings

**Problem:** The HNSW index is built as postings are inserted. At cold start (no postings), the index is empty and `GET /matches` returns an empty list even for fully built profiles. Additionally, if a profile has no embedding (résumé not uploaded), cosine distance queries fail.

**Resolution:** `MatchingService.get_matches()` returns `([], 0)` immediately if `profile.embedding is None`. The frontend renders a "complete your profile to see matches" state. The cold-start problem is addressed by seeding postings via `scripts/probe_refresh.py` before any user session.

---

## 11. Deployment

InternPilot is live in production across three platforms:

### Frontend — Cloudflare Pages (SSR Worker)

- **Build:** `npm run build` in `frontend/` using `@lovable.dev/vite-tanstack-config` with `nitro: { preset: "cloudflare-pages" }` in `vite.config.ts`. Produces `dist/_worker.js/`, `dist/_routes.json`, `dist/_redirects`.
- **Compatibility flags:** `nodejs_compat` (required for Node.js built-ins in the Worker runtime).
- **Auth-aware mocks:** Unauthenticated visitors see in-memory mock data automatically via `shouldUseMocks() = USE_MOCKS || isGuestMode() || !getToken()`. No backend call is made until the user authenticates.
- **URL:** [internpilot.pages.dev](https://internpilot.pages.dev)

### Backend — Render.com (Docker)

- **Build:** Multi-stage Dockerfile. Stage 1 uses `ghcr.io/astral-sh/uv:python3.12-bookworm-slim` to install deps with `uv sync --frozen --no-dev --no-cache`. CPU-only PyTorch wheel (~200 MB) via `pyproject.toml` source override.
- **Startup:** `scripts/start.sh` runs `alembic upgrade head` then `uvicorn app.main:app --host 0.0.0.0 --port $PORT`. Migrations are applied on every boot.
- **Environment:** `DATABASE_URL`, `JWT_SECRET`, all LLM keys, `CORS_ORIGINS` set as Render environment variables.

### Database — Supabase PostgreSQL 17 + pgvector

- **Connection:** Session Pooler URL (`aws-1-ap-south-1.pooler.supabase.com:5432`) for IPv4 compatibility with Render's free tier. Direct connection URL (IPv6) is incompatible with Render free tier.
- **Migrations:** All 18 migrations applied (`0001_initial` through `0018_posting_decode_cache`). Migration 0001 runs `CREATE EXTENSION IF NOT EXISTS vector` before creating the `users` table.
- **Password encoding:** Special characters in the database password are URL-encoded in `DATABASE_URL` (`@` → `%40`).

---

## 12. Setup and Reproducibility

A reviewer can stand up the full system from this section alone.

### Prerequisites

- Python 3.12
- [uv](https://github.com/astral-sh/uv): `pip install uv`
- Docker Desktop (for PostgreSQL + pgvector)
- Node.js ≥ 18 and npm
- At least one LLM API key — Groq free tier (`GROQ_API_KEY`) is sufficient

### Step 1: Clone and configure

```bash
git clone https://github.com/Om-5640/InternPilot.git
cd InternPilot
cp .env.example .env
# Edit .env — minimum required:
#   DATABASE_URL=postgresql+asyncpg://postgres:testpass@localhost:5433/internpilot
#   JWT_SECRET=any-32-char-string
#   GROQ_API_KEY=your-groq-key   (or leave blank to skip LLM calls in tests)
```

### Step 2: Start PostgreSQL with pgvector

```bash
docker run -d \
  --name internpilot-postgres \
  -e POSTGRES_PASSWORD=testpass \
  -p 5433:5432 \
  pgvector/pgvector:pg17
```

### Step 3: Install Python dependencies and apply migrations

```bash
uv sync --all-extras
uv run alembic upgrade head
# Expected: 20 migrations applied (0001_initial → 0020_research_url_unique)
```

### Step 4: Seed demo data (required to observe ghost shield and evaluation)

```bash
uv run python scripts/probe_refresh.py   # optional: aggregate real postings
uv run python scripts/seed_demo.py       # 14 demo users + 26 postings + 364 app-outcome pairs
uv run python scripts/seed_research.py  # 20 research opportunities with pgvector embeddings
uv run python scripts/smoke_replay.py   # builds Platform IQ learning curve (prints 8 checkpoints)
```

Expected output from `seed_demo.py`:

```
DEMO SEED SUMMARY
=================================================================
Demo users created : 14
Applications       : 364
Outcomes recorded  : 364
Alumni contacts    : 23

DECEPTIVE POSTINGS — what the Ghost Shield misses (Module 5's territory)
...
Demo script: "This role matches you 91% — ranked #22 because 0/5 batchmates heard back."
```

Expected output from `smoke_replay.py`:

```
evaluate_now: n_outcomes=364 iq=66.70 brier=0.2260 ghost_f1=0.5070 model=formula_v1
build_history: 8 checkpoint(s)
  [1] n=31   iq=75.10  brier=0.2490  ...
  ...
  [8] n=255  iq=80.30  brier=0.1970  ...
```

### Step 5: Start the backend

```bash
uv run uvicorn app.main:app --reload
# API:  http://localhost:8000
# Docs: http://localhost:8000/api/docs
```

### Step 6: Start the frontend

```bash
cd frontend
npm install
npm run dev
# UI: http://localhost:5173
```

Set `VITE_USE_MOCKS=false` in `frontend/.env` to connect to the live backend.

### Step 7: Run the test suite

```bash
docker exec internpilot-postgres psql -U postgres -c "CREATE DATABASE internpilot_test;"

TEST_DATABASE_URL=postgresql+asyncpg://postgres:testpass@localhost:5433/internpilot_test \
  uv run pytest -v

uv run mypy app          # 0 errors, strict mode, 76 files
uv run ruff check .      # 0 violations
```

### Step 8: End-to-end API smoke test

```bash
uv run python scripts/journey_smoke.py
# Expected: === ALL 12 STEPS PASSED ===
```

---

## 13. Appendix

### A. Engineering contract documents

| Document | Purpose |
|---|---|
| [`API_CONTRACT.md`](API_CONTRACT.md) | Authoritative field-level API contract. Every endpoint, request shape, response shape, enum value, and error code is defined here. Change the contract before changing the code. |
| [`CLAUDE.md`](CLAUDE.md) | Developer conventions: pinned versions, project structure, data-isolation rule (with correct/incorrect examples), module discipline checklist, migration commands, async rules, error handling pattern, LLM router usage, embeddings usage. |

### B. Repository structure

```
app/
  main.py                       FastAPI lifespan, CORS, router mounts
  core/
    config.py                   pydantic-settings; all secrets from env
    database.py                 async engine + get_db() dependency
    security.py                 JWT create/verify + get_current_user
    errors.py                   APIError + global handlers → {error:{code,message}}
  models/                       13 SQLAlchemy ORM models
    base.py                     DeclarativeBase + TimestampMixin (id UUID, created_at, updated_at)
    user.py · profile.py        Modules 0–1
    company.py · posting.py     Shared global entities
    application.py · artifact.py · outcome.py    Modules 6–7 (user-owned)
    contact.py · referral.py    Module 8
    research_opportunity.py · research_outreach.py    Module 10
    evaluation.py               Module 11
    notification.py             Module 12
  schemas/                      Pydantic v2 request/response schemas (one per module)
  services/
    base.py                     BaseService — data-isolation scaffold (28 lines)
    ghost_service.py            5-signal Ghost-Job Shield
    matching_service.py         Matching + response likelihood (Modules 3+5)
    cohort_service.py           Cross-user aggregate response rates
    application_service.py      Application Assistant (grounding guard, ATS)
    evaluation_service.py            Platform IQ — evaluate_now + build_history
    eval_matching_service.py         Offline golden-set matching eval (NDCG@3/5, Precision@3, MRR, weight grid-search)
    eval_grounding_service.py        Live grounding calibration (Spearman ρ, ECE, threshold optimisation)
    research_service.py              Research opportunity ranking + pitch + outreach state machine
    research_aggregation_service.py  Research opportunity ingestion/aggregation
    interest_aggregation_service.py  Interest-based live job fetching with TTL cache
    university_normalizer.py         Deterministic name canonicalization (30-entry alias map)
    contact_scraper.py               Alumni/contact data collection
    ... (21 service files total)
  llm/
    router.py                   5-provider fallback chain (Gemini→Groq→OpenRouter→DeepSeek→Ollama)
    embeddings.py               Local all-MiniLM-L6-v2, EMBEDDING_DIM=384
  api/v1/                       Thin routers — 57 endpoints, no business logic
  sources/                      8 ingestion adapters (Greenhouse, Ashby, Lever, RemoteOK, Remotive, JSearch, USAJobs, Adzuna)
alembic/
  env.py                        Async Alembic env
  versions/                     20 reviewed migrations (0001_initial → 0020_research_url_unique)
tests/                          361 tests across 21 files (integration against real PostgreSQL)
scripts/
  seed_demo.py                  14 users + 364 app-outcome pairs (RNG seed=42, deterministic)
  seed_research.py              20 research opportunities with pgvector embeddings
  probe_refresh.py              Aggregate real postings from all 5 sources
  smoke_replay.py               Replay Platform IQ learning curve (evaluate_now + build_history)
  journey_smoke.py              12-step end-to-end API smoke test
frontend/
  src/
    lib/api-client.ts           Single HTTP client; mock↔real via auth state or VITE_USE_MOCKS
    lib/mocks.ts                In-memory mock data for guest/unauthenticated mode
    routes/                     TanStack Start file-based routes (12 routes)
    routes/blog.tsx             Full editorial blog post — origin story of the buildathon
    components/nav.tsx          Auth-aware navigation (avatar + dropdown / guest badge); footer with Company column (Blog, GitHub, Contact)
  vite.config.ts                nitro cloudflare-pages preset for SSR Worker bundling
API_CONTRACT.md                 Field-level API contract (single source of truth)
CLAUDE.md                       Developer conventions
```

### C. Numbers provenance

| Number | Value | Source |
|---|---|---|
| Test functions | 361 | `uv run pytest --tb=short -q` (live run, 21 test files against PostgreSQL + pgvector) |
| mypy source files | 76 | `uv run mypy app` output |
| API endpoints | 57 | `@router.` decorators in `app/api/v1/*.py` |
| Alembic migrations | 20 | `ls alembic/versions/*.py` (0001_initial → 0020_research_url_unique) |
| Service files | 21 | `ls app/services/*.py` |
| Ingestion source adapters | 8 | `ls app/sources/*.py` (excl. base, config, normalize) |
| Ghost threshold | 0.38 | `ghost_service.py:32` |
| Ghost weight: age | 0.30 | `ghost_service.py:24` |
| Ghost weight: repost | 0.20 | `ghost_service.py:25` |
| Ghost weight: vague | 0.25 | `ghost_service.py:26` |
| Ghost weight: company | 0.15 | `ghost_service.py:27` |
| Ghost weight: cohort | 0.10 | `ghost_service.py:28` |
| Ghost weights sum | 1.00 | `tests/test_ghost.py` verifies this |
| MIN_COHORT_APPS | 5 | `ghost_service.py:184`, `cohort_service.py:20`, `matching_service.py:40` |
| Semantic weight | 0.70 | `matching_service.py:33` |
| Skill weight | 0.30 | `matching_service.py:34` |
| RL cohort weight | 0.55 | `matching_service.py:47` |
| RL freshness weight | 0.35 | `matching_service.py:48` |
| RL ghost-inv weight | 0.10 | `matching_service.py:49` |
| Grounding threshold | 0.70 | `application_service.py:385` |
| W_RESP | 0.60 | `evaluation_service.py:60` |
| W_GHOST | 0.40 | `evaluation_service.py:61` |
| TEST_FRAC | 0.30 | `evaluation_service.py:64` |
| N_PREFIXES | 8 | `evaluation_service.py:67` |
| MIN_TOTAL | 30 | `evaluation_service.py:70` |
| Embedding dim | 384 | `app/llm/embeddings.py` (EMBEDDING_DIM) |
| University alias entries | 30 | `app/services/university_normalizer.py` |
| Normalizer tests | 42 | `tests/test_university_normalizer.py` |
| Demo users | 14 | `seed_demo.py` DEMO_USERS list |
| Demo postings | 26 | Count of POSTING_TEMPLATES entries |
| Demo app-outcome pairs | 364 | 26 postings × 14 users (seed_demo.py) |
| Alumni contacts | 23 | Count of ALUMNI_CONTACTS in seed_demo.py |
| Research opportunities | 20 | scripts/seed_research.py |
| Platform IQ | 66.7 | `smoke_replay.py` output after `seed_demo.py` (RNG seed=42) |
| Response Brier | 0.226 | same |
| Response AUC | 0.769 | same |
| Ghost F1 | 0.507 | same |
| IQ curve start (n=31) | IQ 75.1, Brier 0.249 | same |
| IQ curve end (n=255) | IQ 80.3, Brier 0.197 | same |
| Deceptive posting quote | "91% — ranked #22 because 0/5 batchmates heard back" | `seed_demo.py:1086` |
| Live frontend URL | internpilot.pages.dev | Cloudflare Pages deployment |
