import { createFileRoute } from "@tanstack/react-router";
import { useState, useRef } from "react";
import { CalmBackground } from "@/components/live-background";
import { Nav } from "@/components/nav";
import { api, useApi } from "@/lib/api-client";
import { Pill } from "@/components/ui-bits";
import { LoadingState, ErrorState, EmptyState } from "@/components/data-states";
import { Send, Linkedin, RefreshCw, Pencil } from "lucide-react";
import type { Contact, Referral } from "@/lib/mocks";

export const Route = createFileRoute("/referrals")({
  validateSearch: (s: Record<string, unknown>) => ({
    posting_id: typeof s.posting_id === "string" ? s.posting_id : undefined,
  }),
  head: () => ({ meta: [{ title: "Referrals — InternPilot" }, { name: "description", content: "Warm intros instead of cold applies." }] }),
  component: Referrals,
});

function IntroDraftPanel({ contact, referral }: { contact: Contact; referral: Referral | undefined }) {
  const [isEditing, setIsEditing] = useState(false);
  const editRef = useRef<HTMLDivElement>(null);

  const { data: artifact, loading: artLoading } = useApi(
    () => referral?.intro_artifact_id ? api.getArtifact(referral.intro_artifact_id) : Promise.resolve(undefined),
    [referral?.intro_artifact_id],
  );

  const introContent = artifact?.content;

  const handleTweak = () => {
    setIsEditing(true);
    // Focus the editable div after React re-renders
    setTimeout(() => {
      if (editRef.current) {
        editRef.current.focus();
        // Move cursor to end
        const range = document.createRange();
        range.selectNodeContents(editRef.current);
        range.collapse(false);
        const sel = window.getSelection();
        sel?.removeAllRanges();
        sel?.addRange(range);
      }
    }, 30);
  };

  const templateLines = [
    `Hi ${contact.name.split(" ")[0]},`,
    `I noticed you work at ${contact.company_name} — I'm a student who just came across a role there and wanted to reach out. I'd love to learn more about your experience on the team and whether you'd be open to a quick 15-minute chat.`,
    `Happy to share my resume and a short project demo upfront if that's more useful than coffee.`,
    `Thanks so much either way.`,
  ];
  const templateText = templateLines.join("\n\n");

  return (
    <div className="card-soft p-8">
      <div className="flex items-center justify-between">
        <div className="text-xs uppercase tracking-[0.14em] text-muted-foreground font-mono">
          Drafted intro · {contact.name}
        </div>
        {isEditing && (
          <span className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">Editing</span>
        )}
      </div>
      <h2 className="mt-2 font-display text-2xl">
        Subject: Your school → {contact.company_name} team
      </h2>

      {artLoading ? (
        <div className="mt-5 flex items-center gap-2 text-sm text-muted-foreground">
          <RefreshCw className="h-3.5 w-3.5 animate-spin" /> Loading draft…
        </div>
      ) : (introContent || isEditing) ? (
        <div
          ref={editRef}
          className="mt-5 leading-relaxed text-[15px] font-display whitespace-pre-wrap outline-none focus:ring-2 focus:ring-primary/20 rounded-lg p-2 -mx-2"
          contentEditable
          suppressContentEditableWarning
        >
          {introContent ?? templateText}
        </div>
      ) : (
        <div className="mt-5 leading-relaxed text-[15px] font-display space-y-3 text-foreground/90">
          <p>Hi {contact.name.split(" ")[0]},</p>
          <p>
            I noticed you work at {contact.company_name} — I&apos;m a student who just came across
            a role there and wanted to reach out. I&apos;d love to learn more about your experience
            on the team and whether you&apos;d be open to a quick 15-minute chat.
          </p>
          <p>
            Happy to share my resume and a short project demo upfront if that&apos;s
            more useful than coffee.
          </p>
          <p>Thanks so much either way.</p>
        </div>
      )}

      <div className="mt-6 flex justify-end gap-2">
        <button
          onClick={handleTweak}
          className="inline-flex items-center gap-1.5 rounded-full border bg-white px-4 py-2 text-xs hover:bg-secondary"
          style={{ borderColor: "var(--color-hairline)" }}
        >
          <Pencil className="h-3 w-3" /> Tweak draft
        </button>
        <button
          onClick={() => referral && api.setReferralStatus(referral.id, "requested")}
          disabled={!referral}
          className="inline-flex items-center gap-1.5 rounded-full bg-primary text-primary-foreground px-4 py-2 text-xs font-medium hover:bg-[color:var(--primary-hover)] disabled:opacity-60"
        >
          <Send className="h-3.5 w-3.5" /> Send intro request
        </button>
      </div>
    </div>
  );
}

