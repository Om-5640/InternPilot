// Central API client. All UI data access goes through this module.
//
// When VITE_USE_MOCKS=false (default in .env), every method calls the real
// FastAPI backend at VITE_API_BASE_URL. Set VITE_USE_MOCKS=true to fall back
// to the in-memory fixtures for local development without a running backend.

import {
  user, profile, postings, matches, applications, referrals, contacts,
  dashboardSummary, notifications,
  researchOpportunities, researchOutreach,
  type User, type Profile, type Posting, type Match, type Application,
  type Referral, type Contact, type DashboardSummary,
  type Notification, type Artifact, type ApplicationStatus,
  type ResearchOpportunity, type ResearchOutreach, type ResearchOutreachStatus,
  type ResearchPitch,
} from "./mocks";

export type { User } from "./mocks";

export const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL || "https://internpilot-backend.onrender.com/api";
// Mocks are opt-in: only enabled when VITE_USE_MOCKS is explicitly "true" or "1".
// Empty string, undefined, or any other value keeps the real backend active.
const _mockFlag = String(import.meta.env.VITE_USE_MOCKS ?? "").toLowerCase();
const USE_MOCKS = _mockFlag === "true" || _mockFlag === "1";

// ---------------------------------------------------------------------------
// Guest mode — browse-only with mock data; cleared on real login/signup
// ---------------------------------------------------------------------------

const GUEST_KEY = "internpilot_guest";

export function isGuestMode(): boolean {
  if (typeof localStorage === "undefined") return false;
  return localStorage.getItem(GUEST_KEY) === "true";
}

export function setGuestMode(value: boolean): void {
  if (typeof localStorage === "undefined") return;
  if (value) {
    localStorage.setItem(GUEST_KEY, "true");
  } else {
    localStorage.removeItem(GUEST_KEY);
  }
}

function shouldUseMocks(): boolean {
  return USE_MOCKS || isGuestMode() || !getToken();
}

const delay = (ms = 180) => new Promise<void>((r) => setTimeout(r, ms));

// ---------------------------------------------------------------------------
// Token + user storage helpers
// ---------------------------------------------------------------------------

const TOKEN_KEY = "internpilot_token";
const REFRESH_KEY = "internpilot_refresh_token";
const USER_KEY = "internpilot_user";

export function getToken(): string | null {
  if (typeof localStorage === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  if (typeof localStorage === "undefined") return;
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  if (typeof localStorage === "undefined") return;
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(REFRESH_KEY);
}

function getRefreshToken(): string | null {
  if (typeof localStorage === "undefined") return null;
  return localStorage.getItem(REFRESH_KEY);
}

function setRefreshToken(token: string): void {
  if (typeof localStorage === "undefined") return;
  localStorage.setItem(REFRESH_KEY, token);
}

export function getStoredUser(): User | null {
  if (typeof localStorage === "undefined") return null;
  try {
    const raw = localStorage.getItem(USER_KEY);
    return raw ? (JSON.parse(raw) as User) : null;
  } catch { return null; }
}

function storeUser(u: User): void {
  if (typeof localStorage === "undefined") return;
  localStorage.setItem(USER_KEY, JSON.stringify(u));
}

function clearStoredUser(): void {
  if (typeof localStorage === "undefined") return;
  localStorage.removeItem(USER_KEY);
}

// ---------------------------------------------------------------------------
// Core HTTP client
// ---------------------------------------------------------------------------

class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function http<T>(
  path: string,
  init?: RequestInit,
  opts: { skipAuthRedirect?: boolean } = {},
): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(init?.headers as Record<string, string> | undefined),
  };

  const res = await fetch(`${API_BASE_URL}${path}`, { ...init, headers });

  // Parse error body helper
  const parseErrBody = async (): Promise<{ code: string; message: string }> => {
    let code = "UNKNOWN_ERROR";
    let message = `${res.status} ${res.statusText}`;
    try {
      const body = await res.clone().json();
      if (body?.error?.code) code = body.error.code;
      if (body?.error?.message) message = body.error.message;
    } catch { /* ignore */ }
    return { code, message };
  };

  if (res.status === 401) {
    const { code, message } = await parseErrBody();
    if (!opts.skipAuthRedirect) {
      if (token) {
        // Try a silent refresh before giving up
        const refreshToken = getRefreshToken();
        if (refreshToken) {
          try {
            const refreshRes = await fetch(`${API_BASE_URL}/auth/refresh`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ refresh_token: refreshToken }),
            });
            if (refreshRes.ok) {
              const { token: newToken } = await refreshRes.json();
              setToken(newToken);
              // Retry the original request with the new token
              const retryHeaders: Record<string, string> = {
                "Content-Type": "application/json",
                Authorization: `Bearer ${newToken}`,
                ...(init?.headers as Record<string, string> | undefined),
              };
              const retryRes = await fetch(`${API_BASE_URL}${path}`, { ...init, headers: retryHeaders });
              if (retryRes.status === 204) return undefined as unknown as T;
              if (retryRes.ok) return retryRes.json();
            }
          } catch { /* fall through to redirect */ }
        }
        clearToken();
        if (typeof window !== "undefined" && !window.location.pathname.startsWith("/auth")) {
          window.location.href = "/auth";
        }
        throw new ApiError(401, code, "Session expired. Please sign in again.");
      }
      // No token: unauthenticated request — throw silently (no redirect)
      throw new ApiError(401, code, message);
    }
    // Auth endpoints: pass the backend's own message through unchanged
    throw new ApiError(401, code, message);
  }

  if (!res.ok) {
    const { code, message } = await parseErrBody();
    throw new ApiError(res.status, code, message);
  }

  if (res.status === 204) return undefined as unknown as T;
  return res.json();
}

