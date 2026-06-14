# InternPilot — Master Project Specification
*(working name — rename freely)*

**AI Buildathon · DAU · End-to-end internship co-pilot for students**

---

## 1. One-line vision

The **anti-ghost-job, referral-first internship co-pilot** that spends a student's time *only* on applications that can actually convert — quality-gated, grounded in the student's real work, and powered by a **self-improving evaluation engine that gets smarter with every application and every student**.

## 2. Core principle

**Quality over quantity.** This is *not* a mass-blast bot (the LazyApply category that sprays thousands of applications for near-zero results). Every action is match-scored, response-likelihood-gated, ghost-filtered, and human-approved. We help a student win the *right* 20 roles, not blast 500 badly.

---

## 3. Full feature list (by module)

### Module 0 — Authentication & Accounts
- Email/password sign-up + Google OAuth login.
- Secure sessions (JWT + refresh tokens); passwords hashed (argon2/bcrypt).
- Per-user data isolation — every record scoped to its owner; no cross-user leakage.
- Consent management (explicit consent for Gmail access, GitHub, alumni data use).
- Optional `admin` role for a cohort-analytics view (CMC/placement-cell style).

### Module 1 — Onboarding & "Career Twin" (per-user profile)
- Résumé/CV upload → AI parses into a structured profile (skills, projects, experience, education).
- GitHub connect (clean API) → auto-pull real projects, languages, stack.
- Preferences: domains (SWE/ML/data/design/etc.), remote vs onsite/WFH, stipend, duration, locations, target companies.
- Output: a structured **skill graph**, a **profile-strength score**, and highlighted gaps.

### Module 2 — Opportunity Aggregation
- Pull openings from **legitimate structured sources**: ATS feeds (Greenhouse, Lever, Ashby, Workday endpoints) + aggregator APIs (RemoteOK, Remotive) + a "paste a link" intake.
- Normalize to one unified schema; **embedding-based deduplication** (same role on 5 boards → one entry).
- **Company resolution** — map each posting to a canonical company and enrich it (size, domain) to power ghost-history and alumni matching.
- Incremental refresh + caching for speed.
- *Deliberately avoids ToS-violating LinkedIn scraping (account-ban risk).*

### Module 3 — AI Matching & Ranking
- Semantic profile ↔ role match using embeddings (not keyword search).
- **Explainable match score**: "87% — strong on Python/PyTorch, missing Docker."
- **Skill-gap discovery**: "learn one thing (React) → unlock 30 more roles."
- Filters + personalized ranked feed.

### Module 4 — Ghost-Job Shield (collective intelligence)
- A **ghost score** per posting computed from: cohort response data, posting age, repost frequency, vague-JD detection, and company ghost-history.
- Flags/hides likely-dead postings before anyone wastes time: *"Skip — live 90+ days, 0 of 14 batch applicants got a response."*
- This is the signature feature; a 500-student batch all applying the same season is the perfect dense dataset.

### Module 5 — Response-Likelihood Predictor
- Predicts **P(response | match, company responsiveness, freshness, your history)**.
- Ranks the feed by **expected value**, not just match score.

### Module 6 — Referral / Warm-Intro Finder (DAU alumni graph)
- Finds DAU alumni / 2nd-degree connections at a target company.
- Drafts a personalized, non-cringe referral request.
- Optional within-DAU referral exchange.
- *The local moat — a global tool can't replicate the DAU alumni network. Referrals are the highest-yield channel by a wide margin; cold-apply response rates are near-zero.*

### Module 7 — Application Assistant (quality-gated, human-in-the-loop)
- **Job Decoder** — extracts what the JD actually wants.
- **ATS Optimizer** — tailors résumé to pass ATS keyword screens, shows an ATS match score, avoids over-optimizing into generic mush.
- **Grounded generation** — cover note / email that cites the student's *real* GitHub projects and coursework (RAG over their profile), not AI filler.
- **Confidence gate** — only high-match + high-response roles surface for applying.
- **Assisted send** via the user's own Gmail after review; guided pre-fill for portal applications (no silent auto-submit — keeps it ToS-safe and high quality).

