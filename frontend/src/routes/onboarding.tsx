import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { CalmBackground } from "@/components/live-background";
import { Nav } from "@/components/nav";
import { api, useApi, isGuestMode } from "@/lib/api-client";
import { LoadingState, ErrorState } from "@/components/data-states";
import { Upload, Github, ArrowRight, Sparkles, X, Plus, Check } from "lucide-react";
import { Pill } from "@/components/ui-bits";
import type { Profile } from "@/lib/mocks";
import { useState, useRef, useCallback } from "react";

export const Route = createFileRoute("/onboarding")({
  head: () => ({ meta: [{ title: "Build your Career Twin — InternPilot" }, { name: "description", content: "Set up your Career Twin in two minutes." }] }),
  component: Onboarding,
});

function GuestBanner() {
  const navigate = useNavigate();
  return (
    <div className="mb-8 flex items-center justify-between rounded-xl border bg-[color-mix(in_oklab,var(--color-primary)_8%,white)] px-5 py-3.5"
         style={{ borderColor: "color-mix(in oklab, var(--color-primary) 30%, transparent)" }}>
      <p className="text-sm" style={{ color: "var(--color-primary)" }}>
        <strong>Browsing as guest.</strong> Sign up to save your profile and unlock personalized matches.
      </p>
      <button
        onClick={() => navigate({ to: "/auth" })}
        className="ml-4 shrink-0 inline-flex items-center gap-1.5 rounded-full bg-primary px-4 py-1.5 text-xs font-medium text-primary-foreground"
      >
        Sign up free <ArrowRight className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}

function Onboarding() {
  const { data, loading, error, reload } = useApi(() => api.getProfile(), []);

  return (
    <div className="min-h-screen">
      <CalmBackground />
      <Nav />
      <main className="mx-auto max-w-6xl px-6 py-16">
        <div className="font-mono text-xs uppercase tracking-[0.18em] text-muted-foreground">Step 1 of 3 · Career Twin</div>
        <h1 className="mt-3 font-display text-5xl md:text-6xl font-medium tracking-tight text-balance">
          Tell us what you&apos;ve actually shipped.
        </h1>
        <p className="mt-4 max-w-xl text-muted-foreground">
          The more honest your inputs, the sharper your match feed. We never spray your applications — you approve every send.
        </p>

        <div className="mt-12">
          {loading && <LoadingState label="Loading your profile" />}
          {error && <ErrorState error={error} onRetry={reload} />}
          {!loading && !error && data && <OnboardingInner profile={data} />}
        </div>
      </main>
    </div>
  );
}

function OnboardingInner({ profile }: { profile: Profile }) {
  const navigate = useNavigate();
  const guest = isGuestMode();
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Controlled form state
  const [university, setUniversity] = useState(profile.university);
  const [gradYear, setGradYear] = useState(profile.grad_year?.toString() ?? "");
  const [githubUrl, setGithubUrl] = useState(profile.github_url);
  const [skills, setSkills] = useState<string[]>(profile.skills);
  const [newSkill, setNewSkill] = useState("");
  const [interests, setInterests] = useState<string[]>(profile.research_interests);
  const [newInterest, setNewInterest] = useState("");

  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const [resumeFile, setResumeFile] = useState<File | null>(null);
  const [resumeUploading, setResumeUploading] = useState(false);
  const [resumeError, setResumeError] = useState<string | null>(null);
  const [resumeDone, setResumeDone] = useState(false);

  const [githubConnecting, setGithubConnecting] = useState(false);
  const [githubError, setGithubError] = useState<string | null>(null);
  const [githubDone, setGithubDone] = useState(!!profile.github_url);

  const gateAction = useCallback((action: () => void) => {
    if (guest) { navigate({ to: "/auth" }); return; }
    action();
  }, [guest, navigate]);

  const addSkill = () => {
    const v = newSkill.trim();
    if (v && !skills.includes(v)) setSkills([...skills, v]);
    setNewSkill("");
  };

  const addInterest = () => {
    const v = newInterest.trim();
    if (v && !interests.includes(v)) setInterests([...interests, v]);
    setNewInterest("");
  };

  const handleSave = async () => {
    gateAction(async () => {
      setSaving(true); setSaveError(null); setSaved(false);
      try {
        await api.updateProfile({
          university: university || undefined,
          grad_year: gradYear ? parseInt(gradYear, 10) : undefined,
          skills,
          research_interests: interests,
        } as any);
        setSaved(true);
        setTimeout(() => setSaved(false), 3000);
      } catch (e: any) {
        setSaveError(e?.message ?? "Failed to save profile.");
      } finally {
        setSaving(false);
      }
    });
  };

  const handleResumeChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    gateAction(() => setResumeFile(file));
  };

  const handleResumeUpload = async () => {
    if (!resumeFile) return;
    gateAction(async () => {
      setResumeUploading(true); setResumeError(null);
      try {
        const formData = new FormData();
        formData.append("file", resumeFile);
        const { getToken } = await import("@/lib/api-client");
        const token = getToken();
        const { API_BASE_URL } = await import("@/lib/api-client");
        const res = await fetch(`${API_BASE_URL}/profile/resume`, {
          method: "POST",
          headers: token ? { Authorization: `Bearer ${token}` } : {},
          body: formData,
        });
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          throw new Error(body?.error?.message ?? "Upload failed");
        }
        setResumeDone(true);
        setResumeFile(null);
      } catch (e: any) {
        setResumeError(e?.message ?? "Upload failed.");
      } finally {
        setResumeUploading(false);
      }
    });
  };

  const handleGithubConnect = async () => {
    const url = githubUrl.trim();
    if (!url) { setGithubError("Enter your GitHub profile URL."); return; }
    gateAction(async () => {
      setGithubConnecting(true); setGithubError(null);
      try {
        await api.updateProfile({ github_url: url } as any);
        setGithubDone(true);
      } catch (e: any) {
        setGithubError(e?.message ?? "Failed to connect GitHub.");
      } finally {
        setGithubConnecting(false);
      }
    });
  };

  return (
    <div className="grid gap-6 md:grid-cols-3">
      <div className="md:col-span-2 grid gap-6">
        {guest && <GuestBanner />}

        {/* Resume */}
        <div className="card-soft p-8">
          <h2 className="font-display text-xl">Résumé</h2>
          <p className="text-sm text-muted-foreground mt-1">PDF or DOCX, max 5 MB.</p>
          {resumeDone ? (
            <div className="mt-5 flex items-center gap-2 text-sm" style={{ color: "var(--color-primary)" }}>
              <Check className="h-4 w-4" /> Résumé parsed successfully
            </div>
          ) : (
            <>
              <label
                className="mt-5 block rounded-xl border border-dashed p-10 text-center cursor-pointer hover:bg-secondary transition focus-within:ring-2 focus-within:ring-[color:var(--ring)]"
                style={{ borderColor: "var(--color-hairline)" }}
              >
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".pdf,.docx"
                  className="sr-only"
                  onChange={handleResumeChange}
                />
                <Upload className="mx-auto h-6 w-6 text-muted-foreground" />
                <div className="mt-3 text-sm">
                  {resumeFile ? resumeFile.name : "Drop your résumé here, or click to browse"}
                </div>
                <div className="mt-1 text-xs text-muted-foreground font-mono">
                  {resumeFile ? `${(resumeFile.size / 1024).toFixed(0)} KB` : "PDF · DOCX · max 5 MB"}
                </div>
              </label>
              {resumeFile && (
                <button
                  onClick={handleResumeUpload}
                  disabled={resumeUploading}
                  className="mt-3 inline-flex items-center gap-2 rounded-full bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-60"
                >
                  {resumeUploading ? "Parsing…" : "Parse résumé"}
                </button>
              )}
              {resumeError && <p className="mt-2 text-xs" style={{ color: "var(--color-reject)" }}>{resumeError}</p>}
            </>
          )}
        </div>

        {/* GitHub */}
        <div className="card-soft p-8">
          <h2 className="font-display text-xl">Connect GitHub</h2>
          <p className="text-sm text-muted-foreground mt-1">We read your repos to ground every application in your real work.</p>
          {githubDone ? (
            <div className="mt-5 flex items-center gap-2 text-sm" style={{ color: "var(--color-primary)" }}>
              <Check className="h-4 w-4" /> GitHub connected — {githubUrl || profile.github_url}
            </div>
          ) : (
            <div className="mt-5 flex gap-2">
              <input
                type="url"
                value={githubUrl}
                onChange={(e) => setGithubUrl(e.target.value)}
                placeholder="https://github.com/yourname"
                className="flex-1 rounded-xl border bg-white px-4 py-2.5 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--ring)]"
                style={{ borderColor: "var(--color-hairline)" }}
              />
              <button
                onClick={handleGithubConnect}
                disabled={githubConnecting}
                className="inline-flex items-center gap-2 rounded-full border bg-foreground text-background px-5 py-2.5 text-sm font-medium disabled:opacity-60"
                style={{ borderColor: "var(--color-hairline)" }}
              >
                <Github className="h-4 w-4" /> {githubConnecting ? "Connecting…" : "Connect"}
              </button>
            </div>
          )}
          {githubError && <p className="mt-2 text-xs" style={{ color: "var(--color-reject)" }}>{githubError}</p>}
          {profile.projects.length > 0 && (
            <div className="mt-5 grid gap-3">
              {profile.projects.map((p) => (
                <div key={p.name} className="flex items-center justify-between rounded-lg border bg-surface px-4 py-3" style={{ borderColor: "var(--color-hairline)" }}>
                  <div className="min-w-0">
                    <div className="font-medium text-sm">
                      {p.url ? <a href={p.url} target="_blank" rel="noreferrer" className="hover:underline">{p.name}</a> : p.name}
                    </div>
                    <div className="text-xs text-muted-foreground truncate">{p.description}</div>
                  </div>
                  <div className="flex gap-1.5 shrink-0">{p.tech.map((s) => <Pill key={s}>{s}</Pill>)}</div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* About you */}
        <div className="card-soft p-8">
          <h2 className="font-display text-xl">About you</h2>
          <div className="mt-5 grid sm:grid-cols-2 gap-5 text-sm">
            <Field label="University">
              <input
                value={university}
                onChange={(e) => setUniversity(e.target.value)}
                placeholder="e.g. IIT Delhi"
                className="w-full rounded-lg border bg-white px-3 py-2 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--ring)]"
                style={{ borderColor: "var(--color-hairline)" }}
              />
            </Field>
            <Field label="Graduation year">
              <input
                type="number"
                value={gradYear}
                onChange={(e) => setGradYear(e.target.value)}
                placeholder="e.g. 2026"
                className="w-full rounded-lg border bg-white px-3 py-2 text-sm font-mono focus:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--ring)]"
                style={{ borderColor: "var(--color-hairline)" }}
              />
            </Field>
            <Field label="Skills">
              <div className="flex flex-wrap gap-1.5">
                {skills.map((s) => (
                  <span key={s} className="inline-flex items-center gap-1 rounded-full bg-secondary px-2.5 py-1 text-xs font-medium">
                    {s}
                    <button onClick={() => setSkills(skills.filter((x) => x !== s))} className="hover:text-foreground">
                      <X className="h-3 w-3" />
                    </button>
                  </span>
                ))}
                <div className="flex gap-1">
                  <input
                    value={newSkill}
                    onChange={(e) => setNewSkill(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), addSkill())}
                    placeholder="Add skill"
                    className="rounded-full border bg-white px-2.5 py-1 text-xs focus:outline-none focus-visible:ring-1"
                    style={{ borderColor: "var(--color-hairline)", width: "90px" }}
                  />
                  <button onClick={addSkill} className="text-muted-foreground hover:text-foreground">
                    <Plus className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
            </Field>
            <Field label="Research interests">
              <div className="flex flex-wrap gap-1.5">
                {interests.map((r) => (
                  <span key={r} className="inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-medium"
                        style={{ background: "var(--color-primary-tint)", color: "var(--color-primary)" }}>
                    {r}
                    <button onClick={() => setInterests(interests.filter((x) => x !== r))} className="hover:opacity-70">
                      <X className="h-3 w-3" />
                    </button>
                  </span>
                ))}
                <div className="flex gap-1">
                  <input
                    value={newInterest}
                    onChange={(e) => setNewInterest(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), addInterest())}
                    placeholder="Add topic"
                    className="rounded-full border bg-white px-2.5 py-1 text-xs focus:outline-none focus-visible:ring-1"
                    style={{ borderColor: "var(--color-hairline)", width: "90px" }}
                  />
                  <button onClick={addInterest} className="text-muted-foreground hover:text-foreground">
                    <Plus className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
            </Field>
          </div>

          <div className="mt-6 flex items-center gap-3">
            <button
              onClick={handleSave}
              disabled={saving}
              className="inline-flex items-center gap-2 rounded-full bg-primary px-5 py-2 text-sm font-medium text-primary-foreground hover:bg-[color:var(--primary-hover)] transition disabled:opacity-60"
            >
              {saving ? "Saving…" : saved ? <><Check className="h-4 w-4" /> Saved</> : "Save changes"}
            </button>
            {saveError && <span className="text-xs" style={{ color: "var(--color-reject)" }}>{saveError}</span>}
          </div>
        </div>

        {/* Preferences (read-only display for now) */}
        <div className="card-soft p-8">
          <h2 className="font-display text-xl">Preferences</h2>
          <div className="mt-5 grid sm:grid-cols-2 gap-5 text-sm">
            <Field label="Work mode"><Pill>{profile.preferences.work_mode}</Pill></Field>
            <Field label="Stipend min">
              <span className="font-mono">${(profile.preferences.stipend_min ?? 0).toLocaleString()}/mo</span>
            </Field>
            <Field label="Duration">
              <span className="font-mono">{profile.preferences.duration_months ?? 3} months</span>
            </Field>
            {profile.preferences.domains.length > 0 && (
              <Field label="Domains">
                <div className="flex flex-wrap gap-1.5">{profile.preferences.domains.map((d) => <Pill key={d} tone="primary">{d}</Pill>)}</div>
              </Field>
            )}
            {profile.preferences.locations.length > 0 && (
              <Field label="Locations">
                <div className="flex flex-wrap gap-1.5">{profile.preferences.locations.map((l) => <Pill key={l}>{l}</Pill>)}</div>
              </Field>
            )}
            {profile.preferences.target_companies.length > 0 && (
              <Field label="Target companies">
                <div className="flex flex-wrap gap-1.5">{profile.preferences.target_companies.map((c) => <Pill key={c} tone="warm">{c}</Pill>)}</div>
              </Field>
            )}
          </div>
        </div>
      </div>

      <aside className="card-soft p-8 h-fit sticky top-24">
        <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground font-mono">Profile strength</div>
        <StrengthMeter value={profile.profile_strength} />
        {profile.gaps.length > 0 && (
          <div className="mt-6">
            <div className="text-sm font-medium flex items-center gap-2">
              <Sparkles className="h-4 w-4" style={{ color: "var(--color-primary)" }} /> Gaps to fix
            </div>
            <ul className="mt-3 space-y-2.5 text-sm">
              {profile.gaps.map((g, i) => (
                <li key={g} className="flex gap-2.5">
                  <span className="mt-0.5 font-mono text-xs text-muted-foreground">{String(i + 1).padStart(2, "0")}</span>
                  <span className="text-muted-foreground">{g}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
        <Link
          to="/feed"
          className="mt-8 w-full inline-flex items-center justify-center gap-2 rounded-full bg-primary px-5 py-3 text-sm font-medium text-primary-foreground hover:bg-[color:var(--primary-hover)]"
        >
          See my match feed <ArrowRight className="h-4 w-4" />
        </Link>
      </aside>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-[0.14em] text-muted-foreground mb-2">{label}</div>
      {children}
    </div>
  );
}

function StrengthMeter({ value }: { value: number }) {
  const size = 180, r = 78, c = 2 * Math.PI * r;
  return (
    <div className="relative mt-4 grid place-items-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={value} aria-label="Profile strength">
        <circle cx={size / 2} cy={size / 2} r={r} stroke="var(--color-hairline)" strokeWidth="10" fill="none" />
        <circle cx={size / 2} cy={size / 2} r={r}
                stroke="var(--color-primary)" strokeWidth="10" fill="none" strokeLinecap="round"
                strokeDasharray={c} strokeDashoffset={c - (c * value) / 100} />
      </svg>
      <div className="absolute inset-0 grid place-items-center">
        <div className="text-center">
          <div className="font-display text-5xl font-medium">{value}</div>
          <div className="font-mono text-[10px] uppercase tracking-[0.2em] text-muted-foreground mt-1">/ 100</div>
        </div>
      </div>
    </div>
  );
}
