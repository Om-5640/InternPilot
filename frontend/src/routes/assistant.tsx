import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useState, useRef, useEffect } from "react";
import { CalmBackground } from "@/components/live-background";
import { Nav } from "@/components/nav";
import { api, useApi } from "@/lib/api-client";
import { Pill } from "@/components/ui-bits";
import { LoadingState, ErrorState } from "@/components/data-states";
import { Send, RefreshCw, FileText, Check, Copy, ExternalLink, X, ArrowLeft } from "lucide-react";
import type { Match } from "@/lib/mocks";

export const Route = createFileRoute("/assistant")({
  validateSearch: (s: Record<string, unknown>) => ({
    posting_id: typeof s.posting_id === "string" ? s.posting_id : undefined,
  }),
  head: () => ({ meta: [{ title: "Application Assistant — InternPilot" }, { name: "description", content: "Draft a grounded, ATS-optimized application." }] }),
  component: Assistant,
});

// ---------------------------------------------------------------------------
// Draft cache — localStorage keyed by posting_id so we never regenerate
// ---------------------------------------------------------------------------
const DRAFT_CACHE_KEY = "ip_draft_cache_v1";

function getCachedDraftId(posting_id: string): string | null {
  try {
    const cache = JSON.parse(localStorage.getItem(DRAFT_CACHE_KEY) || "{}");
    return typeof cache[posting_id] === "string" ? cache[posting_id] : null;
  } catch { return null; }
}

function setCachedDraftId(posting_id: string, artifact_id: string): void {
  try {
    const cache = JSON.parse(localStorage.getItem(DRAFT_CACHE_KEY) || "{}");
    cache[posting_id] = artifact_id;
    const entries = Object.entries(cache);
    if (entries.length > 100) {
      const trimmed = Object.fromEntries(entries.slice(-100));
      localStorage.setItem(DRAFT_CACHE_KEY, JSON.stringify(trimmed));
    } else {
      localStorage.setItem(DRAFT_CACHE_KEY, JSON.stringify(cache));
    }
  } catch { /* ignore storage errors */ }
}

// Strip HTML tags from a string for safe plain-text display
function stripHtml(html: string): string {
  return html
    .replace(/<[^>]*>/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&nbsp;/g, " ")
    .replace(/\s{2,}/g, " ")
    .trim();
}

