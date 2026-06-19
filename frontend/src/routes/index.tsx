import { createFileRoute, Link } from "@tanstack/react-router";
import { motion } from "framer-motion";
import { ArrowRight, ShieldCheck, Users, Sparkles, FileText, Send, BarChart3, Ghost, Check, GitBranch } from "lucide-react";
import { LiveBackground } from "@/components/live-background";
import { Nav, Footer } from "@/components/nav";
import { AnimatedCounter, Reveal } from "@/components/motion-primitives";
import { SectionLabel, Pill, MatchRing, GhostBadge } from "@/components/ui-bits";
import { api, useApi, getToken, isGuestMode } from "@/lib/api-client";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "InternPilot — Stop applying into the void." },
      { name: "description", content: "Find the internships that can actually convert. Ghost-job shield, warm referrals, and grounded applications you approve before sending." },
      { property: "og:title", content: "InternPilot — Stop applying into the void." },
      { property: "og:description", content: "The opposite of mass-blast bots. Apply only where you can actually win." },
    ],
  }),
  component: Landing,
});

function Landing() {
  return (
    <div className="min-h-screen">
      <Nav />
      <Hero />
      <StatBand />
      <Pillars />
      <HowItWorks />
      <PlatformIQ />
      <Quotes />
      <CTA />
      <Footer />
    </div>
  );
}

function Hero() {
  return (
    <section className="relative isolate overflow-hidden">
      <div className="absolute inset-0 -z-10">
        <LiveBackground />
      </div>
      <div className="mx-auto max-w-7xl px-6 pt-20 pb-32 md:pt-28 md:pb-44">
        <Reveal>
          <div className="inline-flex items-center gap-2 rounded-full border border-hairline bg-white/60 px-3 py-1 text-xs backdrop-blur"
               style={{ borderColor: "var(--color-hairline)" }}>
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-[color:var(--color-primary)] animate-pulse" />
            <span className="font-mono">Internship season · summer 2026</span>
          </div>
        </Reveal>

        <Reveal delay={0.05}>
          <h1 className="mt-6 max-w-5xl font-display text-[14vw] sm:text-7xl md:text-8xl font-medium leading-[0.95] tracking-tight text-balance">
            Stop applying<br />
            <span className="italic" style={{ color: "var(--color-primary)" }}>into the void.</span>
          </h1>
        </Reveal>

        <Reveal delay={0.15}>
          <p className="mt-8 max-w-2xl text-lg md:text-xl text-muted-foreground text-pretty leading-relaxed">
            Most internship applications vanish — into ghost jobs and resume black holes.
            InternPilot finds the roles that can actually convert, writes applications grounded in your real work,
            and gets you a warm intro instead of a cold apply.
          </p>
        </Reveal>

        <Reveal delay={0.25}>
          <div className="mt-10 flex flex-wrap items-center gap-4">
            <Link
              to="/onboarding"
              className="group inline-flex items-center gap-2 rounded-full bg-foreground px-6 py-3.5 text-sm font-medium text-background transition-transform hover:-translate-y-0.5"
              style={{ boxShadow: "var(--shadow-lift)" }}
            >
              Build your Career Twin
              <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
            </Link>
            <Link to="/feed" className="text-sm text-muted-foreground hover:text-foreground inline-flex items-center gap-1.5">
              See a sample match feed <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          </div>
        </Reveal>

        <Reveal delay={0.4}>
          <FloatingMatchCard />
        </Reveal>
      </div>
    </section>
  );
}

