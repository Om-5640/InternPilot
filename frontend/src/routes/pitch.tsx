import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { CalmBackground } from "@/components/live-background";
import { Nav } from "@/components/nav";
import { api, useApi } from "@/lib/api-client";
import { LoadingState, ErrorState } from "@/components/data-states";
import { Send, RefreshCw, Save, ArrowLeft } from "lucide-react";
import type { ResearchOpportunity, ResearchPitch } from "@/lib/mocks";

export const Route = createFileRoute("/pitch")({
  validateSearch: (s: Record<string, unknown>) => ({
    opportunity_id: typeof s.opportunity_id === "string" ? s.opportunity_id : undefined,
  }),
  head: () => ({ meta: [{ title: "Research pitch — InternPilot" }, { name: "description", content: "Draft a professor email grounded in your work." }] }),
  component: Pitch,
});

function Pitch() {
  const { opportunity_id } = Route.useSearch();
  const { data: result, loading, error, reload } = useApi(() => api.getResearchOpportunities(), []);
  const list = result?.items;
  const o = list?.find((x) => x.id === opportunity_id) ?? list?.[0];

  return (
    <div className="min-h-screen">
      <CalmBackground />
      <Nav />
      <main className="mx-auto max-w-6xl px-6 py-12">
        {loading && <LoadingState label="Loading opportunity" />}
        {error && <ErrorState error={error} onRetry={reload} />}
        {!loading && !error && o && <PitchInner o={o} />}
      </main>
    </div>
  );
}

function PitchInner({ o }: { o: ResearchOpportunity }) {
  const navigate = useNavigate();
  const [pitch, setPitch] = useState<ResearchPitch | null>(null);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [drafting, setDrafting] = useState(false);
  const { data: profile } = useApi(() => api.getProfile(), []);

  const regenerate = async () => {
    setDrafting(true);
    try {
      const p = await api.draftResearchPitch(o.id);
      setPitch(p); setSubject(p.subject); setBody(p.body); setSaved(false);
    } finally { setDrafting(false); }
  };
  useEffect(() => { regenerate(); /* eslint-disable-next-line */ }, [o.id]);

  const save = async () => {
    if (!pitch) return;
    setSaving(true);
    try {
      await api.saveResearchOutreach(o.id, pitch.id);
      setSaved(true);
      setTimeout(() => navigate({ to: "/outreach" }), 500);
    } finally { setSaving(false); }
  };

  return (
    <div className="grid gap-8 md:grid-cols-[380px_1fr]">
      <aside className="space-y-6 md:sticky md:top-24 h-fit">
        <div>
          <Link to="/feed" className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground">
            <ArrowLeft className="h-3 w-3" /> Back to research feed
          </Link>
          <div className="mt-3 text-xs uppercase tracking-[0.18em] text-muted-foreground font-mono">Professor pitch</div>
          <h2 className="mt-2 font-display text-3xl tracking-tight">{o.professor_name}</h2>
          <p className="text-sm text-muted-foreground">{o.lab_name} · {o.institution}</p>
        </div>

        <div className="card-soft p-6">
          <div className="text-xs uppercase tracking-[0.14em] text-muted-foreground">Research area</div>
          <p className="mt-2 text-sm">{o.research_area}</p>
          <div className="mt-4 text-xs uppercase tracking-[0.14em] text-muted-foreground">Why you fit</div>
          <p className="mt-2 text-sm text-muted-foreground leading-relaxed">{o.fit_explanation}</p>
          {o.recent_paper && (
            <>
              <div className="mt-4 text-xs uppercase tracking-[0.14em] text-muted-foreground">Recent paper</div>
              <p className="mt-2 text-sm italic">"{o.recent_paper.title}" ({o.recent_paper.year})</p>
            </>
          )}
        </div>
      </aside>

      <section>
        <div className="flex items-center justify-between gap-4">
          <div>
            <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground font-mono">Draft · grounded in your work</div>
            <h1 className="mt-2 font-display text-4xl tracking-tight">Pitch email</h1>
          </div>
          <div className="flex gap-2">
            <button onClick={regenerate} disabled={drafting}
                    className="inline-flex items-center gap-1.5 rounded-full border bg-white px-3 py-1.5 text-xs hover:bg-secondary disabled:opacity-60"
                    style={{ borderColor: "var(--color-hairline)" }}>
              <RefreshCw className={`h-3.5 w-3.5 ${drafting ? "animate-spin" : ""}`} /> {drafting ? "Drafting" : "Regenerate"}
            </button>
            <button onClick={save} disabled={saving || !pitch}
                    className="inline-flex items-center gap-1.5 rounded-full bg-primary text-primary-foreground px-4 py-1.5 text-xs font-medium hover:bg-[color:var(--primary-hover)] disabled:opacity-60">
              {saved ? <><Send className="h-3.5 w-3.5" /> Saved</> : <><Save className="h-3.5 w-3.5" /> Save to outreach</>}
            </button>
          </div>
        </div>

        <div className="card-soft mt-6 p-8">
          <label className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground font-mono">To</label>
          <div className="mt-1 font-mono text-sm">{o.professor_email}</div>

          <label className="mt-5 block text-[10px] uppercase tracking-[0.18em] text-muted-foreground font-mono">Subject</label>
          <input
            value={subject} onChange={(e) => { setSubject(e.target.value); setSaved(false); }}
            className="mt-1 w-full bg-transparent font-display text-xl tracking-tight focus:outline-none border-b pb-2"
            style={{ borderColor: "var(--color-hairline)" }}
          />

          <label className="mt-5 block text-[10px] uppercase tracking-[0.18em] text-muted-foreground font-mono">Body</label>
          <textarea
            value={body} onChange={(e) => { setBody(e.target.value); setSaved(false); }}
            rows={16}
            className="mt-1 w-full bg-transparent text-[15px] leading-relaxed font-display focus:outline-none resize-y"
          />
        </div>

        <p className="mt-3 text-xs text-muted-foreground">
          {profile?.projects?.length
            ? `Grounded in: ${profile.projects.slice(0, 3).map((p) => p.name).join(" · ")} · `
            : "Grounded in your profile · "}
          You approve every send — we never email professors for you.
        </p>
      </section>
    </div>
  );
}