### Module 8 — Tracker / Personal CRM
- Kanban pipeline: Saved → Applied → Viewed → Responded → Interview → Offer / Reject / Ghosted.
- Per-application contacts, notes, dates, and the artifacts that were sent.
- Smart follow-up reminders + AI-drafted follow-up email after N days of silence (student approves & sends).

### Module 9 — Interview-Prep Handoff
- On a positive response, auto-spin **company/role-specific interview prep**: likely questions, the student's weak spots, and a mock round. (Folds the prep-engine value into one product, single-user.)

### Module 10 — **The Evaluation System** (the unique, hardest core)
*See Section 5 for full detail — this is the centerpiece that makes the platform compound in value.*

### Module 11 — Dashboards & Notifications
- **Personal dashboard:** pipeline, response rate, time saved, "applications saved from ghosts," Platform-IQ curve.
- **Cohort dashboard (optional/admin):** batch-level ghost map, company responsiveness leaderboard.
- Daily/weekly digest of new high-match roles; deadline + follow-up alerts.

---

## 4. End-to-end user flow

1. **Sign up / log in** (auth).
2. **Onboard** — upload résumé + connect GitHub + set preferences → *Career Twin* built.
3. **Discover** — aggregation pulls roles → matching + Ghost-Shield + Response-Predictor rank them → personalized feed (ghosts filtered out, expected-value ranked).
4. **Apply** — pick a role → Job Decoder + ATS Optimizer + grounded draft → student reviews → assisted send. *Or* referral path → find alumni → draft warm intro.
5. **Track** — application logged; the system records every prediction it made (match, response-likelihood, ghost score, ATS score).
6. **Learn** — outcome arrives (reply detected via Gmail / status update) → **Evaluation System** ingests ground truth, scores its own predictions, updates per-user + cohort models, raises Platform IQ.
7. **Follow up** — no response after N days → AI-drafted follow-up (student approves & sends).
8. **Convert** — positive response → interview-prep handoff.
9. **Compound** — dashboards reflect pipeline, response rate, ghosts avoided, time saved; cohort intelligence sharpens for *every* student.

*(The loop repeats; the platform gets measurably smarter each cycle.)*

---

## 5. The Evaluation System (centerpiece — self-improving)

**Purpose:** close the loop between every action the platform takes and the real-world outcome, score itself, and continuously improve — so the platform's "IQ" rises with each application and each student. No competitor in the auto-apply space does this; it is the hardest and most defensible part.

**a) Outcome ingestion (ground truth)**
Capture real outcomes per application — responded? ghosted? interview? offer? rejection? time-to-response. Sources: Gmail reply detection, status updates, student input.

**b) Prediction self-scoring**
For every prediction the system made (match score, response-likelihood, ghost score, ATS score), compare to the realized outcome. Compute rolling metrics: ghost-detection precision/recall, response-likelihood calibration, correlation of ATS score with actual responses. *These metrics are both the improvement signal and the demo numbers.*

**c) Artifact-quality evaluation**
Score each generated application/email on multiple axes (ATS-fit, grounding/personalization depth, predicted response) before send; after the outcome, learn which artifact features correlated with success.

**d) Learning / model-update loop**
Feed outcomes back to recalibrate: **per-user weights** (what works for *you*) + **cohort models** (company responsiveness, ghost likelihood, winning pitch styles). Incremental updates live; full retrain nightly.

**e) Platform IQ metric**
A visible, rising score (prediction accuracy, response-rate uplift vs baseline) that demonstrably improves as data accumulates. *Demo/blog gold: "Day 1: 41% ghost-detection precision → Day 7 with cohort data: 78%."*

**f) A/B evaluation harness**
Continuously test variants (grounded vs generic email; referral vs cold) and let the winner inform recommendations — this produces the killer measurable for judging.

**Why it's unique & hard:** it's a real online-learning + evaluation system (not a chatbot wrapper), exactly the rigor ML faculty and interviewers respect — and it's what makes the platform *compound*. A static blast-bot can't get better with use; this does.

---

## 6. Data model (end-to-end data)