function FloatingMatchCard() {
  // Only call the real API when authenticated or in guest/mock mode.
  // Without a token the backend returns 401 and the old code would hard-redirect to /auth.
  const authenticated =
    typeof localStorage !== "undefined" ? !!getToken() || isGuestMode() : false;
  const { data: result } = useApi(
    () => (authenticated ? api.getMatches() : Promise.resolve({ items: [], fetching: false })),
    [authenticated],
  );
  const data = result?.items;
  const m = data?.[0];
  const ghost = data?.find((x) => x.is_ghost);
  if (!m) return null;
  return (
    <div className="relative mt-20 hidden md:block max-w-3xl">
      <motion.div
        initial={{ opacity: 0, y: 30 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.6, duration: 0.8, ease: [0.22, 1, 0.36, 1] }}
        className="flex max-w-2xl items-center gap-5 rounded-2xl border bg-white/85 backdrop-blur-xl p-5"
        style={{ borderColor: "var(--color-hairline)", boxShadow: "var(--shadow-lift)" }}
      >
        <MatchRing value={m.match_score} size={72} label="match" />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-display text-lg font-medium truncate">{m.posting.title}</span>
            <span className="text-muted-foreground">·</span>
            <span className="text-sm text-muted-foreground">{m.posting.company.name}</span>
          </div>
          <p className="text-sm text-muted-foreground mt-1 line-clamp-1">{m.match_explanation}</p>
          <div className="mt-3 flex items-center gap-2">
            <GhostBadge isGhost={false} score={0} />
            <Pill>Response <span className="font-mono ml-1">{Math.round(m.response_likelihood * 100)}%</span></Pill>
            <Pill tone="primary">Referral available</Pill>
          </div>
        </div>
      </motion.div>

      {ghost && (
        <motion.div
          initial={{ opacity: 0, y: 10, rotate: -2 }}
          animate={{ opacity: 1, y: [0, -8, 0], rotate: -2 }}
          transition={{ delay: 1.1, duration: 6, repeat: Infinity, ease: "easeInOut" }}
          className="absolute right-0 -bottom-12 w-[320px] rounded-2xl border bg-white p-4"
          style={{ borderColor: "var(--color-hairline)", boxShadow: "var(--shadow-lift)" }}
          aria-label="Likely ghost posting — skip"
        >
          <span className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium"
                style={{ background: "color-mix(in oklab, var(--color-ghost) 14%, white)", color: "color-mix(in oklab, var(--color-ghost) 80%, black)" }}>
            <Ghost className="h-3.5 w-3.5" /> Likely ghost — skip
          </span>
          <div className="mt-2 font-display text-lg font-medium leading-tight">{ghost.posting.title}</div>
          <div className="mt-1 text-xs text-muted-foreground">
            {ghost.posting.company.name} · posted {Math.max(7, Math.round((Date.now() - new Date(ghost.posting.posted_at).getTime()) / 86400000))}d ago
          </div>
        </motion.div>
      )}
    </div>
  );
}

function StatBand() {
  const authenticated = typeof localStorage !== "undefined" ? !!getToken() || isGuestMode() : false;
  const { data: digest } = useApi(
    () => (authenticated ? api.getDashboardDigest() : Promise.resolve(null)),
    [authenticated],
  );

  const stats = [
    {
      label: "Hours saved",
      value: digest ? Math.round(digest.ghosts_avoided * 2 + 1.5) : 41,
      suffix: "h",
    },
    {
      label: "Ghost jobs filtered",
      value: digest?.ghosts_avoided ?? 23,
      suffix: "",
    },
    {
      label: "Response rate",
      value: digest ? Math.round(digest.platform_iq) : 34,
      suffix: "%",
    },
    {
      label: "Platform IQ",
      value: digest?.platform_iq ?? 78,
      suffix: "",
    },
  ];

  return (
    <section className="relative border-y" style={{ borderColor: "var(--color-hairline)" }}>
      <div className="mx-auto max-w-7xl px-6 py-14 grid grid-cols-2 md:grid-cols-4 gap-y-10 gap-x-6">
        {stats.map((s, i) => (
          <Reveal key={s.label} delay={i * 0.05}>
            <div className="text-[10px] uppercase tracking-[0.22em] text-muted-foreground">{s.label}</div>
            <div className="mt-3 font-display text-5xl md:text-6xl font-medium tracking-tight">
              <AnimatedCounter to={s.value} suffix={s.suffix} duration={1.6} />
            </div>
          </Reveal>
        ))}
      </div>
    </section>
  );
}

