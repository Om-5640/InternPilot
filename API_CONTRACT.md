# InternPilot — API Contract & Data Schema (v1)

**The single source of truth both the v0 frontend and the Claude backend build against.**
If a field or endpoint isn't here, it doesn't exist yet — add it here first, then build. Field names are identical everywhere on purpose.

---

## 0. Conventions

- **Base path:** all routes are prefixed `/api`.
- **Auth:** every endpoint requires `Authorization: Bearer <jwt>` **except** `signup`, `login`, `google`. The backend scopes every record to the authenticated `user_id` — no cross-user access, ever.
- **Content-Type:** `application/json`, except résumé upload (`multipart/form-data`).
- **IDs:** UUID strings.
- **Timestamps:** ISO-8601 UTC strings, e.g. `"2026-06-13T10:30:00Z"`.
- **Scores:** floats in `0..1` unless noted (`ats_score` and `profile_strength` are `0..100`).
- **Errors:** non-2xx return `{ "error": { "code": string, "message": string } }` with a matching HTTP status (`400/401/403/404/409/422/429/500`).
- **Pagination:** list endpoints accept `?page=1&limit=20`; responses are `{ data: T[], page, limit, total }`.
- **Money/numbers:** `stipend` is a number (monthly, INR) or `null`.

---

## 1. Data schema (objects)

Types shown in TypeScript notation (`?` = optional/nullable).