// ---------------------------------------------------------------------------
// Auth helpers — called by auth.tsx route
// ---------------------------------------------------------------------------

export interface AuthPayload {
  user: User;
  token: string;
  refresh_token: string;
}

export async function authSignup(name: string, email: string, password: string): Promise<AuthPayload> {
  const data = await http<AuthPayload>(
    "/auth/signup",
    { method: "POST", body: JSON.stringify({ name, email, password }) },
    { skipAuthRedirect: true },
  );
  setToken(data.token);
  if (data.refresh_token) setRefreshToken(data.refresh_token);
  storeUser(mapUser(data));
  setGuestMode(false);
  return data;
}

export async function authLogin(email: string, password: string): Promise<AuthPayload> {
  const data = await http<AuthPayload>(
    "/auth/login",
    { method: "POST", body: JSON.stringify({ email, password }) },
    { skipAuthRedirect: true },
  );
  setToken(data.token);
  if (data.refresh_token) setRefreshToken(data.refresh_token);
  storeUser(mapUser(data));
  setGuestMode(false);
  return data;
}

export async function authGoogleLogin(idToken: string): Promise<AuthPayload> {
  const data = await http<AuthPayload>(
    "/auth/google",
    { method: "POST", body: JSON.stringify({ id_token: idToken }) },
    { skipAuthRedirect: true },
  );
  setToken(data.token);
  if (data.refresh_token) setRefreshToken(data.refresh_token);
  storeUser(mapUser(data));
  setGuestMode(false);
  return data;
}

export async function authLogout(): Promise<void> {
  try { await http("/auth/logout", { method: "POST" }); } catch { /* ignore */ }
  clearToken();
  clearStoredUser();
  setGuestMode(false);
}

// ---------------------------------------------------------------------------
// In-memory mutable copies so mock writes feel real within a session
// ---------------------------------------------------------------------------

let _applications: Application[] = [...applications];
let _referrals: Referral[] = [...referrals];
let _notifications: Notification[] = [...notifications];
let _outreach: ResearchOutreach[] = [...researchOutreach];

// ---------------------------------------------------------------------------
// Shape-mapping helpers: adapt real backend JSON → frontend types
// ---------------------------------------------------------------------------

// Backend GET /auth/me → { user: UserSchema }
// Backend POST /auth/signup|login → { user: UserSchema, token, refresh_token }
function mapUser(raw: any): User {
  const u = raw?.user ?? raw;
  return {
    id: String(u.id),
    name: u.name,
    email: u.email,
    role: u.role ?? "student",
    consent: u.consent ?? { gmail: false, github: false, alumni_data: false },
  };
}