function Pillars() {
  return (
    <section className="mx-auto max-w-7xl px-6 py-32">
      <Reveal>
        <SectionLabel>Three things we do differently</SectionLabel>
        <h2 className="mt-4 max-w-3xl font-display text-5xl md:text-6xl font-medium tracking-tight text-balance">
          The opposite of mass-blast bots.
        </h2>
      </Reveal>

      <div className="mt-16 grid gap-6 md:grid-cols-2">
        <Reveal>
          <PillarCard
            tone="warm"
            badge="Ghost-Job Shield"
            icon={Ghost}
            title="1 in 5 postings is a phantom. We delete them from your evening."
            body="Recruiter activity, repost cadence, time-to-fill and a dozen other signals score every posting. The dead ones never reach your feed."
            visual={<GhostShieldGrid />}
          />
        </Reveal>
        <Reveal delay={0.05}>
          <PillarCard
            badge="Referral-first"
            icon={Users}
            title="A warm intro converts 8×. We find yours, then draft it."
            body="Alumni, mutuals and second-degree connections at your target companies — with a respectful opener written in your voice."
            visual={<ReferralNodes />}
          />
        </Reveal>
        <Reveal delay={0.1}>
          <PillarCard
            tone="warm"
            badge="Quality over quantity"
            icon={Sparkles}
            title="Grounded in your real work. ATS-clean. You approve every send."
            body="Your GitHub projects, internships and write-ups are the source of truth. We translate them into the language each posting actually rewards."
            visual={<ProjectToDraft />}
          />
        </Reveal>
        <Reveal delay={0.15}>
          <PillarCard
            badge="Career Twin"
            icon={GitBranch}
            title="One profile. Every application personalized."
            body="Connect your résumé and GitHub once. We keep a living model of what you've actually shipped, and rewrite each application against the specific job."
            visual={<CareerTwinFan />}
          />
        </Reveal>
      </div>
    </section>
  );
}

function PillarCard({ badge, title, body, icon: Icon, visual, tone = "primary" }: {
  badge: string; title: string; body: string; icon: any; visual?: React.ReactNode; tone?: "primary" | "warm";
}) {
  const tintBg = tone === "warm"
    ? "color-mix(in oklab, var(--color-warm) 14%, white)"
    : "var(--color-primary-tint)";
  const tintFg = tone === "warm"
    ? "color-mix(in oklab, var(--color-warm) 80%, black)"
    : "var(--color-primary)";
  return (
    <div className="card-soft card-lift h-full p-8 md:p-10 flex flex-col">
      <div className="inline-flex items-center gap-2 self-start">
        <span className="grid h-8 w-8 place-items-center rounded-lg" style={{ background: tintBg, color: tintFg }}>
          <Icon className="h-4 w-4" />
        </span>
        <span className="text-[10px] uppercase tracking-[0.22em] font-medium text-muted-foreground">{badge}</span>
      </div>
      <h3 className="mt-6 font-display text-3xl md:text-4xl font-medium leading-[1.1] tracking-tight text-balance">{title}</h3>
      <p className="mt-4 text-muted-foreground leading-relaxed">{body}</p>
      {visual && <div className="mt-8">{visual}</div>}
    </div>
  );
}

// ---------- Pillar visuals ----------

function GhostShieldGrid() {
  // 10 tiles, ghosts at indices 2, 5, 9
  const tiles = Array.from({ length: 10 }, (_, i) => ({ ghost: i === 2 || i === 5 || i === 9 }));
  return (
    <div className="grid grid-cols-5 gap-2.5">
      {tiles.map((t, i) => (
        <motion.div
          key={i}
          initial={{ opacity: 0, y: 6 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ delay: i * 0.05, duration: 0.4 }}
          className="aspect-[5/3] rounded-lg grid place-items-center"
          style={{
            background: t.ghost ? "color-mix(in oklab, var(--color-ghost) 10%, white)" : "white",
            border: t.ghost ? "1px dashed color-mix(in oklab, var(--color-ghost) 60%, white)" : "1px solid var(--color-hairline)",
          }}
        >
          {t.ghost ? (
            <motion.div
              animate={{ opacity: [0.5, 1, 0.5] }}
              transition={{ duration: 2.8, repeat: Infinity, delay: i * 0.2 }}
            >
              <Ghost className="h-4 w-4" style={{ color: "color-mix(in oklab, var(--color-ghost) 80%, black)" }} />
            </motion.div>
          ) : (
            <Check className="h-4 w-4" style={{ color: "var(--color-primary)" }} />
          )}
        </motion.div>
      ))}
    </div>
  );
}