function Assistant() {
  const { posting_id } = Route.useSearch();
  const { data: result, loading, error, reload } = useApi(() => api.getMatches(), []);
  const matches = result?.items;

  const m: Match | undefined =
    matches?.find((x) => x.posting.id === posting_id) ?? matches?.[0];

  return (
    <div className="min-h-screen">
      <CalmBackground />
      <Nav />
      <main className="mx-auto max-w-7xl px-6 py-12">
        {loading && <LoadingState label="Loading matches" />}
        {error && <ErrorState error={error} onRetry={reload} />}
        {!loading && !error && !m && (
          <div className="text-center py-24 text-muted-foreground">
            No match selected. <Link to="/feed" className="underline">Browse the feed</Link> and open a posting first.
          </div>
        )}
        {!loading && !error && m && <AssistantInner m={m} />}
      </main>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Review modal — shows before user marks as applied
// ---------------------------------------------------------------------------
function ReviewModal({
  m,
  content,
  onConfirm,
  onClose,
  submitting,
  submitted,
}: {
  m: Match;
  content: string;
  onConfirm: () => void;
  onClose: () => void;
  submitting: boolean;
  submitted: boolean;
}) {
  const [copied, setCopied] = useState(false);

  const copyLetter = async () => {
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch { /* ignore */ }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" style={{ background: "rgba(0,0,0,0.4)" }}>
      <div className="relative bg-white rounded-2xl shadow-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto p-8">
        <button onClick={onClose} className="absolute top-4 right-4 text-muted-foreground hover:text-foreground">
          <X className="h-5 w-5" />
        </button>

        <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground font-mono">Application review</div>
        <h2 className="mt-2 font-display text-2xl tracking-tight">Ready to apply?</h2>

        <div className="mt-5 rounded-xl border p-4 space-y-2 text-sm" style={{ borderColor: "var(--color-hairline)" }}>
          <div><span className="text-muted-foreground">Company:</span> <strong>{m.posting.company.name}</strong></div>
          <div><span className="text-muted-foreground">Role:</span> {m.posting.title}</div>
          <div><span className="text-muted-foreground">Location:</span> {m.posting.location} · {m.posting.work_mode}</div>
          {m.posting.source_url && (
            <a
              href={m.posting.source_url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1.5 text-xs font-medium mt-2"
              style={{ color: "var(--color-primary)" }}
            >
              <ExternalLink className="h-3.5 w-3.5" /> Open application page
            </a>
          )}
        </div>

        <div className="mt-5">
          <div className="flex items-center justify-between">
            <div className="text-xs uppercase tracking-[0.14em] text-muted-foreground">Your cover letter</div>
            <button onClick={copyLetter} className="inline-flex items-center gap-1.5 rounded-full border bg-white px-3 py-1 text-xs hover:bg-secondary" style={{ borderColor: "var(--color-hairline)" }}>
              {copied ? <><Check className="h-3 w-3" /> Copied</> : <><Copy className="h-3 w-3" /> Copy</>}
            </button>
          </div>
          <div className="mt-3 rounded-xl border p-4 text-sm leading-relaxed font-display max-h-48 overflow-y-auto whitespace-pre-wrap" style={{ borderColor: "var(--color-hairline)" }}>
            {content}
          </div>
        </div>

        <div className="mt-2 rounded-xl p-3 text-xs text-muted-foreground" style={{ background: "var(--color-surface)" }}>
          <strong>How to apply:</strong> Click "Open application page" above → paste your cover letter → submit. Come back and click "Mark as Applied" once done.
        </div>

        <div className="mt-6 flex gap-3 justify-end">
          <button onClick={onClose} className="rounded-full border px-4 py-2 text-sm hover:bg-secondary" style={{ borderColor: "var(--color-hairline)" }}>
            Go back and edit
          </button>
          <button
            onClick={onConfirm}
            disabled={submitting || submitted}
            className="inline-flex items-center gap-2 rounded-full bg-primary text-primary-foreground px-5 py-2 text-sm font-medium hover:bg-[color:var(--primary-hover)] disabled:opacity-60"
          >
            {submitted ? <><Check className="h-4 w-4" /> Applied!</> : submitting ? <><RefreshCw className="h-4 w-4 animate-spin" /> Saving…</> : <><Check className="h-4 w-4" /> Mark as Applied</>}
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main assistant UI
// ---------------------------------------------------------------------------
function AssistantInner({ m }: { m: Match }) {
  const navigate = useNavigate();
  const draftRef = useRef<HTMLDivElement>(null);

  const [showReview, setShowReview] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  // Draft state — managed manually so we can cache
  const [draft, setDraft] = useState<{ artifact_id: string; content: string; ats_score: number; missing_keywords: string[] } | null>(null);
  const [draftLoading, setDraftLoading] = useState(true);
  const [nonce, setNonce] = useState(0);

  // Decode — LLM-extracted summary + requirements (cached per posting)
  const { data: decoded, loading: decodeLoading } = useApi(
    () => api.decodePosting(m.posting.id),
    [m.posting.id],
  );

  // Load draft — check cache first, generate if missing
  useEffect(() => {
    let cancelled = false;
    setDraftLoading(true);

    const load = async () => {
      if (nonce === 0) {
        // First load: check backend for existing draft
        try {
          const existing = await api.getLatestDraft(m.posting.id);
          if (existing && !cancelled) {
            setDraft(existing);
            if (existing.artifact_id) setCachedDraftId(m.posting.id, existing.artifact_id);
            return;
          }
        } catch { /* not found, generate */ }

        // Also check localStorage cache
        const cachedId = getCachedDraftId(m.posting.id);
        if (cachedId) {
          try {
            const artifact = await api.getArtifact(cachedId);
            if (artifact && !cancelled) {
              setDraft({
                artifact_id: artifact.id,
                content: artifact.content,
                ats_score: artifact.ats_score ?? 0,
                missing_keywords: artifact.missing_keywords ?? [],
              });
              return;
            }
          } catch { /* cache miss */ }
        }
      }

      // Generate new draft
      const d = await api.draftCoverLetter(m.posting.id);
      if (!cancelled) {
        setDraft(d);
        if (d.artifact_id) setCachedDraftId(m.posting.id, d.artifact_id);
      }
    };

    load()
      .catch((e) => { if (!cancelled) console.error("Draft load error:", e); })
      .finally(() => { if (!cancelled) setDraftLoading(false); });

    return () => { cancelled = true; };
  }, [m.posting.id, nonce]);

  const atsScore = draft?.ats_score ?? 0;
  const missing = draft?.missing_keywords ?? [];

  // Job summary: show loading until decoded, then use LLM summary, never raw HTML
  const rawDesc = m.posting.description ?? "";
  const cleanDesc = rawDesc.startsWith("<") || rawDesc.includes("&lt;") ? stripHtml(rawDesc) : rawDesc;
  const summary = decoded?.summary || (decodeLoading ? "" : cleanDesc.slice(0, 400) + (cleanDesc.length > 400 ? "…" : ""));
  const requirements = decoded?.requirements?.length ? decoded.requirements : m.posting.requirements;

  const getEditedContent = (): string => {
    if (draftRef.current) {
      return draftRef.current.innerText || draftRef.current.textContent || draft?.content || "";
    }
    return draft?.content || "";
  };

  const handleReviewAndSend = () => {
    if (!draft?.artifact_id || draftLoading) return;
    setShowReview(true);
  };

  const handleConfirmApplied = async () => {
    if (!draft?.artifact_id || submitting || submitted) return;
    setSubmitting(true);
    try {
      const editedContent = getEditedContent();

      // If content was edited, save the update first
      if (editedContent && editedContent !== draft.content) {
        await api.updateArtifact(draft.artifact_id, editedContent);
      }

      const app = await api.createApplication(m.posting.id, "portal", draft.artifact_id);
      await api.setApplicationStatus(app.id, "applied");
      setSubmitted(true);

      // Invalidate cache so next open generates fresh
      setCachedDraftId(m.posting.id, "");

      setTimeout(() => navigate({ to: "/tracker" }), 1200);
    } catch (err) {
      console.error("Failed to submit application:", err);
      setSubmitting(false);
    }
  };

  return (
    <>
      {showReview && (
        <ReviewModal
          m={m}
          content={getEditedContent()}
          onConfirm={handleConfirmApplied}
          onClose={() => setShowReview(false)}
          submitting={submitting}
          submitted={submitted}
        />
      )}

      <div className="grid gap-8 md:grid-cols-[420px_1fr]">
        <aside className="space-y-6 md:sticky md:top-24 h-fit">
          <div>
            <Link to="/feed" className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground">
              <ArrowLeft className="h-3 w-3" /> Back to feed
            </Link>
            <div className="mt-3 text-xs uppercase tracking-[0.18em] text-muted-foreground font-mono">Decoded posting</div>
            <h2 className="mt-2 font-display text-3xl tracking-tight">{m.posting.title}</h2>
            <p className="text-sm text-muted-foreground">{m.posting.company.name} · {m.posting.location}</p>
            {m.posting.source_url && (
              <a href={m.posting.source_url} target="_blank" rel="noreferrer"
                 className="mt-1 inline-flex items-center gap-1 text-xs hover:underline"
                 style={{ color: "var(--color-primary)" }}>
                <ExternalLink className="h-3 w-3" /> View & apply on site
              </a>
            )}
          </div>

          {/* ATS Score card */}
          <div className="card-soft p-6">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-xs uppercase tracking-[0.14em] text-muted-foreground">ATS score</div>
                <div className="text-[10px] text-muted-foreground mt-0.5">Profile vs. job requirements</div>
              </div>
              <div className="font-mono text-sm" style={{ color: atsScore >= 70 ? "var(--color-primary)" : atsScore >= 40 ? "var(--color-warm)" : "#e44" }}>
                {draftLoading ? "—" : `${atsScore} / 100`}
              </div>
            </div>
            <div className="mt-3 h-2 rounded-full bg-secondary overflow-hidden" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={atsScore}>
              {draftLoading ? (
                <div className="h-full rounded-full animate-pulse" style={{ width: "60%", background: "var(--color-hairline)" }} />
              ) : (
                <div
                  className="h-full rounded-full transition-all duration-700"
                  style={{
                    width: `${atsScore}%`,
                    background: atsScore >= 70 ? "var(--color-primary)" : atsScore >= 40 ? "var(--color-warm)" : "#e44",
                  }}
                />
              )}
            </div>
            {!draftLoading && missing.length > 0 && (
              <>
                <div className="mt-4 text-xs uppercase tracking-[0.14em] text-muted-foreground">Requirements your profile is missing</div>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {missing.slice(0, 8).map((k) => <Pill key={k} tone="warm">{k}</Pill>)}
                </div>
                <p className="mt-2 text-[10px] text-muted-foreground">Add these skills to your profile to improve your ATS score.</p>
              </>
            )}
            {!draftLoading && missing.length === 0 && atsScore > 0 && (
              <p className="mt-3 text-xs" style={{ color: "var(--color-primary)" }}>Your profile covers all listed requirements.</p>
            )}
          </div>

          {/* Job summary card */}
          <div className="card-soft p-6">
            <div className="text-xs uppercase tracking-[0.14em] text-muted-foreground">Job summary</div>
            {decodeLoading ? (
              <div className="mt-3 space-y-2">
                <div className="h-3 rounded bg-secondary animate-pulse" style={{ width: "90%" }} />
                <div className="h-3 rounded bg-secondary animate-pulse" style={{ width: "75%" }} />
                <div className="h-3 rounded bg-secondary animate-pulse" style={{ width: "80%" }} />
                <div className="mt-2 text-xs text-muted-foreground">Analysing job description…</div>
              </div>
            ) : (
              <p className="mt-2 text-sm leading-relaxed">{summary}</p>
            )}
            {requirements.length > 0 && (
              <>
                <div className="mt-4 text-xs uppercase tracking-[0.14em] text-muted-foreground">Requirements</div>
                <ul className="mt-2 text-sm space-y-1.5">
                  {requirements.slice(0, 8).map((r) => (
                    <li key={r} className="flex gap-2">
                      <Check className="h-3.5 w-3.5 mt-1 shrink-0" style={{ color: "var(--color-primary)" }} />
                      {r}
                    </li>
                  ))}
                </ul>
              </>
            )}
            {m.posting.stipend > 0 && (
              <div className="mt-4 text-xs text-muted-foreground">
                Stipend: <span className="font-mono">${m.posting.stipend.toLocaleString()}/mo</span>
              </div>
            )}
          </div>
        </aside>

        <section>
          <div className="flex items-center justify-between">
            <div>
              <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground font-mono">
                Cover letter · grounded in your profile
                {draft?.artifact_id && !draftLoading && (
                  <span className="ml-2 text-[9px] uppercase tracking-widest opacity-50">cached</span>
                )}
              </div>
              <h1 className="mt-2 font-display text-4xl tracking-tight">Draft</h1>
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => setNonce((n) => n + 1)}
                disabled={draftLoading || submitting}
                className="inline-flex items-center gap-1.5 rounded-full border bg-white px-3 py-1.5 text-xs hover:bg-secondary disabled:opacity-60"
                style={{ borderColor: "var(--color-hairline)" }}
              >
                <RefreshCw className={`h-3.5 w-3.5 ${draftLoading ? "animate-spin" : ""}`} /> Regenerate
              </button>
              <button
                onClick={handleReviewAndSend}
                disabled={!draft?.artifact_id || draftLoading || submitting || submitted}
                className="inline-flex items-center gap-1.5 rounded-full bg-primary text-primary-foreground px-4 py-1.5 text-xs font-medium hover:bg-[color:var(--primary-hover)] disabled:opacity-60"
              >
                {submitted ? (
                  <><Check className="h-3.5 w-3.5" /> Applied</>
                ) : (
                  <><Send className="h-3.5 w-3.5" /> Review &amp; apply</>
                )}
              </button>
            </div>
          </div>

          {draftLoading ? (
            <div className="card-soft mt-6 p-10 min-h-[320px]">
              <div className="flex items-center gap-3 text-sm text-muted-foreground mb-6">
                <RefreshCw className="h-4 w-4 animate-spin" style={{ color: "var(--color-primary)" }} />
                Drafting your cover letter — reading your profile and the job requirements…
              </div>
              <div className="space-y-3">
                {[90, 75, 82, 68, 78, 60].map((w, i) => (
                  <div key={i} className="h-3.5 rounded-full animate-pulse" style={{ width: `${w}%`, background: "var(--color-hairline)" }} />
                ))}
              </div>
            </div>
          ) : draft?.content ? (
            <div
              ref={draftRef}
              className="card-soft mt-6 p-10 leading-relaxed text-[15px] font-display focus:outline-none focus:ring-2 focus:ring-primary/20 rounded-2xl"
              contentEditable
              suppressContentEditableWarning
              style={{ minHeight: "320px" }}
            >
              {draft.content.split("\n\n").map((para, i) => (
                <p key={i} className={i > 0 ? "mt-4" : ""}>{para}</p>
              ))}
            </div>
          ) : (
            <div className="card-soft mt-6 p-10 flex items-center justify-center min-h-[320px] text-muted-foreground text-sm">
              Draft will appear here once your profile and the posting are loaded.
            </div>
          )}

          {draft?.content && (
            <p className="mt-3 text-xs text-muted-foreground flex items-center gap-2">
              <FileText className="h-3.5 w-3.5" />
              Editable above — your changes are saved when you click "Review &amp; apply".
              All claims are grounded in your verified profile.
            </p>
          )}
        </section>
      </div>
    </>
  );
}