const relationshipLabel: Record<Contact["relationship"], string> = {
  alumni: "alum",
  second_degree: "2nd-degree",
  unknown: "warm",
};

function Referrals() {
  const { posting_id } = Route.useSearch();
  const isCandidateMode = !!posting_id;

  // In candidate mode: show contacts at the company for this posting
  const { data: candidates, loading: cLoad, error: cErr, reload: cReload } = useApi(
    () => api.getReferralCandidates(posting_id),
    [posting_id],
  );
  // Always load existing referral records (for the intro panel action)
  const { data: referrals, loading: rLoad, error: rErr, reload: rReload } = useApi(
    () => api.getReferrals(),
    [],
  );

  const loading = isCandidateMode ? cLoad : rLoad;
  const error = isCandidateMode ? cErr : rErr;
  const reload = isCandidateMode ? cReload : rReload;

  // Unified contact list: either direct candidates or contacts extracted from referral records
  const contacts: Contact[] = isCandidateMode
    ? (candidates ?? [])
    : (referrals ?? []).map((r) => r.contact);

  // The active referral for the first contact (used by the send button)
  const activeReferral: Referral | undefined = referrals?.[0];
  const firstContact = contacts[0];

  return (
    <div className="min-h-screen">
      <CalmBackground />
      <Nav />
      <main className="mx-auto max-w-6xl px-6 py-12">
        <div>
          <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground font-mono">
            {isCandidateMode ? "Candidates · Role match" : "Target · Linear"}
          </div>
          <h1 className="mt-2 font-display text-5xl md:text-6xl tracking-tight">A warm intro,<br/><span className="italic" style={{color:"var(--color-primary)"}}>drafted for you.</span></h1>
        </div>

        <div className="mt-10">
          {loading && <LoadingState label={isCandidateMode ? "Searching LinkedIn for contacts…" : "Finding alumni"} />}
          {error && <ErrorState error={error} onRetry={reload} />}
          {!loading && !error && contacts.length === 0 && (
            <EmptyState
              title={isCandidateMode ? "No contacts found" : "No referral paths yet."}
              body={
                isCandidateMode
                  ? "We checked LinkedIn but couldn't find any public contacts at this company. Try a different company or ask your university career center."
                  : "As you save more roles, we'll surface alumni and 2nd-degree contacts at those companies."
              }
            />
          )}
          {!loading && !error && contacts.length > 0 && (
            <div className="grid gap-6 md:grid-cols-[1fr_1.4fr]">
              <div className="space-y-4">
                {contacts.map((c) => {
                  const linkedReferral = referrals?.find((r) => r.contact.id === c.id);
                  return (
                    <div key={c.id} className="card-soft card-lift p-5 flex items-center gap-4">
                      <div className="h-12 w-12 rounded-full grid place-items-center font-display text-lg"
                           style={{ background: "var(--color-primary-tint)", color: "var(--color-primary)" }}>
                        {c.name.split(" ").map((s) => s[0]).join("")}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="font-medium">{c.name}</div>
                        <div className="text-xs text-muted-foreground">{c.role} · {c.university} '{String(c.grad_year).slice(2)}</div>
                        <div className="mt-2 flex gap-1.5">
                          <Pill tone="primary">{relationshipLabel[c.relationship]}</Pill>
                          {linkedReferral && <Pill>{linkedReferral.status}</Pill>}
                        </div>
                      </div>
                      <a
                        href={c.linkedin}
                        target="_blank"
                        rel="noreferrer"
                        aria-label={`Open ${c.name} on LinkedIn`}
                        className="text-muted-foreground hover:text-foreground"
                      >
                        <Linkedin className="h-4 w-4" />
                      </a>
                    </div>
                  );
                })}
              </div>

              {firstContact && (
                <IntroDraftPanel
                  contact={firstContact}
                  referral={activeReferral}
                />
              )}
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