```ts
type Role = "student" | "admin";
type WorkMode = "remote" | "onsite" | "hybrid" | "any";
type PostingStatus = "active" | "stale";
type Channel = "portal" | "email" | "referral";
type AppStatus =
  | "saved" | "applied" | "viewed" | "responded"
  | "interview" | "offer" | "rejected" | "ghosted";
type ArtifactType =
  "resume" | "cover_letter" | "email" | "followup" | "referral_intro";
type OutcomeType =
  "response" | "rejection" | "interview" | "offer" | "ghosted" | "no_response";
type ReferralStatus =
  "suggested" | "requested" | "accepted" | "declined" | "no_response";
type PredictionType = "match" | "response_likelihood" | "ghost" | "ats";
type OpportunityType = "company" | "research";
type CompanyType = "product" | "service" | "research_lab" | "unknown";
type QuestionCategory =
  | "coding" | "cs_fundamentals" | "project" | "behavioral" | "hr" | "gd"
  | "research_fit" | "domain_depth" | "methods";
type Difficulty = "easy" | "medium" | "hard";
type NotificationType =
  "new_matches" | "deadline" | "followup_due" | "response_received" | "digest";

interface User {
  id: string;
  name: string;
  email: string;
  role: Role;
  auth_provider: "password" | "google";
  consent: { gmail: boolean; github: boolean; alumni_data: boolean };
  created_at: string;
}

interface Profile {
  user_id: string;
  headline?: string;
  university?: string;          // student's own university (parsed from résumé or user-set)
  grad_year?: number;           // expected graduation year (int)
  research_interests: string[]; // empty array by default
  skills: string[];
  experience: { title: string; org: string; start?: string; end?: string; description?: string }[];
  education: { degree: string; institution: string; year?: string; gpa?: number }[];
  projects: { name: string; description?: string; tech: string[]; url?: string }[];
  github_url?: string;
  preferences: {
    domains: string[];
    work_mode: WorkMode;
    stipend_min?: number;
    duration_months?: number;
    locations: string[];
    target_companies: string[];
  };
  profile_strength: number;   // 0..100
  gaps: string[];
  updated_at: string;
}

interface CompanySummary { id: string; name: string; domain?: string }

interface Company extends CompanySummary {
  size?: string;
  industry?: string;
  responsiveness_score: number;   // 0..1, from cohort data
  ghost_history_score: number;    // 0..1
}

interface Posting {
  id: string;
  company: CompanySummary;
  title: string;
  description: string;
  requirements: string[];
  location?: string;
  work_mode: WorkMode;
  stipend?: number;
  source: "greenhouse" | "lever" | "ashby" | "remoteok" | "remotive" | "manual";
  source_url: string;
  posted_at?: string;
  last_seen_at: string;
  status: PostingStatus;
  ghost_score: number;   // 0..1
  is_ghost: boolean;     // derived threshold on ghost_score
}

interface Match {
  posting_id: string;
  posting: Posting;            // embedded for the feed
  match_score: number;         // 0..1
  match_explanation: string;
  matched_skills: string[];
  missing_skills: string[];
  response_likelihood: number; // 0..1
  expected_value: number;      // 0..1, the ranking key
  ghost_score: number;
  is_ghost: boolean;
  created_at: string;
}

interface Artifact {
  id: string;
  application_id?: string;
  type: ArtifactType;
  content: string;
  ats_score?: number;          // 0..100
  missing_keywords: string[];
  grounding_score?: number;    // 0..1
  predicted_response?: number; // 0..1
  version: number;
  generated_at: string;
}

interface Outcome {
  id: string;
  application_id: string;
  outcome_type: OutcomeType;
  responded: boolean;
  time_to_response_hours?: number;
  source: "gmail" | "manual" | "status_update";
  recorded_at: string;
}

interface Application {
  id: string;
  posting_id: string;
  posting: { id: string; title: string; company_name: string };
  channel: Channel;
  status: AppStatus;
  artifacts: Artifact[];
  predicted_response_prob: number; // 0..1
  predicted_ghost: boolean;
  applied_at?: string;
  last_status_at: string;
  outcome?: Outcome;
  created_at: string;
}

interface Contact {            // alumni / referral target
  id: string;
  name: string;
  company_id: string;
  company_name: string;
  role?: string;
  grad_year?: number;   // graduation year (int); replaces dau_batch
  university?: string;  // alumnus's university
  linkedin?: string;
  relationship: "alumni" | "second_degree" | "unknown";
}

interface Referral {
  id: string;
  posting_id?: string;
  company_id: string;
  contact: Contact;
  status: ReferralStatus;
  intro_artifact_id?: string;
  created_at: string;
}

interface PrepQuestion {
  q: string;
  type: "technical" | "behavioral" | "gd";
  category?: QuestionCategory;           // v1.1 — additive
  difficulty?: Difficulty;               // v1.1 — additive
  answer_guidance?: string;
  ideal_answer_outline?: string;         // v1.1 — additive
}

interface InterviewPrep {
  id: string;
  application_id?: string;
  company_name: string;
  role: string;
  opportunity_type: OpportunityType;     // v1.1 — default "company"
  region?: string;                       // v1.1 — additive
  company_type: CompanyType;             // v1.1 — classified internally
  questions: PrepQuestion[];
  weak_spots: string[];
  reverse_questions: string[];           // v1.1 — additive
  created_at: string;
  updated_at: string;
}

interface Evaluation {         // prediction-vs-outcome log (mostly internal)
  id: string;
  prediction_type: PredictionType;
  predicted_value: number;
  actual_value?: number;
  error?: number;
  model_version: string;
  user_id?: string;
  scored_at?: string;
}

interface ModelMetric {        // powers the Platform-IQ curve
  id: string;
  model_name: string;
  metric_name: "ghost_precision" | "response_calibration" | "ats_correlation" | "platform_iq";
  metric_value: number;
  computed_at: string;
}

interface Notification {
  id: string;
  type: NotificationType;
  content: string;
  read: boolean;
  created_at: string;
}

interface DashboardSummary {
  pipeline: Record<AppStatus, number>;
  response_rate: number;       // 0..1
  time_saved_hours: number;
  ghosts_avoided: number;
  platform_iq: number;
  iq_trend: { date: string; value: number }[];
}
```

---

## 2. Endpoints

Format: `METHOD /path` — *auth* — **request** → **response**.
🟦 = called by the v0 frontend · ⚙️ = internal/worker (Claude builds, UI never calls).

