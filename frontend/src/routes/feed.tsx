import { createFileRoute, Link } from "@tanstack/react-router";
import { useState } from "react";
import { CalmBackground } from "@/components/live-background";
import { Nav } from "@/components/nav";
import { api, useApi } from "@/lib/api-client";
import { GhostBadge, MatchRing, Pill } from "@/components/ui-bits";
import { LoadingState, EmptyState, ErrorState } from "@/components/data-states";
import { ArrowUpRight, SlidersHorizontal, Users, MapPin, DollarSign, Ghost, FlaskConical, Briefcase, Sparkles, Link2, UserCircle } from "lucide-react";
import { motion } from "framer-motion";
import type { Match, ResearchOpportunity } from "@/lib/mocks";

export const Route = createFileRoute("/feed")({
  head: () => ({ meta: [{ title: "Match feed — InternPilot" }, { name: "description", content: "Roles you can actually win." }] }),
  component: Feed,
});

type SortKey = "match" | "ev" | "response";
type Mode = "company" | "research";

function Feed() {
  const [mode, setMode] = useState<Mode>("company");
  return (
    <div className="min-h-screen">
      <CalmBackground />
      <Nav />
      <main className="mx-auto max-w-7xl px-6 py-12">
        <div className="flex flex-wrap items-end justify-between gap-6">
          <div>
            <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground font-mono">Two feeds, one signal</div>
            <h1 className="mt-2 font-display text-5xl md:text-6xl font-medium tracking-tight">Roles you can win.</h1>
          </div>
          <ModeToggle mode={mode} onChange={setMode} />
        </div>
        <div className="mt-10">
          {mode === "company" ? <CompanyFeed /> : <ResearchFeed />}
        </div>
      </main>
    </div>
  );
}

function ModeToggle({ mode, onChange }: { mode: Mode; onChange: (m: Mode) => void }) {
  return (
    <div className="inline-flex rounded-full border bg-white p-1" style={{ borderColor: "var(--color-hairline)" }}>
      {([
        { k: "company" as const, label: "Company", icon: Briefcase },
        { k: "research" as const, label: "Research", icon: FlaskConical },
      ]).map((o) => (
        <button
          key={o.k}
          onClick={() => onChange(o.k)}
          className={`inline-flex items-center gap-1.5 rounded-full px-4 py-2 text-sm transition focus:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--ring)] ${mode === o.k ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"}`}
          aria-pressed={mode === o.k}
        >
          <o.icon className="h-3.5 w-3.5" />
          {o.label}
        </button>
      ))}
    </div>
  );
}

const WORK_MODES = ["remote", "hybrid", "onsite"] as const;

function ImportBox({ onImported }: { onImported: () => void }) {
  const [url, setUrl] = useState("");
  const [importing, setImporting] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!url.trim()) return;
    setImporting(true); setErr(null);
    try {
      await api.importPosting(url.trim());
      setUrl("");
      onImported();
    } catch (ex: any) {
      setErr(ex?.message ?? "Import failed.");
    } finally {
      setImporting(false);
    }
  };

  return (
    <div className="card-soft p-6 mt-4">
      <div className="text-xs uppercase tracking-[0.14em] text-muted-foreground font-mono mb-3">Paste a job URL to add it</div>
      <form onSubmit={submit} className="flex gap-2">
        <input
          type="url"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://jobs.lever.co/... or any posting URL"
          className="flex-1 rounded-xl border bg-white px-4 py-2.5 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--ring)]"
          style={{ borderColor: "var(--color-hairline)" }}
        />
        <button
          type="submit"
          disabled={importing || !url.trim()}
          className="inline-flex items-center gap-1.5 rounded-full bg-primary text-primary-foreground px-4 py-2 text-xs font-medium hover:bg-[color:var(--primary-hover)] disabled:opacity-60"
        >
          <Link2 className="h-3.5 w-3.5" /> {importing ? "Importing…" : "Import"}
        </button>
      </form>
      {err && <p className="mt-2 text-xs" style={{ color: "var(--color-reject)" }}>{err}</p>}
    </div>
  );
}

