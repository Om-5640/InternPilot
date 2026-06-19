import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { CalmBackground } from "@/components/live-background";
import { Nav } from "@/components/nav";
import { api, useApi, isGuestMode, getToken, API_BASE_URL } from "@/lib/api-client";
import { LoadingState, ErrorState } from "@/components/data-states";
import { Upload, Github, ArrowRight, Sparkles, X, Plus, Check, ChevronDown, ChevronUp } from "lucide-react";
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
          {!loading && !error && data && <OnboardingInner initialProfile={data} />}
        </div>
      </main>
    </div>
  );
}

const ALWAYS_USEFUL_GAPS = [
  "Add quantified outcomes to your experience — numbers (%, $, ×) make recruiters stop scrolling",
  "List 2–3 tools or frameworks you're actively learning right now — shows intellectual momentum",
  "Add links to live demos or deployed projects — recruiters spend ~6 seconds per profile",
  "Expand your research interests so the Research feed surfaces relevant lab opportunities",
  "Set target companies in Preferences — the match feed weights companies you've named higher",
];

function OnboardingInner({ initialProfile }: { initialProfile: Profile }) {
  const navigate = useNavigate();
  const guest = isGuestMode();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [profile, setProfile] = useState<Profile>(initialProfile);

  // About you form state
  const [university, setUniversity] = useState(initialProfile.university);
  const [gradYear, setGradYear] = useState(initialProfile.grad_year?.toString() ?? "");
  const [githubUrl, setGithubUrl] = useState(initialProfile.github_url);
  const [skills, setSkills] = useState<string[]>(initialProfile.skills);
  const [newSkill, setNewSkill] = useState("");
  const [interests, setInterests] = useState<string[]>(initialProfile.research_interests);
  const [newInterest, setNewInterest] = useState("");

  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  // Resume state — persist across page loads: if experience or education was parsed, consider done
  const hasResumeData = initialProfile.experience.length > 0 || initialProfile.education.length > 0;
  const [resumeFile, setResumeFile] = useState<File | null>(null);
  const [resumeUploading, setResumeUploading] = useState(false);
  const [resumeError, setResumeError] = useState<string | null>(null);
  const [resumeDone, setResumeDone] = useState(hasResumeData);

  // GitHub state
  const [githubConnecting, setGithubConnecting] = useState(false);
  const [githubError, setGithubError] = useState<string | null>(null);
  const [githubDone, setGithubDone] = useState(!!initialProfile.github_url);

  // Preferences state
  const [prefWorkMode, setPrefWorkMode] = useState<"any" | "remote" | "hybrid" | "onsite">(
    (initialProfile.preferences.work_mode as "any" | "remote" | "hybrid" | "onsite") ?? "any"
  );
  const [prefStipend, setPrefStipend] = useState(String(initialProfile.preferences.stipend_min ?? 0));
  const [prefDuration, setPrefDuration] = useState(String(initialProfile.preferences.duration_months ?? 3));
  const [prefDomains, setPrefDomains] = useState<string[]>(initialProfile.preferences.domains);
  const [prefLocations, setPrefLocations] = useState<string[]>(initialProfile.preferences.locations);
  const [prefTargets, setPrefTargets] = useState<string[]>(initialProfile.preferences.target_companies);
  const [newDomain, setNewDomain] = useState("");
  const [newLocation, setNewLocation] = useState("");
  const [newTarget, setNewTarget] = useState("");
  const [prefSaving, setPrefSaving] = useState(false);
  const [prefSaved, setPrefSaved] = useState(false);
  const [prefError, setPrefError] = useState<string | null>(null);

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
  const addTag = (
    val: string, list: string[], setList: (v: string[]) => void, setCurrent: (v: string) => void
  ) => {
    const v = val.trim();
    if (v && !list.includes(v)) setList([...list, v]);
    setCurrent("");
  };

  const handleSave = async () => {
    gateAction(async () => {
      setSaving(true); setSaveError(null); setSaved(false);
      try {
        const updated = await api.updateProfile({
          university: university || undefined,
          grad_year: gradYear ? parseInt(gradYear, 10) : undefined,
          skills,
          research_interests: interests,
        } as any);
        setProfile(updated);
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
        const token = getToken();
        const res = await fetch(`${API_BASE_URL}/profile/resume`, {
          method: "POST",
          headers: token ? { Authorization: `Bearer ${token}` } : {},
          body: formData,
        });
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          throw new Error(body?.error?.message ?? "Upload failed");
        }
        const updated = await api.getProfile();
        setProfile(updated);

        // Update form fields from extracted data
        if (updated.university) setUniversity(updated.university);
        if (updated.grad_year) setGradYear(String(updated.grad_year));
        if (updated.skills.length > 0) setSkills(updated.skills);
        if (updated.research_interests.length > 0) setInterests(updated.research_interests);

        // Build extraction summary
        const parts: string[] = [];
        if (updated.skills.length > 0) parts.push(`${updated.skills.length} skills`);
        if (updated.experience.length > 0) parts.push(`${updated.experience.length} experience entries`);
        if (updated.education.length > 0) parts.push(`${updated.education.length} education entries`);
        if (updated.projects.length > 0) parts.push(`${updated.projects.length} projects`);
        setExtractedSummary(parts.length > 0 ? `Extracted: ${parts.join(", ")}` : "Résumé parsed — fields updated.");
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
        const updated = await api.importGithub(url);
        setProfile(updated);
        if (updated.skills.length > 0) setSkills(updated.skills);
        setGithubDone(true);
      } catch (e: any) {
        setGithubError(e?.message ?? "Failed to connect GitHub.");
      } finally {
        setGithubConnecting(false);
      }
    });
  };

  const handleSavePreferences = async () => {
    gateAction(async () => {
      setPrefSaving(true); setPrefError(null); setPrefSaved(false);
      try {
        const updated = await api.updatePreferences({
          work_mode: prefWorkMode as any,
          stipend_min: prefStipend ? parseInt(prefStipend, 10) : 0,
          duration_months: prefDuration ? parseInt(prefDuration, 10) : 3,
          domains: prefDomains,
          locations: prefLocations,
          target_companies: prefTargets,
        });
        setProfile(updated);
        setPrefSaved(true);
        setTimeout(() => setPrefSaved(false), 3000);
      } catch (e: any) {
        setPrefError(e?.message ?? "Failed to save preferences.");
      } finally {
        setPrefSaving(false);
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
          <p className="text-sm text-muted-foreground mt-1">PDF or DOCX, max 5 MB. We extract skills, experience, and education automatically.</p>
          {resumeDone ? (
            <div className="mt-5 space-y-4">
              <div className="flex items-center gap-2 text-sm font-medium" style={{ color: "var(--color-primary)" }}>
                <Check className="h-4 w-4" /> Résumé parsed — here's what we extracted:
              </div>

              {profile.skills.length > 0 && (
                <div className="rounded-xl border p-4" style={{ borderColor: "var(--color-hairline)" }}>
                  <div className="text-xs uppercase tracking-[0.14em] text-muted-foreground mb-2">Skills detected ({profile.skills.length})</div>
                  <div className="flex flex-wrap gap-1.5">
                    {profile.skills.slice(0, 20).map((s) => <Pill key={s}>{s}</Pill>)}
                    {profile.skills.length > 20 && <span className="text-xs text-muted-foreground self-center">+{profile.skills.length - 20} more</span>}
                  </div>
                </div>
              )}

              {profile.experience.length > 0 && (
                <div className="rounded-xl border p-4" style={{ borderColor: "var(--color-hairline)" }}>
                  <div className="text-xs uppercase tracking-[0.14em] text-muted-foreground mb-2">Experience ({profile.experience.length} entries)</div>
                  <ul className="space-y-2 text-sm">
                    {profile.experience.map((e: any, i: number) => (
                      <li key={i} className="flex gap-2 text-muted-foreground">
                        <span className="font-mono text-xs mt-0.5">·</span>
                        <span><strong className="text-foreground">{e.title}</strong>{e.org ? ` at ${e.org}` : ""}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {profile.education.length > 0 && (
                <div className="rounded-xl border p-4" style={{ borderColor: "var(--color-hairline)" }}>
                  <div className="text-xs uppercase tracking-[0.14em] text-muted-foreground mb-2">Education</div>
                  <ul className="space-y-1.5 text-sm">
                    {profile.education.map((e: any, i: number) => (
                      <li key={i} className="text-muted-foreground">
                        <strong className="text-foreground">{e.degree}</strong>{e.institution ? ` · ${e.institution}` : ""}
                        {e.year ? ` · ${e.year}` : ""}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {profile.research_interests.length > 0 && (
                <div className="rounded-xl border p-4" style={{ borderColor: "var(--color-hairline)" }}>
                  <div className="text-xs uppercase tracking-[0.14em] text-muted-foreground mb-2">Research interests</div>
                  <div className="flex flex-wrap gap-1.5">
                    {profile.research_interests.map((r) => (
                      <span key={r} className="inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium"
                            style={{ background: "var(--color-primary-tint)", color: "var(--color-primary)" }}>
                        {r}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              <button
                onClick={() => { setResumeDone(false); setExtractedSummary(null); }}
                className="text-xs text-muted-foreground underline"
              >
                Upload a different résumé
              </button>
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
                  {resumeUploading ? "Parsing résumé…" : "Parse résumé"}
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
            <div className="mt-5 space-y-4">
              <div className="flex items-center gap-2 text-sm font-medium" style={{ color: "var(--color-primary)" }}>
                <Check className="h-4 w-4" /> GitHub connected —{" "}
                <a href={githubUrl || profile.github_url} target="_blank" rel="noreferrer"
                   className="underline text-sm" style={{ color: "var(--color-primary)" }}>
                  {githubUrl || profile.github_url}
                </a>
              </div>

              {profile.projects.length > 0 && (
                <div className="rounded-xl border p-4 space-y-3" style={{ borderColor: "var(--color-hairline)" }}>
                  <div className="text-xs uppercase tracking-[0.14em] text-muted-foreground">
                    Projects fetched from GitHub ({profile.projects.length})
                  </div>
                  {profile.projects.map((p) => (
                    <div key={p.name} className="rounded-lg border bg-white p-3" style={{ borderColor: "var(--color-hairline)" }}>
                      <div className="flex items-start justify-between gap-2">
                        <div className="font-medium text-sm">
                          {p.url
                            ? <a href={p.url} target="_blank" rel="noreferrer" className="hover:underline">{p.name}</a>
                            : p.name}
                        </div>
                        <div className="flex flex-wrap gap-1 shrink-0">
                          {p.tech.slice(0, 3).map((t) => <Pill key={t}>{t}</Pill>)}
                          {p.tech.length > 3 && <span className="text-xs text-muted-foreground self-center">+{p.tech.length - 3}</span>}
                        </div>
                      </div>
                      {p.description && (
                        <p className="mt-1.5 text-xs text-muted-foreground leading-relaxed">{p.description}</p>
                      )}
                    </div>
                  ))}
                </div>
              )}

              <button
                onClick={() => setGithubDone(false)}
                className="text-xs text-muted-foreground underline"
              >
                Connect a different account
              </button>
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

        {/* Preferences — fully editable */}
        <div className="card-soft p-8">
          <h2 className="font-display text-xl">Preferences</h2>
          <div className="mt-5 grid sm:grid-cols-2 gap-6 text-sm">
            <Field label="Work mode">
              <div className="flex flex-wrap gap-2">
                {["any", "remote", "hybrid", "onsite"].map((m) => (
                  <button
                    key={m}
                    onClick={() => setPrefWorkMode(m as "any" | "remote" | "hybrid" | "onsite")}
                    className={`rounded-full border px-3 py-1.5 text-xs font-medium transition focus:outline-none focus-visible:ring-2 ${prefWorkMode === m ? "bg-primary text-primary-foreground border-primary" : "bg-white text-muted-foreground hover:bg-secondary"}`}
                    style={{ borderColor: prefWorkMode === m ? undefined : "var(--color-hairline)" }}
                  >
                    {m}
                  </button>
                ))}
              </div>
            </Field>
            <Field label="Min stipend ($/mo)">
              <input
                type="number"
                value={prefStipend}
                onChange={(e) => setPrefStipend(e.target.value)}
                placeholder="0"
                min={0}
                className="w-full rounded-lg border bg-white px-3 py-2 text-sm font-mono focus:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--ring)]"
                style={{ borderColor: "var(--color-hairline)" }}
              />
            </Field>
            <Field label="Duration (months)">
              <input
                type="number"
                value={prefDuration}
                onChange={(e) => setPrefDuration(e.target.value)}
                placeholder="3"
                min={1}
                max={24}
                className="w-full rounded-lg border bg-white px-3 py-2 text-sm font-mono focus:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--ring)]"
                style={{ borderColor: "var(--color-hairline)" }}
              />
            </Field>
            <Field label="Domains">
              <TagInput tags={prefDomains} setTags={setPrefDomains} value={newDomain} setValue={setNewDomain} placeholder="e.g. ML, Web" onAdd={() => addTag(newDomain, prefDomains, setPrefDomains, setNewDomain)} />
            </Field>
            <Field label="Locations">
              <TagInput tags={prefLocations} setTags={setPrefLocations} value={newLocation} setValue={setNewLocation} placeholder="e.g. SF, Remote" onAdd={() => addTag(newLocation, prefLocations, setPrefLocations, setNewLocation)} />
            </Field>
            <Field label="Target companies">
              <TagInput tags={prefTargets} setTags={setPrefTargets} value={newTarget} setValue={setNewTarget} placeholder="e.g. Anthropic" onAdd={() => addTag(newTarget, prefTargets, setPrefTargets, setNewTarget)} tone="warm" />
            </Field>
          </div>

          <div className="mt-6 flex items-center gap-3">
            <button
              onClick={handleSavePreferences}
              disabled={prefSaving}
              className="inline-flex items-center gap-2 rounded-full bg-primary px-5 py-2 text-sm font-medium text-primary-foreground hover:bg-[color:var(--primary-hover)] transition disabled:opacity-60"
            >
              {prefSaving ? "Saving…" : prefSaved ? <><Check className="h-4 w-4" /> Saved</> : "Save preferences"}
            </button>
            {prefError && <span className="text-xs" style={{ color: "var(--color-reject)" }}>{prefError}</span>}
          </div>
        </div>
      </div>

      {/* Sidebar — fixed-width right column, no sticky, no scroll */}
      <aside className="card-soft p-5 h-fit space-y-5">
        {/* Profile strength ring */}
        <div>
          <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground font-mono">Profile strength</div>
          <StrengthMeter value={profile.profile_strength} />
        </div>

        {/* Quick snapshot */}
        <div className="rounded-xl p-3 space-y-2" style={{ background: "var(--color-surface)" }}>
          <div className="text-xs uppercase tracking-[0.14em] text-muted-foreground mb-1">What we know</div>
          <ProfileStat label="Skills" count={profile.skills.length} good={profile.skills.length >= 5} hint="upload résumé" />
          <ProfileStat label="Experience" count={profile.experience.length} good={profile.experience.length >= 1} hint="upload résumé" />
          <ProfileStat label="Education" count={profile.education.length} good={profile.education.length >= 1} hint="upload résumé" />
          <ProfileStat label="Projects" count={profile.projects.length} good={profile.projects.length >= 2} hint="connect GitHub" />
          <div className="flex items-center justify-between text-xs">
            <span className="text-muted-foreground">GitHub</span>
            {profile.github_url
              ? <span className="font-medium" style={{ color: "var(--color-primary)" }}>Connected</span>
              : <span className="text-muted-foreground italic">not set</span>}
          </div>
        </div>

        {/* Top skills — cap at 8 so pills never wrap past 2 rows */}
        {profile.skills.length > 0 && (
          <div>
            <div className="text-xs uppercase tracking-[0.14em] text-muted-foreground mb-1.5">Top skills</div>
            <div className="flex flex-wrap gap-1">
              {profile.skills.slice(0, 8).map((s) => <Pill key={s}>{s}</Pill>)}
              {profile.skills.length > 8 && (
                <span className="text-xs text-muted-foreground self-center">+{profile.skills.length - 8}</span>
              )}
            </div>
          </div>
        )}

        {/* Improvement gaps — 3 items keeps the sidebar height predictable */}
        <div>
          <div className="text-xs font-medium flex items-center gap-1.5 mb-2" style={{ color: "var(--color-primary)" }}>
            <Sparkles className="h-3.5 w-3.5" /> Always room to grow
          </div>
          <ul className="space-y-1.5">
            {(profile.gaps.length > 0 ? profile.gaps : ALWAYS_USEFUL_GAPS).slice(0, 3).map((g, i) => (
              <GapItem key={g} gap={g} index={i} />
            ))}
          </ul>
        </div>

        <Link
          to="/feed"
          className="w-full inline-flex items-center justify-center gap-2 rounded-full bg-primary px-5 py-2.5 text-sm font-medium text-primary-foreground hover:bg-[color:var(--primary-hover)]"
        >
          See my match feed <ArrowRight className="h-4 w-4" />
        </Link>
      </aside>
    </div>
  );
}

function TagInput({
  tags, setTags, value, setValue, placeholder, onAdd, tone,
}: {
  tags: string[];
  setTags: (v: string[]) => void;
  value: string;
  setValue: (v: string) => void;
  placeholder: string;
  onAdd: () => void;
  tone?: "primary" | "warm";
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {tags.map((t) => (
        <span
          key={t}
          className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-medium ${tone === "warm" ? "" : tone === "primary" ? "" : "bg-secondary"}`}
          style={
            tone === "primary" ? { background: "var(--color-primary-tint)", color: "var(--color-primary)" }
            : tone === "warm" ? { background: "var(--color-warm-tint)", color: "var(--color-warm)" }
            : {}
          }
        >
          {t}
          <button onClick={() => setTags(tags.filter((x) => x !== t))} className="hover:opacity-70">
            <X className="h-3 w-3" />
          </button>
        </span>
      ))}
      <div className="flex gap-1">
        <input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), onAdd())}
          placeholder={placeholder}
          className="rounded-full border bg-white px-2.5 py-1 text-xs focus:outline-none focus-visible:ring-1"
          style={{ borderColor: "var(--color-hairline)", width: "100px" }}
        />
        <button onClick={onAdd} className="text-muted-foreground hover:text-foreground">
          <Plus className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}

function ProfileStat({ label, count, good, hint }: { label: string; count: number; good: boolean; hint: string }) {
  return (
    <div className="flex items-center justify-between text-xs">
      <span className="text-muted-foreground">{label}</span>
      {count > 0
        ? <span className={`font-mono font-semibold ${good ? "" : "text-[color:var(--color-warm)]"}`} style={good ? { color: "var(--color-primary)" } : {}}>
            {count} {good ? "✓" : ""}
          </span>
        : <span className="italic text-muted-foreground">{hint}</span>}
    </div>
  );
}

function GapItem({ gap, index }: { gap: string; index: number }) {
  const [expanded, setExpanded] = useState(false);
  const guidance = getGapGuidance(gap);

  return (
    <li className="rounded-lg border px-2.5 py-2" style={{ borderColor: "var(--color-hairline)" }}>
      <div className="flex items-start justify-between gap-1.5">
        <div className="flex gap-2 items-start min-w-0">
          <span className="shrink-0 mt-0.5 font-mono text-[10px] text-muted-foreground">{String(index + 1).padStart(2, "0")}</span>
          <span className="text-muted-foreground text-xs leading-snug">{gap}</span>
        </div>
        {guidance && (
          <button
            onClick={() => setExpanded((o) => !o)}
            className="shrink-0 text-[10px] text-muted-foreground hover:text-foreground underline flex items-center gap-0.5 mt-0.5"
          >
            {expanded ? <>less <ChevronUp className="h-2.5 w-2.5" /></> : <>more <ChevronDown className="h-2.5 w-2.5" /></>}
          </button>
        )}
      </div>
      {expanded && guidance && (
        <div className="mt-2 rounded p-2 text-[10px] text-muted-foreground leading-relaxed" style={{ background: "var(--color-surface)" }}>
          {guidance}
        </div>
      )}
    </li>
  );
}

function getGapGuidance(gap: string): string {
  const lower = gap.toLowerCase();
  if (lower.includes("résumé") || lower.includes("resume"))
    return "Upload your résumé above so we can parse your experience, skills, and education automatically. This alone can raise your profile strength by 25+ points.";
  if (lower.includes("github"))
    return "Connect your GitHub profile above. We scan your repos for real languages and project complexity — recruiters trust hands-on work more than listed skills.";
  if (lower.includes("skill"))
    return "Add at least 5 concrete technical skills (languages, frameworks, tools) in the About you section. More specific = better match ranking.";
  if (lower.includes("project"))
    return "Projects with a live URL or GitHub link are weighted heavily in match scoring. Make sure your GitHub is connected so we can pull these automatically.";
  if (lower.includes("experience"))
    return "Add at least one internship, research role, or part-time job. Even a 2-month stint counts — companies want to see you can work in a professional environment.";
  if (lower.includes("university") || lower.includes("education"))
    return "Fill in your university and graduation year in the About you section. Many roles filter by institution or grad year range.";
  if (lower.includes("preference"))
    return "Set your work mode, stipend floor, and target domains in the Preferences section. This directly shapes which matches appear in your feed.";
  return "Completing this section improves your profile strength and match accuracy. Use the form above to update your details.";
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
  const size = 140, r = 58, c = 2 * Math.PI * r;
  return (
    <div className="relative mt-3 grid place-items-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={value} aria-label="Profile strength">
        <circle cx={size / 2} cy={size / 2} r={r} stroke="var(--color-hairline)" strokeWidth="9" fill="none" />
        <circle cx={size / 2} cy={size / 2} r={r}
                stroke="var(--color-primary)" strokeWidth="9" fill="none" strokeLinecap="round"
                strokeDasharray={c} strokeDashoffset={c - (c * value) / 100} />
      </svg>
      <div className="absolute inset-0 grid place-items-center">
        <div className="text-center">
          <div className="font-display text-4xl font-medium">{value}</div>
          <div className="font-mono text-[10px] uppercase tracking-[0.2em] text-muted-foreground mt-0.5">/ 100</div>
        </div>
      </div>
    </div>
  );
}