function ReferralNodes() {
  const contacts = [
    { id: "M.I", x: 230, y: 50 },
    { id: "S.R", x: 250, y: 130 },
    { id: "N.W", x: 340, y: 80 },
  ];
  return (
    <div className="relative h-44 w-full">
      <svg viewBox="0 0 400 180" className="absolute inset-0 w-full h-full" aria-hidden>
        {contacts.map((c, i) => (
          <motion.path
            key={c.id}
            d={`M 70 90 Q ${(70 + c.x) / 2} ${c.y - 30} ${c.x} ${c.y}`}
            stroke="var(--color-primary)"
            strokeOpacity={0.45}
            strokeWidth="1.2"
            strokeDasharray="4 4"
            fill="none"
            initial={{ pathLength: 0 }}
            whileInView={{ pathLength: 1 }}
            viewport={{ once: true }}
            transition={{ duration: 1.4, delay: 0.2 + i * 0.2, ease: "easeInOut" }}
          />
        ))}
      </svg>
      <div className="absolute" style={{ left: 70 - 26, top: 90 - 26 }}>
        <div className="h-13 w-13 rounded-full grid place-items-center text-sm font-mono font-medium"
             style={{ height: 52, width: 52, background: "var(--color-primary)", color: "var(--color-primary-foreground)" }}>
          You
        </div>
      </div>
      {contacts.map((c) => (
        <motion.div
          key={c.id}
          initial={{ opacity: 0, scale: 0.8 }}
          whileInView={{ opacity: 1, scale: 1 }}
          viewport={{ once: true }}
          transition={{ delay: 0.9, duration: 0.4 }}
          className="absolute h-12 w-12 rounded-full grid place-items-center text-xs font-mono"
          style={{
            left: c.x - 24, top: c.y - 24,
            background: "color-mix(in oklab, var(--color-primary) 15%, white)",
            color: "var(--color-primary)",
            border: "1px solid color-mix(in oklab, var(--color-primary) 25%, white)",
          }}
        >
          {c.id}
        </motion.div>
      ))}
    </div>
  );
}

function ProjectToDraft() {
  return (
    <div className="grid gap-3 md:grid-cols-2">
      <div className="rounded-xl border bg-surface p-4" style={{ borderColor: "var(--color-hairline)" }}>
        <div className="text-[10px] uppercase tracking-[0.2em] text-muted-foreground">Your project</div>
        <div className="mt-2 font-display text-lg">paper-mind</div>
        <div className="text-xs text-muted-foreground mt-0.5">Local-first RAG over arXiv with citation tracing.</div>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {["LLM", "RAG", "Next.js"].map((t) => <Pill key={t}>{t}</Pill>)}
        </div>
      </div>
      <div className="rounded-xl p-4" style={{ background: "var(--color-primary)", color: "var(--color-primary-foreground)" }}>
        <div className="text-[10px] uppercase tracking-[0.2em]" style={{ color: "color-mix(in oklab, white 70%, var(--color-primary))" }}>Draft → Anthropic</div>
        <p className="mt-2 text-[13px] leading-relaxed">
          "At CampusLab I trained a small transformer for code search; evaluation rigor was the limiter, which is exactly what your evals team is solving…"
        </p>
        <button className="mt-3 inline-flex items-center gap-1.5 text-xs font-medium" style={{ color: "color-mix(in oklab, white 90%, var(--color-primary))" }}>
          <Send className="h-3.5 w-3.5" /> Review & send
        </button>
      </div>
    </div>
  );
}