// Backend GET /profile → { profile: ProfileSchema }
function mapProfile(raw: any): Profile {
  const p = raw?.profile ?? raw;
  const prefs = p.preferences ?? {};
  return {
    user_id: String(p.user_id),
    headline: p.headline ?? "",
    university: p.university ?? "",
    grad_year: p.grad_year ?? null,
    research_interests: p.research_interests ?? [],
    skills: p.skills ?? [],
    experience: p.experience ?? [],
    education: p.education ?? [],
    projects: p.projects ?? [],
    github_url: p.github_url ?? "",
    preferences: {
      domains: prefs.domains ?? [],
      work_mode: prefs.work_mode ?? "any",
      stipend_min: prefs.stipend_min ?? 0,
      duration_months: prefs.duration_months ?? 3,
      locations: prefs.locations ?? [],
      target_companies: prefs.target_companies ?? [],
    },
    profile_strength: p.profile_strength ?? 0,
    gaps: p.gaps ?? [],
  };
}

// Backend GET /matches → { data: [MatchSchema...], page, limit, total }
// MatchSchema has posting_id + posting (PostingSchema) already
function mapMatch(raw: any): Match {
  const posting = raw.posting ?? {};
  const company = posting.company ?? {};
  return {
    posting: {
      id: String(posting.id ?? raw.posting_id),
      company: {
        id: String(company.id),
        name: company.name ?? "",
        domain: company.domain ?? "",
      },
      title: posting.title ?? "",
      description: posting.description ?? "",
      requirements: posting.requirements ?? [],
      location: posting.location ?? "",
      work_mode: posting.work_mode ?? "remote",
      stipend: posting.stipend ?? 0,
      source: posting.source ?? "",
      source_url: posting.source_url ?? "",
      posted_at: posting.posted_at ?? "",
      last_seen_at: posting.last_seen_at ?? "",
      status: posting.status ?? "open",
      ghost_score: raw.ghost_score ?? posting.ghost_score ?? 0,
      is_ghost: raw.is_ghost ?? posting.is_ghost ?? false,
    },
    match_score: raw.match_score ?? 0,
    match_explanation: raw.match_explanation ?? "",
    matched_skills: raw.matched_skills ?? [],
    missing_skills: raw.missing_skills ?? [],
    response_likelihood: raw.response_likelihood ?? 0,
    expected_value: raw.expected_value ?? 0,
    ghost_score: raw.ghost_score ?? 0,
    is_ghost: raw.is_ghost ?? false,
    created_at: raw.created_at ?? new Date().toISOString(),
  };
}

// Backend GET /postings → { data: [PostingSchema...] }
function mapPosting(raw: any): Posting {
  const company = raw.company ?? {};
  return {
    id: String(raw.id),
    company: {
      id: String(company.id),
      name: company.name ?? "",
      domain: company.domain ?? "",
    },
    title: raw.title ?? "",
    description: raw.description ?? "",
    requirements: raw.requirements ?? [],
    location: raw.location ?? "",
    work_mode: raw.work_mode ?? "remote",
    stipend: raw.stipend ?? 0,
    source: raw.source ?? "",
    source_url: raw.source_url ?? "",
    posted_at: raw.posted_at ?? "",
    last_seen_at: raw.last_seen_at ?? "",
    status: raw.status ?? "open",
    ghost_score: raw.ghost_score ?? 0,
    is_ghost: raw.is_ghost ?? false,
  };
}

// Backend GET /applications → { data: [ApplicationSchema...] }
function mapApplication(raw: any): Application {
  const posting = raw.posting ?? {};
  return {
    id: String(raw.id),
    posting_id: String(raw.posting_id),
    posting: {
      id: String(posting.id ?? raw.posting_id),
      title: posting.title ?? "",
      company_name: posting.company_name ?? "",
    },
    channel: (raw.channel as Application["channel"]) ?? "direct",
    status: (raw.status as ApplicationStatus) ?? "saved",
    artifacts: (raw.artifacts ?? []).map((a: any): Artifact => ({
      id: String(a.id),
      application_id: String(a.application_id ?? raw.id),
      type: a.type ?? "resume",
      content: a.content ?? "",
      ats_score: a.ats_score ?? 0,
      missing_keywords: a.missing_keywords ?? [],
      grounding_score: a.grounding_score ?? 0,
      predicted_response: a.predicted_response ?? 0,
      version: a.version ?? 1,
      generated_at: a.generated_at ?? new Date().toISOString(),
    })),
    predicted_response_prob: raw.predicted_response_prob ?? 0,
    applied_at: raw.applied_at ?? "",
    last_status_at: raw.last_status_at ?? "",
    outcome: raw.outcome?.outcome_type ?? undefined,
  };
}