function CompanyFeed() {
  const [sort, setSort] = useState<SortKey>("ev");
  const [hideGhosts, setHideGhosts] = useState(true);
  const [selectedModes, setSelectedModes] = useState<string[]>([]);
  const { data, loading, error, reload } = useApi(() => api.getMatches(!hideGhosts), [hideGhosts]);

  const toggleMode = (m: string) =>
    setSelectedModes((prev) => prev.includes(m) ? prev.filter((x) => x !== m) : [...prev, m]);

  const all = data ?? [];
  const ghostsHidden = all.filter((m) => m.is_ghost).length;
  const list = all
    .filter((m) => (hideGhosts ? !m.is_ghost : true))
    .filter((m) => selectedModes.length === 0 || selectedModes.includes(m.posting.work_mode))
    .sort((a, b) => sort === "match" ? b.match_score - a.match_score : sort === "response" ? b.response_likelihood - a.response_likelihood : b.expected_value - a.expected_value);

  return (
    <div className="grid gap-10 md:grid-cols-[260px_1fr]">
      <aside className="space-y-6 md:sticky md:top-24 h-fit">
        <div className="card-soft p-5 space-y-4 text-sm">
          <FilterGroup label="Sort by">
            {[
              { k: "ev", l: "Expected value" },
              { k: "match", l: "Match score" },
              { k: "response", l: "Response likelihood" },
            ].map((o) => (
              <button key={o.k} onClick={() => setSort(o.k as SortKey)}
                      className={`w-full text-left px-3 py-2 rounded-lg transition focus:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--ring)] ${sort === o.k ? "bg-primary-tint text-[color:var(--color-primary)]" : "hover:bg-secondary"}`}>
                {o.l}
              </button>
            ))}
          </FilterGroup>
          <FilterGroup label="Shield">
            <label className="flex items-center gap-2 px-3 py-2 cursor-pointer">
              <input type="checkbox" checked={hideGhosts} onChange={(e) => setHideGhosts(e.target.checked)} className="accent-[color:var(--color-primary)]" />
              Hide likely ghosts
            </label>
          </FilterGroup>
          <FilterGroup label="Work mode">
            <div className="flex flex-wrap gap-1.5 px-3 pb-2">
              {WORK_MODES.map((m) => (
                <button
                  key={m}
                  onClick={() => toggleMode(m)}
                  className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium transition border focus:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--ring)] ${selectedModes.includes(m) ? "bg-primary text-primary-foreground border-primary" : "bg-white text-muted-foreground border-hairline hover:bg-secondary"}`}
                  style={{ borderColor: selectedModes.includes(m) ? undefined : "var(--color-hairline)" }}
                  aria-pressed={selectedModes.includes(m)}
                >
                  {m}
                </button>
              ))}
            </div>
          </FilterGroup>
        </div>
      </aside>

      <section>
        <div className="flex items-end justify-between">
          <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground font-mono">
            {list.length} curated · {ghostsHidden} {ghostsHidden === 1 ? "ghost" : "ghosts"} {hideGhosts ? "filtered" : "flagged"}
          </div>
          <button onClick={reload} className="hidden md:inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground">
            <SlidersHorizontal className="h-4 w-4" /> Re-rank
          </button>
        </div>

        {/* Profile completeness banner — shown when no match scores yet */}
        {!loading && list.length > 0 && list.every((m) => m.match_score === 0) && (
          <Link to="/onboarding" className="mt-4 flex items-center gap-3 rounded-xl border p-4 hover:bg-secondary transition"
                style={{ borderColor: "color-mix(in oklab, var(--color-primary) 35%, transparent)", background: "color-mix(in oklab, var(--color-primary) 6%, white)" }}>
            <UserCircle className="h-8 w-8 shrink-0" style={{ color: "var(--color-primary)" }} />
            <div>
              <div className="font-medium text-sm" style={{ color: "var(--color-primary)" }}>Upload your résumé to unlock personalized match scores</div>
              <div className="text-xs text-muted-foreground mt-0.5">Right now you're seeing postings ranked by freshness. Once your profile is built, each card gets a real % match based on your skills and experience.</div>
            </div>
            <ArrowUpRight className="h-4 w-4 ml-auto shrink-0" style={{ color: "var(--color-primary)" }} />
          </Link>
        )}

        <div className="mt-6 grid gap-5">
          {loading && <LoadingState label="Scoring matches" />}
          {error && <ErrorState error={error} onRetry={reload} />}
          {!loading && !error && list.length === 0 && (
            <>
              <EmptyState icon={Ghost} title="No live matches right now."
                body={hideGhosts && ghostsHidden > 0
                  ? `We filtered ${ghostsHidden} likely-ghost ${ghostsHidden === 1 ? "role" : "roles"}. Turn the shield off to see them, or check back tomorrow.`
                  : "Complete your profile in onboarding to unlock ranked matches, or paste a job URL below to add it directly."}
              />
              <ImportBox onImported={reload} />
            </>
          )}
          {list.map((m, i) => (
            <motion.div key={m.posting.id}
                        initial={{ opacity: 0, y: 14 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: i * 0.04, duration: 0.5, ease: [0.22, 1, 0.36, 1] }}>
              <MatchCard m={m} />
            </motion.div>
          ))}
        </div>
      </section>
    </div>
  );
}

function ResearchFeed() {
  const { data, loading, error, reload } = useApi(() => api.getResearchOpportunities(), []);
  const list = (data ?? []).slice().sort((a, b) => b.fit_score - a.fit_score);

  return (
    <section>
      <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground font-mono">
        {list.length} labs · ranked by fit
      </div>

      <div className="mt-6 grid gap-5">
        {loading && <LoadingState label="Matching to labs" />}
        {error && <ErrorState error={error} onRetry={reload} />}
        {!loading && !error && list.length === 0 && (
          <EmptyState icon={FlaskConical} title="No research matches yet." body="Add research interests in onboarding to seed this feed." />
        )}
        {list.map((o, i) => (
          <motion.div key={o.id}
                      initial={{ opacity: 0, y: 14 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: i * 0.05 }}>
            <ResearchCard o={o} />
          </motion.div>
        ))}
      </div>
    </section>
  );
}

function FilterGroup({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="px-3 pt-1 pb-2 text-xs uppercase tracking-[0.14em] text-muted-foreground">{label}</div>
      <div className="space-y-0.5">{children}</div>
    </div>
  );
}

function MatchCard({ m }: { m: Match }) {
  return (
    <div className="card-soft card-lift p-6 grid gap-5 md:grid-cols-[88px_1fr_auto] items-start">
      <MatchRing value={m.match_score} size={88} label="match" />
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <h3 className="font-display text-2xl font-medium tracking-tight">{m.posting.title}</h3>
          <span className="text-muted-foreground">·</span>
          <span className="text-sm">{m.posting.company.name}</span>
          <a href={m.posting.source_url} target="_blank" rel="noreferrer" aria-label="Open original posting" className="text-muted-foreground hover:text-foreground"><ArrowUpRight className="h-4 w-4" /></a>
        </div>
        <p className="mt-2 text-sm text-muted-foreground max-w-2xl">{m.match_explanation}</p>
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <GhostBadge isGhost={m.is_ghost} score={m.ghost_score} />
          <Pill><MapPin className="h-3 w-3 mr-1" />{m.posting.location} · {m.posting.work_mode}</Pill>
          {m.posting.stipend > 0 && (
            <Pill><DollarSign className="h-3 w-3 mr-1" /><span className="font-mono">{m.posting.stipend.toLocaleString()}</span>/mo</Pill>
          )}
          {m.matched_skills.slice(0, 3).map((s) => <Pill key={s} tone="primary">{s}</Pill>)}
          {m.missing_skills.slice(0, 1).map((s) => <Pill key={s} tone="warm">missing · {s}</Pill>)}
        </div>
      </div>
      <div className="text-right">
        <div className="text-xs uppercase tracking-[0.14em] text-muted-foreground">Response</div>
        <div className="font-mono text-2xl">{Math.round(m.response_likelihood * 100)}%</div>
        <div className="mt-1 text-xs text-muted-foreground">EV <span className="font-mono">{m.expected_value.toFixed(2)}</span></div>
        <div className="mt-4 flex gap-2 justify-end">
          <Link to="/referrals" search={{ posting_id: m.posting.id }} className="inline-flex items-center gap-1.5 rounded-full border bg-white px-3 py-1.5 text-xs hover:bg-secondary" style={{ borderColor: "var(--color-hairline)" }}>
            <Users className="h-3 w-3" /> Find referral
          </Link>
          <Link to="/assistant" search={{ posting_id: m.posting.id }} className="inline-flex items-center rounded-full bg-primary text-primary-foreground px-3.5 py-1.5 text-xs font-medium hover:bg-[color:var(--primary-hover)]">
            Draft application
          </Link>
        </div>
      </div>
    </div>
  );
}

function ResearchCard({ o }: { o: ResearchOpportunity }) {
  return (
    <div className="card-soft card-lift p-6 grid gap-5 md:grid-cols-[88px_1fr_auto] items-start">
      <MatchRing value={o.fit_score} size={88} label="fit" />
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <h3 className="font-display text-2xl font-medium tracking-tight">{o.professor_name}</h3>
          <span className="text-muted-foreground">·</span>
          <span className="text-sm">{o.lab_name}</span>
        </div>
        <div className="mt-1 text-xs text-muted-foreground font-mono uppercase tracking-[0.16em]">
          {o.institution} · {o.research_area}
        </div>
        <p className="mt-3 text-sm text-muted-foreground max-w-2xl">{o.fit_explanation}</p>
        <div className="mt-4 flex flex-wrap items-center gap-2">
          {o.recent_paper && (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-primary-tint px-2.5 py-1 text-xs font-medium" style={{ color: "var(--color-primary)" }}>
              <Sparkles className="h-3 w-3" /> Recent: {o.recent_paper.title} ({o.recent_paper.year})
            </span>
          )}
          {o.matched_skills.slice(0, 3).map((s) => <Pill key={s} tone="primary">{s}</Pill>)}
        </div>
      </div>
      <div className="text-right">
        <div className="text-xs uppercase tracking-[0.14em] text-muted-foreground">Region</div>
        <div className="font-mono text-sm">{o.region}</div>
        <div className="mt-4 flex gap-2 justify-end">
          <Link to="/pitch" search={{ opportunity_id: o.id }} className="inline-flex items-center rounded-full bg-primary text-primary-foreground px-3.5 py-1.5 text-xs font-medium hover:bg-[color:var(--primary-hover)]">
            Draft pitch
          </Link>
        </div>
      </div>
    </div>
  );
}