function CareerTwinFan() {
  const targets = [
    { label: "Linear · Editor", y: 30 },
    { label: "Anthropic · Inference", y: 75 },
    { label: "Vercel · Dashboard", y: 120 },
    { label: "Ramp · Platform", y: 165 },
  ];
  return (
    <div className="relative h-52 w-full">
      <svg viewBox="0 0 400 200" className="absolute inset-0 w-full h-full" aria-hidden>
        {targets.map((t, i) => (
          <motion.path
            key={t.label}
            d={`M 60 100 C 180 100, 200 ${t.y}, 290 ${t.y}`}
            fill="none"
            stroke="var(--color-primary)"
            strokeOpacity={0.4}
            strokeWidth="1.2"
            initial={{ pathLength: 0, opacity: 0 }}
            whileInView={{ pathLength: 1, opacity: 1 }}
            viewport={{ once: true }}
            transition={{ duration: 1.2, delay: 0.15 * i, ease: "easeInOut" }}
          />
        ))}
      </svg>
      <div className="absolute" style={{ left: 60 - 30, top: 100 - 30 }}>
        <div className="h-15 w-15 rounded-full grid place-items-center text-[11px] font-mono leading-tight text-center"
             style={{ height: 60, width: 60, background: "var(--color-primary)", color: "var(--color-primary-foreground)", padding: 6 }}>
          Career<br/>Twin
        </div>
      </div>
      {targets.map((t, i) => (
        <motion.div
          key={t.label}
          initial={{ opacity: 0, x: -8 }}
          whileInView={{ opacity: 1, x: 0 }}
          viewport={{ once: true }}
          transition={{ delay: 0.5 + i * 0.1 }}
          className="absolute text-xs rounded-lg border bg-white px-2.5 py-1.5 font-mono"
          style={{ left: 290, top: t.y - 14, borderColor: "var(--color-hairline)" }}
        >
          {t.label}
        </motion.div>
      ))}
    </div>
  );
}

function HowItWorks() {
  const steps = [
    { n: "01", icon: FileText, title: "Build your Career Twin", body: "Drop in your résumé, connect GitHub, set your bar. We build a living model of your real work." },
    { n: "02", icon: ShieldCheck, title: "Get a real match feed", body: "Ghost-job shield filters the dead ones. What's left is ranked by what you can actually win." },
    { n: "03", icon: Send, title: "Apply with a warm intro", body: "Approve a grounded, ATS-strong application, or skip the apply form and send the warm intro." },
  ];
  return (
    <section className="mx-auto max-w-7xl px-6 py-32 border-t" style={{ borderColor: "var(--color-hairline)" }}>
      <Reveal>
        <SectionLabel>How it works</SectionLabel>
        <h2 className="mt-4 max-w-3xl font-display text-5xl md:text-6xl font-medium tracking-tight text-balance">
          Three steps. Then you stop guessing.
        </h2>
      </Reveal>
      <div className="mt-16 grid gap-10 md:grid-cols-3">
        {steps.map((s, i) => (
          <Reveal key={s.n} delay={i * 0.08}>
            <div className="font-mono text-xs text-muted-foreground">{s.n}</div>
            <s.icon className="mt-4 h-6 w-6" style={{ color: "var(--color-primary)" }} />
            <h3 className="mt-4 font-display text-2xl font-medium">{s.title}</h3>
            <p className="mt-2 text-muted-foreground leading-relaxed">{s.body}</p>
          </Reveal>
        ))}
      </div>
    </section>
  );
}

function PlatformIQ() {
  return (
    <section className="mx-auto max-w-7xl px-6">
      <div className="card-soft p-10 md:p-16 grid gap-10 md:grid-cols-2 items-center">
        <div>
          <SectionLabel icon={BarChart3}>Platform IQ</SectionLabel>
          <h2 className="mt-4 font-display text-4xl md:text-5xl font-medium tracking-tight text-balance">
            It gets smarter every application.
          </h2>
          <p className="mt-4 text-muted-foreground leading-relaxed max-w-md">
            Every response, every interview, every ghost feeds back into the model. By application 20, the curve has bent in your favor.
          </p>
        </div>
        <IQCurve />
      </div>
    </section>
  );
}