### Module 0 — Auth
- 🟦 `POST /api/auth/signup` — public — `{ name, email, password }` → `201 { user: User, token, refresh_token }`
- 🟦 `POST /api/auth/login` — public — `{ email, password }` → `200 { user, token, refresh_token }`
- 🟦 `POST /api/auth/google` — public — `{ id_token }` → `200 { user, token, refresh_token }`
- 🟦 `POST /api/auth/refresh` — public — `{ refresh_token }` → `200 { token }`
- 🟦 `POST /api/auth/logout` — auth — `{}` → `204`
- 🟦 `GET  /api/auth/me` — auth — → `200 { user: User }`
- 🟦 `PUT  /api/auth/consent` — auth — `{ gmail?, github?, alumni_data? }` → `200 { user: User }`

### Module 1 — Profile / Career Twin
- 🟦 `POST /api/profile/resume` — auth — `multipart: file` → `200 { profile: Profile }` *(AI-parsed)*
- 🟦 `POST /api/profile/github` — auth — `{ github_url }` → `200 { profile: Profile }`
- 🟦 `GET  /api/profile` — auth — → `200 { profile: Profile }`
- 🟦 `PUT  /api/profile` — auth — `Partial<Profile>` → `200 { profile: Profile }`
- 🟦 `PUT  /api/profile/preferences` — auth — `Profile["preferences"]` → `200 { profile: Profile }`
- 🟦 `GET  /api/profile/strength` — auth — → `200 { profile_strength: number, gaps: string[] }`

### Module 2 — Postings / Aggregation
- 🟦 `GET  /api/postings` — auth — query: `work_mode?, domain?, company?, page?, limit?` → `200 { data: Posting[], page, limit, total }`
- 🟦 `GET  /api/postings/:id` — auth — → `200 { posting: Posting }`
- 🟦 `POST /api/postings/import` — auth — `{ url }` → `201 { posting: Posting }` *(paste-a-link intake)*
- ⚙️ `POST /api/aggregation/refresh` — admin/cron — `{}` → `202 { ingested: number, deduped: number }`

### Module 3 — Matching & Ranking
- 🟦 `GET  /api/matches` — auth — query: `work_mode?, domain?, include_ghosts?(bool, default false), sort?(default "expected_value"), page?, limit?` → `200 { data: Match[], page, limit, total }`
- 🟦 `GET  /api/matches/:posting_id` — auth — → `200 { match: Match }`
- 🟦 `GET  /api/skill-gaps` — auth — → `200 { gaps: { skill: string, unlockable_roles: number }[] }`

### Module 4 — Ghost-Job Shield
- 🟦 `GET /api/postings/:id/ghost` — auth — → `200 { ghost_score: number, is_ghost: boolean, signals: string[], cohort: { applied: number, responded: number } }`

*(Ghost data is also embedded in every `Posting`/`Match`. This endpoint is for the detail view.)*

### Module 5 — Response Likelihood
*(Embedded as `response_likelihood` / `expected_value` in `Match`. No separate call needed for the UI.)*

### Module 6 — Referral / Warm-Intro Finder
- 🟦 `GET  /api/referrals/candidates` — auth — query: `posting_id | company_id` → `200 { data: Contact[] }`
- 🟦 `POST /api/referrals` — auth — `{ posting_id?, company_id, contact_id }` → `201 { referral: Referral }` *(creates referral + drafts intro artifact)*
- 🟦 `GET  /api/referrals` — auth — → `200 { data: Referral[] }`
- 🟦 `PUT  /api/referrals/:id` — auth — `{ status: ReferralStatus }` → `200 { referral: Referral }`