| Entity | Key fields | Relationships |
|---|---|---|
| **users** | id, name, email, password_hash, auth_provider, role, consent_flags, created_at | 1—1 profile; 1—* applications |
| **profiles** | user_id (FK), parsed_skills (jsonb), experience, education, github_url, projects (jsonb), preferences (jsonb), profile_strength, embedding | belongs to user |
| **companies** | id, canonical_name, domain, size, industry, ghost_history_score, responsiveness_score, embedding | 1—* postings |
| **postings** | id, company_id (FK), title, description, source, source_url, posted_at, last_seen_at, location, remote_flag, stipend, parsed_requirements (jsonb), embedding, ghost_score, status | belongs to company; 1—* matches |
| **matches** | id, user_id, posting_id, match_score, match_explanation, response_likelihood, expected_value, created_at | links user ↔ posting |
| **applications** | id, user_id, posting_id, channel (apply/email/referral), status, applied_at, last_status_at, predicted_response_prob, predicted_ghost | 1—* artifacts; 1—1 outcome |
| **artifacts** | id, application_id (FK), type (resume/cover/email/followup), content, ats_score, grounding_score, version, generated_at | belongs to application |
| **outcomes** | id, application_id (FK), outcome_type, responded (bool), time_to_response, interview (bool), offer (bool), source, recorded_at | belongs to application |
| **referrals** | id, user_id, posting_id, alumni_contact_id, status, intro_artifact_id | links user ↔ posting ↔ contact |
| **contacts_alumni** | id, name, company_id, role, dau_batch, linkedin, source | belongs to company |
| **evaluations** | id, prediction_type, predicted_value, actual_value, error, model_version, user_id?, cohort_flag, scored_at | the self-scoring log |
| **model_metrics** | id, model_name, version, metric_name, metric_value, computed_at | powers Platform-IQ curve |
| **events_audit** | id, user_id, event_type, payload (jsonb), ts | feeds the learning loop |
| **notifications** | id, user_id, type, content, read, ts | belongs to user |

---

## 7. Auth & database architecture

- **Auth:** JWT sessions + refresh tokens, argon2/bcrypt password hashing, Google OAuth, strict per-row `user_id` scoping, explicit consent records.
- **Database:** PostgreSQL (relational + `jsonb` for flexible parsed fields) with **pgvector** for embeddings (matching, dedup, company resolution). Redis for caching/queues (optional).
- **Background jobs:** scheduled aggregation refresh, nightly model retrain, follow-up reminders, Gmail reply-detection — run on a worker queue.

## 8. Tech stack (web-deployable)

- **Frontend:** built with **v0** (outputs Next.js + React + shadcn/Tailwind) → deploy on Vercel. *Owned by v0; consumes only the 🟦 endpoints in the API contract.*
- **Backend:** FastAPI (Python) or Node → deploy on Render/Railway/Fly.
- **DB:** Postgres + pgvector (Supabase/Neon).
- **AI:** multi-provider free LLMs behind a fallback router (see §8a); local open-source embeddings (sentence-transformers) for matching/dedup.
- **Auth:** NextAuth / Supabase Auth or custom JWT.
- **Jobs:** cron + queue (Celery / BullMQ).
- **Email:** Gmail API (OAuth) for assisted send + reply detection.

---

## 8a. LLM fallback architecture (cost: $0 at demo scale)

**Principle:** with free LLMs the constraint is the rate limit, not price — so stack several free tiers behind one router and never depend on a single provider.

**Provider chain (in order):**
1. **Google Gemini 2.5 Flash** (AI Studio) — *primary.* Multimodal (parses résumé PDFs/images directly), 1M context, ~1,500 req/day, no credit card.
2. **Groq (Llama 3.3 70B)** — *fast fallback,* ~14,400 req/day.
3. **OpenRouter** — *breadth fallback,* ~30 free models via one OpenAI-compatible key.
4. **Paid/local backstop** — one cheap paid key (e.g. DeepSeek) or a local Ollama model as the final link, so a rate limit can't kill the live demo.
- **Embeddings:** local sentence-transformers (free, no API).

**Router logic:** a single OpenAI-compatible interface sits in front of all providers. Try provider 1 → on a `429`/rate-limit/error, retry the same call on the next provider → … → backstop. Models stay hot-swappable; optionally use a gateway (OpenRouter / Portkey) for built-in load-balancing + fallback.