// Backend GET /referrals → { data: [...] }
// Backend GET /referrals/candidates → { data: [...] }
function mapContact(raw: any): Contact {
  return {
    id: String(raw.id),
    name: raw.name ?? "",
    company_id: String(raw.company_id),
    company_name: raw.company_name ?? "",
    role: raw.role ?? "",
    university: raw.university ?? "",
    grad_year: raw.grad_year ?? 0,
    linkedin: raw.linkedin ?? "",
    relationship: raw.relationship ?? "unknown",
  };
}

function mapReferral(raw: any): Referral {
  return {
    id: String(raw.id),
    posting_id: String(raw.posting_id),
    company_id: String(raw.company_id ?? ""),
    contact: mapContact(raw.contact ?? {}),
    status: (raw.status as Referral["status"]) ?? "suggested",
    intro_artifact_id: raw.intro_artifact_id ? String(raw.intro_artifact_id) : null,
    created_at: raw.created_at ?? new Date().toISOString(),
  };
}

// Backend GET /dashboard → DashboardSummary
// Backend iq_trend is list[float], frontend chart expects {date, value}[]
function mapDashboard(raw: any): DashboardSummary {
  const trendRaw: number[] = raw.iq_trend ?? [];
  const iq_trend = trendRaw.map((value, i) => ({
    date: `W${i + 1}`,
    value,
  }));
  return {
    pipeline: raw.pipeline ?? {
      saved: 0, applied: 0, viewed: 0, responded: 0,
      interview: 0, offer: 0, rejected: 0, ghosted: 0,
    },
    response_rate: raw.response_rate ?? 0,
    time_saved_hours: raw.time_saved_hours ?? 0,
    ghosts_avoided: raw.ghosts_avoided ?? 0,
    platform_iq: raw.platform_iq ?? 0,
    iq_trend,
  };
}

// Backend GET /research/opportunities → { data: [ResearchMatchSchema...] }
// ResearchMatchSchema = { opportunity: ResearchOpportunitySchema, fit_score, fit_explanation, matched_skills, missing_skills }
// Frontend ResearchOpportunity = flat (professor_name, institution, lab_name, research_area, fit_score, ...)
function mapResearchOpportunity(raw: any): ResearchOpportunity {
  const opp = raw.opportunity ?? raw;
  return {
    id: String(opp.id ?? raw.id),
    professor_name: opp.professor_name ?? "",
    institution: opp.institution ?? "",
    lab_name: opp.lab_name ?? "",
    research_area: opp.research_area ?? "",
    fit_score: raw.fit_score ?? 0,
    matched_skills: raw.matched_skills ?? opp.desired_skills ?? [],
    fit_explanation: raw.fit_explanation ?? "",
    professor_email: opp.contact_email ?? "",
    recent_paper: opp.recent_paper?.title ? opp.recent_paper : undefined,
    region: opp.region ?? raw.region ?? "",
  };
}

// Backend POST /research/pitch → ArtifactSchema (not ResearchPitch)
// Frontend ResearchPitch = { id, opportunity_id, subject, body, generated_at }
// We adapt ArtifactSchema.content (which should contain email body) → ResearchPitch
function mapResearchPitch(raw: any, opportunity_id: string): ResearchPitch {
  // Content may be a JSON string or plain text email
  let subject = "Research inquiry";
  let body = raw.content ?? "";
  try {
    const parsed = JSON.parse(raw.content);
    if (parsed?.subject) subject = parsed.subject;
    if (parsed?.body) body = parsed.body;
  } catch {
    // Content is plain email text — extract subject from first line if it starts with "Subject:"
    const lines = body.split("\n");
    if (lines[0]?.toLowerCase().startsWith("subject:")) {
      subject = lines[0].replace(/^subject:\s*/i, "").trim();
      body = lines.slice(1).join("\n").trim();
    }
  }
  return {
    id: String(raw.id),
    opportunity_id,
    subject,
    body,
    generated_at: raw.generated_at ?? new Date().toISOString(),
  };
}