function IQCurve() {
  return (
    <div className="relative h-64">
      <svg viewBox="0 0 400 200" className="w-full h-full">
        <defs>
          <linearGradient id="iq" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--color-primary)" stopOpacity="0.35" />
            <stop offset="100%" stopColor="var(--color-primary)" stopOpacity="0" />
          </linearGradient>
        </defs>
        {[40, 80, 120, 160].map((y) => <line key={y} x1="0" y1={y} x2="400" y2={y} stroke="var(--color-hairline)" />)}
        <path d="M 0 170 C 60 165 100 150 160 120 S 280 50 400 25 L 400 200 L 0 200 Z" fill="url(#iq)" />
        <path d="M 0 170 C 60 165 100 150 160 120 S 280 50 400 25" fill="none" stroke="var(--color-primary)" strokeWidth="2.5" />
        {[[0, 170], [80, 158], [160, 120], [240, 90], [320, 55], [400, 25]].map(([x, y], i) => (
          <circle key={i} cx={x} cy={y} r="3.5" fill="white" stroke="var(--color-primary)" strokeWidth="2" />
        ))}
      </svg>
    </div>
  );
}

function Quotes() {
  const quotes = [
    {
      q: "I stopped doom-scrolling job boards. The first three roles in my feed were ones I would have missed — and one had an alum.",
      name: "Priya M.",
      school: "Waterloo · CS '26",
    },
    {
      q: "The ghost-job filter alone is worth it. I used to apply to 60 and hear back from 2. Now I apply to 8 and hear back from 4.",
      name: "Jordan R.",
      school: "Berkeley · EECS '26",
    },
    {
      q: "It writes like me, not like ChatGPT. The reviewer at Figma actually quoted a line from my draft.",
      name: "Anaya S.",
      school: "NYU · IDM '27",
    },
  ];
  return (
    <section className="mx-auto max-w-7xl px-6 py-32">
      <Reveal><SectionLabel>From the first cohort</SectionLabel></Reveal>
      <div className="mt-10 grid gap-6 md:grid-cols-3">
        {quotes.map((q, i) => (
          <Reveal key={i} delay={i * 0.08}>
            <figure className="card-soft p-8 h-full flex flex-col">
              <QuoteIcon />
              <blockquote className="mt-5 font-display text-[22px] leading-snug text-balance">
                &ldquo;{q.q}&rdquo;
              </blockquote>
              <figcaption className="mt-auto pt-8 flex items-end justify-between gap-3">
                <div>
                  <div className="text-sm font-medium">{q.name}</div>
                  <div className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground font-mono mt-1">{q.school}</div>
                </div>
                <span className="inline-flex items-center gap-1.5 rounded-full border bg-white px-2.5 py-1 text-[11px] font-medium"
                      style={{ borderColor: "var(--color-hairline)" }}>
                  <span className="h-1.5 w-1.5 rounded-full" style={{ background: "var(--color-success)" }} />
                  Offer in hand
                </span>
              </figcaption>
            </figure>
          </Reveal>
        ))}
      </div>
    </section>
  );
}

function QuoteIcon() {
  return (
    <svg width="28" height="20" viewBox="0 0 28 20" fill="none" aria-hidden>
      <path d="M0 20V12C0 5.4 4.2 1 10 0L11 3C7.4 4 5 6.6 5 10H10V20H0ZM17 20V12C17 5.4 21.2 1 27 0L28 3C24.4 4 22 6.6 22 10H27V20H17Z"
            fill="var(--color-primary)" />
    </svg>
  );
}

function CTA() {
  return (
    <section className="relative mx-auto max-w-7xl px-6 py-24">
      <div className="relative overflow-hidden rounded-3xl p-12 md:p-20 text-center"
           style={{ background: "linear-gradient(135deg, var(--color-primary) 0%, #0A4838 60%, #16140F 100%)" }}>
        <h2 className="font-display text-5xl md:text-7xl font-medium tracking-tight text-balance" style={{ color: "#FAF8F4" }}>
          Apply where you can win.
        </h2>
        <p className="mt-5 max-w-xl mx-auto text-base md:text-lg" style={{ color: "rgba(250,248,244,0.7)" }}>
          Build your Career Twin in under two minutes. We'll show you a real match feed.
        </p>
        <div className="mt-10">
          <Link
            to="/onboarding"
            className="inline-flex items-center gap-2 rounded-full bg-white px-7 py-4 text-sm font-medium text-foreground hover:-translate-y-0.5 transition-transform"
          >
            Get started — free <ArrowRight className="h-4 w-4" />
          </Link>
        </div>
      </div>
    </section>
  );
}