### Module 7 — Application Assistant
- 🟦 `POST /api/applications/decode` — auth — `{ posting_id }` → `200 { requirements: string[], keywords: string[], summary: string }` *(Job Decoder)*
- 🟦 `POST /api/applications/draft` — auth — `{ posting_id, type: ArtifactType, channel: Channel }` → `200 { artifact: Artifact }` *(grounded generation + ats_score)*
- 🟦 `POST /api/applications/ats-score` — auth — `{ posting_id, content }` → `200 { ats_score: number, missing_keywords: string[] }`
- 🟦 `POST /api/applications` — auth — `{ posting_id, channel, artifact_id }` → `201 { application: Application }`
- 🟦 `POST /api/applications/:id/send` — auth — `{ via: "gmail" }` → `200 { application: Application }` *(assisted send; requires gmail consent)*
- 🟦 `GET  /api/applications` — auth — query: `status?, page?, limit?` → `200 { data: Application[], page, limit, total }`
- 🟦 `GET  /api/applications/:id` — auth — → `200 { application: Application }`
- 🟦 `PUT  /api/applications/:id` — auth — `{ status?: AppStatus, notes?: string }` → `200 { application: Application }`
- 🟦 `PUT  /api/artifacts/:id` — auth — `{ content }` → `200 { artifact: Artifact }` *(user edits before send)*

### Module 8 — Tracker / Follow-up / Outcomes
- 🟦 `POST /api/applications/:id/followup` — auth — `{}` → `200 { artifact: Artifact }` *(AI-drafted follow-up; type="followup")*
- 🟦 `POST /api/applications/:id/outcome` — auth — `{ outcome_type, responded, time_to_response_hours? }` → `201 { outcome: Outcome }` *(manual log)*
- ⚙️ `POST /api/integrations/gmail/sync` — worker — `{}` → `200 { detected: number }` *(reply detection → auto-creates outcomes)*

### Module 9 — Interview-Prep Handoff
- 🟦 `POST /api/interview-prep` — auth — `{ application_id?, company_name, role, opportunity_type?, region? }` → `201 { prep: InterviewPrep }` *(adaptive: company vs research, region-aware round structure)*
- 🟦 `GET  /api/interview-prep/:id` — auth — → `200 { prep: InterviewPrep }`

### Module 10 — Evaluation System
- 🟦 `GET  /api/evaluation/metrics` — auth — → `200 { platform_iq: number, iq_trend: { date, value }[], metrics: ModelMetric[] }`
- 🟦 `GET  /api/evaluation/accuracy` — auth — → `200 { ghost_precision: number, response_calibration: number, ats_correlation: number }`
- 🟦 `GET  /api/evaluation/ab-tests` — auth — → `200 { data: { name: string, variant_a: number, variant_b: number, winner: string }[] }`
- ⚙️ `POST /api/evaluation/score` — worker — `{}` → `200 { scored: number }` *(compares predictions to outcomes, updates models + metrics)*

### Module 11 — Dashboard & Notifications
- 🟦 `GET /api/dashboard` — auth — → `200 { summary: DashboardSummary }`
- 🟦 `GET /api/dashboard/cohort` — admin — → `200 { ghost_map: object, company_responsiveness: object }`
- 🟦 `GET /api/notifications` — auth — → `200 { data: Notification[] }`
- 🟦 `PUT /api/notifications/:id/read` — auth — `{}` → `200 { notification: Notification }`
- 🟦 `GET /api/digest` — auth — → `200 { new_matches: Match[], due_followups: Application[] }`

---

## 3. How v0 and Claude use this

- **v0 builds the UI against the 🟦 endpoints only**, using the exact object shapes in §1. It never assumes a field that isn't defined here. While the backend is being built, v0 mocks these responses with the §1 shapes.
- **Claude builds every endpoint** (🟦 + ⚙️) plus the workers (`aggregation/refresh`, `gmail/sync`, `evaluation/score`) and the DB. Claude owns auth, data isolation, and all AI calls (behind the §8a fallback router).
- **Change rule:** any new field or endpoint is added *here first*, then implemented on both sides. The contract is the law — that's what keeps the merge a wiring job, not a debugging job.

---
*v1.1 — Module 9 Interview Prep: OpportunityType, CompanyType, QuestionCategory, Difficulty, PrepQuestion, InterviewPrep extended with opportunity_type/region/company_type/reverse_questions/updated_at; question items gain category/difficulty/ideal_answer_outline. All new fields are additive/optional — UI-safe.*