// Backend ResearchOutreachWithOpportunitySchema = { id, opportunity_id, opportunity: {professor_name, institution, lab_name}, status, pitch_id, last_status_at, created_at }
// Frontend ResearchOutreach = same shape
function mapResearchOutreach(raw: any): ResearchOutreach {
  const opp = raw.opportunity ?? {};
  return {
    id: String(raw.id),
    opportunity_id: String(raw.opportunity_id ?? raw.research_opportunity_id),
    opportunity: {
      professor_name: opp.professor_name ?? "",
      institution: opp.institution ?? "",
      lab_name: opp.lab_name ?? "",
    },
    status: (raw.status as ResearchOutreachStatus) ?? "suggested",
    pitch_id: raw.pitch_id ? String(raw.pitch_id) : (raw.pitch_artifact_id ? String(raw.pitch_artifact_id) : null),
    contacted_at: raw.contacted_at ?? null,
    replied_at: raw.replied_at ?? null,
    last_status_at: raw.last_status_at ?? raw.updated_at ?? new Date().toISOString(),
  };
}

// ---------------------------------------------------------------------------
// Public API object
// ---------------------------------------------------------------------------

export const api = {
  // ---------- Auth ----------
  async me(): Promise<User> {
    if (!shouldUseMocks()) {
      const raw = await http<any>("/auth/me");
      return mapUser(raw);
    }
    await delay(); return user;
  },

  // ---------- Profile ----------
  async getProfile(): Promise<Profile> {
    if (!shouldUseMocks()) {
      const raw = await http<any>("/profile");
      return mapProfile(raw);
    }
    await delay(); return profile;
  },
  async updateProfile(updates: Partial<Profile>): Promise<Profile> {
    if (!shouldUseMocks()) {
      const raw = await http<any>("/profile", {
        method: "PUT", body: JSON.stringify(updates),
      });
      return mapProfile(raw);
    }
    await delay(); return { ...profile, ...updates };
  },
  async importGithub(github_url: string): Promise<Profile> {
    if (!shouldUseMocks()) {
      const raw = await http<any>("/profile/github", {
        method: "POST", body: JSON.stringify({ github_url }),
      });
      return mapProfile(raw.profile ?? raw);
    }
    await delay(); return { ...profile, github_url };
  },
  async getStrength(): Promise<{ profile_strength: number; gaps: string[] }> {
    if (!shouldUseMocks()) return http("/profile/strength");
    await delay(); return { profile_strength: profile.profile_strength, gaps: profile.gaps };
  },

  // ---------- Postings ----------
  async getPostings(): Promise<Posting[]> {
    if (!shouldUseMocks()) {
      const raw = await http<any>("/postings");
      const items: any[] = raw?.data ?? (Array.isArray(raw) ? raw : []);
      return items.map(mapPosting);
    }
    await delay(); return postings;
  },
  async getPosting(id: string): Promise<Posting | undefined> {
    if (!shouldUseMocks()) {
      const raw = await http<any>(`/postings/${id}`);
      const p = raw?.posting ?? raw;
      return mapPosting(p);
    }
    await delay(); return postings.find((p) => p.id === id);
  },

  // ---------- Matches ----------
  async getMatches(includeGhosts = false): Promise<{ items: Match[]; fetching: boolean }> {
    if (!shouldUseMocks()) {
      const url = includeGhosts ? "/matches?include_ghosts=true" : "/matches";
      const raw = await http<any>(url);
      const items: any[] = raw?.data ?? (Array.isArray(raw) ? raw : []);
      return { items: items.map(mapMatch), fetching: raw?.fetching ?? false };
    }
    await delay(); return { items: matches, fetching: false };
  },
  async getMatch(posting_id: string): Promise<Match | undefined> {
    if (!shouldUseMocks()) {
      const raw = await http<any>(`/matches/${posting_id}`);
      const m = raw?.match ?? raw;
      return mapMatch(m);
    }
    await delay(); return matches.find((m) => m.posting.id === posting_id);
  },

  // ---------- Applications ----------
  async getApplications(): Promise<Application[]> {
    if (!shouldUseMocks()) {
      const raw = await http<any>("/applications");
      const items: any[] = raw?.data ?? (Array.isArray(raw) ? raw : []);
      return items.map(mapApplication);
    }
    await delay(); return _applications;
  },
  async setApplicationStatus(id: string, status: ApplicationStatus): Promise<Application | undefined> {
    if (!shouldUseMocks()) {
      const raw = await http<any>(`/applications/${id}`, {
        method: "PUT", body: JSON.stringify({ status }),
      });
      return mapApplication(raw?.application ?? raw);
    }
    await delay(60);
    _applications = _applications.map((a) =>
      a.id === id ? { ...a, status, last_status_at: new Date().toISOString().slice(0, 10) } : a,
    );
    return _applications.find((a) => a.id === id);
  },
  async getArtifact(id: string): Promise<Artifact | undefined> {
    if (!shouldUseMocks()) {
      const raw = await http<any>(`/artifacts/${id}`);
      const a = raw?.artifact ?? raw;
      return {
        id: String(a.id),
        application_id: String(a.application_id),
        type: a.type,
        content: a.content,
        ats_score: a.ats_score ?? 0,
        missing_keywords: a.missing_keywords ?? [],
        grounding_score: a.grounding_score ?? 0,
        predicted_response: a.predicted_response ?? 0,
        version: a.version ?? 1,
        generated_at: a.generated_at ?? new Date().toISOString(),
      };
    }
    await delay();
    for (const a of _applications) {
      const f = a.artifacts.find((x) => x.id === id);
      if (f) return f;
    }
    return undefined;
  },

  async decodePosting(posting_id: string): Promise<{ requirements: string[]; keywords: string[]; summary: string }> {
    if (!shouldUseMocks()) {
      const raw = await http<any>("/applications/decode", {
        method: "POST",
        body: JSON.stringify({ posting_id }),
      });
      return {
        requirements: Array.isArray(raw?.requirements) ? raw.requirements : [],
        keywords: Array.isArray(raw?.keywords) ? raw.keywords : [],
        summary: String(raw?.summary ?? ""),
      };
    }
    await delay(200);
    return { requirements: [], keywords: [], summary: "" };
  },

  async importPosting(url: string): Promise<Posting> {
    if (!shouldUseMocks()) {
      const raw = await http<any>("/postings/import", {
        method: "POST",
        body: JSON.stringify({ url }),
      });
      return mapPosting(raw?.posting ?? raw);
    }
    await delay(500);
    return postings[0];
  },

  async getLatestDraft(posting_id: string): Promise<{ artifact_id: string; content: string; ats_score: number; missing_keywords: string[] } | null> {
    if (!shouldUseMocks()) {
      try {
        const raw = await http<any>(`/applications/draft/latest?posting_id=${posting_id}`);
        if (!raw) return null;
        const a = raw?.artifact ?? raw;
        return {
          artifact_id: String(a.id ?? ""),
          content: String(a.content ?? ""),
          ats_score: Number(a.ats_score ?? 0),
          missing_keywords: Array.isArray(a.missing_keywords) ? a.missing_keywords : [],
        };
      } catch { return null; }
    }
    return null;
  },

  async updateArtifact(artifact_id: string, content: string): Promise<void> {
    if (!shouldUseMocks()) {
      await http<any>(`/artifacts/${artifact_id}`, {
        method: "PUT",
        body: JSON.stringify({ content }),
      });
    }
  },

  async draftCoverLetter(posting_id: string): Promise<{ artifact_id: string; content: string; ats_score: number; missing_keywords: string[] }> {
    if (!shouldUseMocks()) {
      const raw = await http<any>("/applications/draft", {
        method: "POST",
        body: JSON.stringify({ posting_id, type: "cover_letter", channel: "portal" }),
      });
      const a = raw?.artifact ?? raw;
      return {
        artifact_id: String(a.id ?? ""),
        content: String(a.content ?? ""),
        ats_score: Number(a.ats_score ?? 0),
        missing_keywords: Array.isArray(a.missing_keywords) ? a.missing_keywords : [],
      };
    }
    await delay(280);
    return { artifact_id: "", content: "", ats_score: 0, missing_keywords: [] };
  },

  async createApplication(posting_id: string, channel: "portal" | "email" | "referral", artifact_id: string): Promise<Application> {
    if (!shouldUseMocks()) {
      const raw = await http<any>("/applications", {
        method: "POST",
        body: JSON.stringify({ posting_id, channel, artifact_id }),
      });
      return mapApplication(raw?.application ?? raw);
    }
    await delay(120);
    return _applications[0];
  },

  // ---------- Referrals ----------
  async getReferralCandidates(posting_id?: string): Promise<Contact[]> {
    if (!shouldUseMocks()) {
      const qs = posting_id ? `?posting_id=${posting_id}` : "";
      const raw = await http<any>(`/referrals/candidates${qs}`);
      const items: any[] = raw?.data ?? (Array.isArray(raw) ? raw : []);
      return items.map(mapContact);
    }
    await delay(); return contacts;
  },
  async getReferrals(): Promise<Referral[]> {
    if (!shouldUseMocks()) {
      const raw = await http<any>("/referrals");
      const items: any[] = raw?.data ?? (Array.isArray(raw) ? raw : []);
      return items.map(mapReferral);
    }
    await delay(); return _referrals;
  },
  async setReferralStatus(id: string, status: Referral["status"]): Promise<Referral | undefined> {
    if (!shouldUseMocks()) {
      const raw = await http<any>(`/referrals/${id}`, {
        method: "PUT", body: JSON.stringify({ status }),
      });
      return mapReferral(raw?.referral ?? raw);
    }
    await delay(60);
    _referrals = _referrals.map((r) => r.id === id ? { ...r, status } : r);
    return _referrals.find((r) => r.id === id);
  },

  async updatePreferences(prefs: Partial<Profile["preferences"]>): Promise<Profile> {
    if (!shouldUseMocks()) {
      const raw = await http<any>("/profile/preferences", {
        method: "PUT",
        body: JSON.stringify(prefs),
      });
      return mapProfile(raw);
    }
    await delay();
    return { ...profile, preferences: { ...profile.preferences, ...prefs } };
  },

  // ---------- Dashboard ----------
  async getCohortCompanies(): Promise<Array<{ company_name: string; response_rate: number; applied_count: number; note: string }>> {
    if (!shouldUseMocks()) {
      const raw = await http<any>("/dashboard/cohort");
      return Array.isArray(raw?.companies) ? raw.companies : [];
    }
    await delay();
    return [];
  },
  async getDashboard(): Promise<DashboardSummary> {
    if (!shouldUseMocks()) {
      const raw = await http<any>("/dashboard");
      return mapDashboard(raw);
    }
    await delay(); return dashboardSummary;
  },
  async getDashboardDigest(): Promise<{ new_matches: number; followup_due: number; recent_responses: number; ghosts_avoided: number; platform_iq: number }> {
    if (!shouldUseMocks()) return http("/dashboard/digest");
    await delay();
    return { new_matches: 3, followup_due: 1, recent_responses: 0, ghosts_avoided: 23, platform_iq: 78 };
  },
  async getNotifications(): Promise<Notification[]> {
    if (!shouldUseMocks()) return http<Notification[]>("/notifications");
    await delay(); return _notifications;
  },
  async markNotificationRead(id: string): Promise<void> {
    if (!shouldUseMocks()) { await http(`/notifications/${id}/read`, { method: "PUT" }); return; }
    _notifications = _notifications.map((n) => n.id === id ? { ...n, read: true } : n);
  },

  // ---------- Research ----------
  async getResearchOpportunities(): Promise<{ items: ResearchOpportunity[]; fetching: boolean }> {
    if (!shouldUseMocks()) {
      const raw = await http<any>("/research/opportunities");
      const items: any[] = raw?.data ?? (Array.isArray(raw) ? raw : []);
      return { items: items.map(mapResearchOpportunity), fetching: raw?.fetching ?? false };
    }
    await delay(); return { items: researchOpportunities, fetching: false };
  },
  async getResearchOpportunity(id: string): Promise<ResearchOpportunity | undefined> {
    if (!shouldUseMocks()) {
      const raw = await http<any>(`/research/opportunities/${id}`);
      return mapResearchOpportunity(raw);
    }
    await delay(); return researchOpportunities.find((o) => o.id === id);
  },
  async draftResearchPitch(opportunity_id: string): Promise<ResearchPitch> {
    if (!shouldUseMocks()) {
      const raw = await http<any>("/research/pitch", {
        method: "POST", body: JSON.stringify({ opportunity_id }),
      });
      return mapResearchPitch(raw, opportunity_id);
    }
    await delay(280);
    const o = researchOpportunities.find((x) => x.id === opportunity_id)!;
    const firstName = o.professor_name.replace(/^Dr\.?\s*/, "").split(" ")[0];
    return {
      id: `rp_${Date.now()}`,
      opportunity_id,
      subject: `${o.research_area.split("·")[0].trim()} — undergrad inquiry from Berkeley`,
      body:
`Dear ${o.professor_name},

I'm Maya Chen, a third-year EECS student at UC Berkeley. ${o.recent_paper ? `I read "${o.recent_paper.title}" (${o.recent_paper.year}) twice — the` : "The"} section on ${o.research_area.toLowerCase()} matches a problem I've been quietly working on.

In rustpad-mini I shipped a small CRDT-backed editor in Rust + WASM; at Replicate I sent 14 inference PRs that cut p95 on a serving path by 38%. That overlap with what the ${o.lab_name} is doing is why I'm writing.

Would you be open to a 20-minute conversation about a summer research role, or a small concrete project I could try as a trial? I'm happy to send a one-page proposal first.

Thank you for your time,
Maya Chen
maya@berkeley.edu · github.com/maya`,
      generated_at: new Date().toISOString(),
    };
  },
  async getResearchOutreach(): Promise<ResearchOutreach[]> {
    if (!shouldUseMocks()) {
      const raw = await http<any>("/research/outreach");
      const items: any[] = raw?.data ?? (Array.isArray(raw) ? raw : []);
      return items.map(mapResearchOutreach);
    }
    await delay(); return _outreach;
  },
  async saveResearchOutreach(opportunity_id: string, pitch_artifact_id: string | null): Promise<ResearchOutreach> {
    if (!shouldUseMocks()) {
      const raw = await http<any>("/research/outreach", {
        method: "POST",
        body: JSON.stringify({
          opportunity_id,
          pitch_artifact_id: pitch_artifact_id ?? undefined,
        }),
      });
      return mapResearchOutreach(raw);
    }
    await delay(80);
    const o = researchOpportunities.find((x) => x.id === opportunity_id)!;
    const existing = _outreach.find((x) => x.opportunity_id === opportunity_id);
    if (existing) {
      _outreach = _outreach.map((x) => x.opportunity_id === opportunity_id
        ? { ...x, status: "drafted", pitch_id: pitch_artifact_id, last_status_at: new Date().toISOString().slice(0, 10) }
        : x);
      return _outreach.find((x) => x.opportunity_id === opportunity_id)!;
    }
    const created: ResearchOutreach = {
      id: `rx_${Date.now()}`,
      opportunity_id,
      opportunity: { professor_name: o.professor_name, institution: o.institution, lab_name: o.lab_name },
      status: "drafted",
      pitch_id: pitch_artifact_id,
      contacted_at: null,
      replied_at: null,
      last_status_at: new Date().toISOString().slice(0, 10),
    };
    _outreach = [created, ..._outreach];
    return created;
  },
  async setResearchOutreachStatus(id: string, status: ResearchOutreachStatus): Promise<ResearchOutreach | undefined> {
    if (!shouldUseMocks()) {
      const raw = await http<any>(`/research/outreach/${id}`, {
        method: "PUT", body: JSON.stringify({ status }),
      });
      return mapResearchOutreach(raw);
    }
    await delay(60);
    _outreach = _outreach.map((x) => x.id === id
      ? {
          ...x,
          status,
          contacted_at: status === "contacted" ? (x.contacted_at ?? new Date().toISOString().slice(0, 10)) : x.contacted_at,
          replied_at: (status === "replied" || status === "accepted" || status === "declined") ? (x.replied_at ?? new Date().toISOString().slice(0, 10)) : x.replied_at,
          last_status_at: new Date().toISOString().slice(0, 10),
        }
      : x);
    return _outreach.find((x) => x.id === id);
  },
};

// ---------------------------------------------------------------------------
// Tiny React hook for fetching with loading + error states.
// ---------------------------------------------------------------------------
import { useEffect, useState } from "react";

export function useApi<T>(fetcher: () => Promise<T>, deps: any[] = []): {
  data: T | undefined; loading: boolean; error: Error | null; reload: () => void;
} {
  const [data, setData] = useState<T | undefined>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true); setError(null);
    fetcher()
      .then((d) => { if (!cancelled) setData(d); })
      .catch((e) => { if (!cancelled) setError(e instanceof Error ? e : new Error(String(e))); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce]);

  return { data, loading, error, reload: () => setNonce((n) => n + 1) };
}