**Cautions:**
- Free tiers are **per developer key/account, not per end-user** — don't spin up many accounts to multiply credits (ToS violation). At demo scale, 1–2 keys + the chain is plenty.
- **Privacy:** free tiers may train on your inputs — keep real personal data (résumés) off them; demo on your own/synthetic data; note a paid privacy-respecting tier for production.
- Free tiers **change without notice** — the paid/Ollama backstop is non-negotiable for demo day.
- OpenAI / Anthropic APIs need a credit card (no indefinite free tier) → backstop only.

## 8b. Build workflow & ownership (v0 + Claude, contract-first)

**The API contract (separate doc) is the law — both sides build against it.**

- **v0 owns the UI only.** It generates every screen/component against the 🟦 endpoints using the exact object shapes in the contract. While the backend isn't ready, v0 mocks those responses with the contract shapes.
- **Claude owns everything else:** all endpoints (🟦 + ⚙️ workers), the Postgres + pgvector DB, auth + per-user data isolation, the AI pipeline behind the §8a router, and the wiring of the v0 UI to the backend.
- **One backend owner = no conflicts.** v0 never touches backend/auth/DB; Claude never re-designs the UI. The contract is the only interface between them.
- **Merge step:** drop the v0 output into the project folder → Claude wires each UI call to its real endpoint, replaces the mocks, and closes any gaps. Because both built to the same contract, this is wiring, not reconciling.
- **Change rule:** any new field/endpoint goes into the contract *first*, then both sides implement it.

## 9. USP (final)

**The anti-ghost-job, referral-first co-pilot that compounds.** Three pillars + the moat:

1. **Collective Ghost-Job Shield** — your cohort protects each other from dead postings; impossible for any single-user tool, perfect for a 500-student batch.
2. **Referral-first** — routes you to the highest-yield channel (DAU alumni warm intros), not the near-useless cold-apply pile.
3. **Quality-gated, project-grounded, ATS-optimized** — the opposite of the 2-star blast bots.
4. **The compounding moat (Evaluation System)** — the platform literally gets better the more it's used; every application and every student raises its accuracy. A static bot can't compound; this can. Plus the **DAU-local** alumni graph + dense cohort data that global tools structurally can't replicate.

## 10. Measurable value (judging + interview slide)

- Ghost-detection precision/recall (improving over the week).
- Response-likelihood calibration.
- A/B test: grounded-quality vs generic response rate; referral vs cold.
- Time saved = ghosts avoided × ~45 min per application.
- The **Platform-IQ rising curve** (Day 1 → Day 7).

## 11. 7-day build sequencing (two parallel tracks against the contract)

**Day 0 — prep:** lock the API contract (done) · sign up for free LLM keys (Gemini/Groq/OpenRouter) + a paid backstop · confirm & test data sources · seed alumni data.

**Track A — v0 (UI), against mocked contract data:**
- **Day 1–2:** generate all screens — auth, onboarding, match feed, application assistant, tracker, dashboards — using the 🟦 endpoint shapes.
- **Day 3–4:** polish, loading/empty/error states, responsive.

**Track B — Claude (backend + AI + integration):**
- **Day 1–2:** Auth + DB schema + Career Twin (résumé parse, GitHub).
- **Day 2–3:** Aggregation + matching + ranked feed.
- **Day 3–4:** Ghost-Shield + Response Predictor + prediction-logging.
- **Day 4–5:** Application Assistant (decoder, ATS, grounded gen) + Tracker + assisted send.
- **Day 5–6:** Evaluation learning loop + dashboards + Platform IQ + A/B harness.

**Merge & finish:**
- **Day 5–6:** drop the v0 UI into the repo → Claude wires it to real endpoints, replaces mocks, adds referral finder + follow-up + interview-prep handoff.
- **Day 7:** deploy, seed data, measure, write the blog.

---

*Build the MVP spine first (auth → twin → aggregate → match → ghost-shield → quality-gated draft → tracker). The referral graph, full evaluation learning loop, and interview-prep handoff are the differentiators layered on top.*