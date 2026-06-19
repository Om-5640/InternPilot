import { createFileRoute } from "@tanstack/react-router";
import { useState, useEffect, useRef } from "react";
import { CalmBackground } from "@/components/live-background";
import { Nav } from "@/components/nav";
import { api, useApi } from "@/lib/api-client";
import { AnimatedCounter } from "@/components/motion-primitives";
import { LoadingState, ErrorState } from "@/components/data-states";
import { Bell } from "lucide-react";
import type { DashboardSummary, Notification } from "@/lib/mocks";

export const Route = createFileRoute("/dashboard")({
  head: () => ({ meta: [{ title: "Dashboard — InternPilot" }, { name: "description", content: "Platform IQ, response rate, ghosts avoided." }] }),
  component: Dashboard,
});

function Dashboard() {
  const d = useApi(() => api.getDashboard(), []);
  const n = useApi(() => api.getNotifications(), []);

  return (
    <div className="min-h-screen">
      <CalmBackground />
      <Nav />
      <main className="mx-auto max-w-7xl px-6 py-12">
        {(d.loading || n.loading) && <LoadingState label="Loading dashboard" />}
        {d.error && <ErrorState error={d.error} onRetry={d.reload} />}
        {n.error && <ErrorState error={n.error} onRetry={n.reload} />}
        {d.data && n.data && <DashboardInner d={d.data} notifications={n.data} />}
      </main>
    </div>
  );
}

function DashboardInner({ d, notifications: initialNotifications }: { d: DashboardSummary; notifications: Notification[] }) {
  const [notifications, setNotifications] = useState<Notification[]>(initialNotifications);
  const cohort = useApi(() => api.getCohortCompanies(), []);
  const activityRef = useRef<HTMLDivElement>(null);
  useEffect(() => { setNotifications(initialNotifications); }, [initialNotifications]);

  const markRead = async (id: string) => {
    setNotifications((prev) => prev.map((n) => n.id === id ? { ...n, read: true } : n));
    try { await api.markNotificationRead(id); } catch { /* revert on failure */ setNotifications((prev) => prev.map((n) => n.id === id ? { ...n, read: false } : n)); }
  };

  const scrollToActivity = () => activityRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });

  const unread = notifications.filter((x) => !x.read).length;
  const weekLabel = d.iq_trend.length > 0 ? `Week ${d.iq_trend.length}` : "Dashboard";
  return (
    <>
      <div className="flex items-end justify-between">
        <div>
          <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground font-mono">{weekLabel}</div>
          <h1 className="mt-2 font-display text-5xl md:text-6xl tracking-tight">The curve is bending.</h1>
        </div>
        <button
          onClick={scrollToActivity}
          className="hidden md:inline-flex items-center gap-2 rounded-full border bg-white px-3 py-1.5 text-xs hover:bg-secondary transition-colors"
          style={{ borderColor: "var(--color-hairline)" }}
          aria-label={`${unread} unread notifications — scroll to activity`}
        >
          <Bell className="h-3.5 w-3.5" /> Notifications · {unread} unread
        </button>
      </div>

      <div className="mt-10 grid gap-5 md:grid-cols-4">
        <Stat label="Response rate" value={d.response_rate * 100} suffix="%" decimals={0} />
        <Stat label="Hours saved" value={d.time_saved_hours} suffix="h" />
        <Stat label="Ghosts avoided" value={d.ghosts_avoided} />
        <Stat label="Platform IQ" value={d.platform_iq} />
      </div>

      <div className="mt-8 grid gap-6 md:grid-cols-[1.6fr_1fr]">
        <div className="card-soft p-8">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-xs uppercase tracking-[0.14em] text-muted-foreground">Platform IQ trend</div>
              <h2 className="mt-1 font-display text-2xl">It learns from every application.</h2>
            </div>
            <div className="font-mono text-3xl" style={{ color: "var(--color-primary)" }}>{d.platform_iq}</div>
          </div>
          <IQChart points={d.iq_trend} />
        </div>

        <div className="card-soft p-8">
          <div className="text-xs uppercase tracking-[0.14em] text-muted-foreground">Pipeline</div>
          <div className="mt-4 space-y-3">
            {Object.entries(d.pipeline).map(([k, v]) => (
              <div key={k}>
                <div className="flex justify-between text-sm">
                  <span className="capitalize">{k}</span>
                  <span className="font-mono">{v}</span>
                </div>
                <div className="mt-1.5 h-1.5 rounded-full bg-secondary overflow-hidden">
                  <div
                    className="h-full rounded-full"
                    style={{
                      width: `${Math.min(100, (v / 14) * 100)}%`,
                      background: k === "ghosted" || k === "rejected" ? "var(--color-ghost)" : "var(--color-primary)",
                    }}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="mt-8 grid gap-6 md:grid-cols-2">
        <div className="card-soft p-8">
          <div className="text-xs uppercase tracking-[0.14em] text-muted-foreground">Cohort intelligence</div>
          <h2 className="mt-1 font-display text-2xl">Where peers like you converted.</h2>
          {cohort.loading && <div className="mt-5 text-xs text-muted-foreground">Loading cohort data…</div>}
          {!cohort.loading && (!cohort.data || cohort.data.length === 0) && (
            <p className="mt-5 text-xs text-muted-foreground italic">No cohort data yet — stats appear as peers apply and get responses.</p>
          )}
          {!cohort.loading && cohort.data && cohort.data.length > 0 && (
            <ul className="mt-5 space-y-3 text-sm">
              {cohort.data.slice(0, 4).map((c) => (
                <Row key={c.company_name} company={c.company_name} rate={`${Math.round(c.response_rate * 100)}%`} note={c.note} />
              ))}
            </ul>
          )}
        </div>
        <div ref={activityRef} className="card-soft p-8">
          <div className="text-xs uppercase tracking-[0.14em] text-muted-foreground">Recent activity · digest</div>
          <ul className="mt-5 space-y-4">
            {notifications.map((n) => (
              <li key={n.id} className="flex items-start gap-3">
                <span
                  className="mt-1.5 h-1.5 w-1.5 rounded-full"
                  style={{ background: (n.type === "status_change" || n.type === "followup_due") ? "var(--color-ghost)" : "var(--color-primary)", opacity: n.read ? 0.4 : 1 }}
                />
                <div className="flex-1">
                  <div className={`text-sm ${n.read ? "text-muted-foreground" : ""}`}>{n.content}</div>
                  <div className="text-xs text-muted-foreground font-mono mt-0.5">
                    {new Date(n.created_at).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}
                  </div>
                </div>
                {!n.read && (
                  <button
                    onClick={() => markRead(n.id)}
                    className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground hover:text-foreground"
                  >
                    mark read
                  </button>
                )}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </>
  );
}

function Stat({ label, value, suffix = "", decimals = 0 }: { label: string; value: number; suffix?: string; decimals?: number }) {
  return (
    <div className="card-soft p-6">
      <div className="text-xs uppercase tracking-[0.14em] text-muted-foreground">{label}</div>
      <div className="mt-2 font-display text-4xl tracking-tight">
        <AnimatedCounter to={value} suffix={suffix} decimals={decimals} />
      </div>
    </div>
  );
}

function Row({ company, rate, note }: { company: string; rate: string; note: string }) {
  return (
    <li className="flex items-center justify-between border-b last:border-0 pb-3" style={{ borderColor: "var(--color-hairline)" }}>
      <div>
        <div className="font-medium">{company}</div>
        <div className="text-xs text-muted-foreground">{note}</div>
      </div>
      <div className="font-mono" style={{ color: "var(--color-primary)" }}>{rate}</div>
    </li>
  );
}

function IQChart({ points }: { points: { date: string; value: number }[] }) {
  const w = 600, h = 200, pad = 24;
  const max = 80;
  if (points.length === 0) {
    return <div className="mt-6 h-56 flex items-center justify-center text-xs text-muted-foreground">No data yet — apply to some roles to see your IQ trend.</div>;
  }
  const xs = (i: number) => points.length === 1 ? w / 2 : pad + (i * (w - pad * 2)) / (points.length - 1);
  const ys = (v: number) => h - pad - ((v / max) * (h - pad * 2));
  const path = points.map((p, i) => `${i ? "L" : "M"} ${xs(i)} ${ys(p.value)}`).join(" ");
  const area = `${path} L ${xs(points.length - 1)} ${h - pad} L ${pad} ${h - pad} Z`;
  return (
    <div className="mt-6">
      <svg viewBox={`0 0 ${w} ${h}`} className="w-full h-56" role="img" aria-label="Platform IQ trend, last 8 weeks">
        <defs>
          <linearGradient id="d" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--color-primary)" stopOpacity="0.3" />
            <stop offset="100%" stopColor="var(--color-primary)" stopOpacity="0" />
          </linearGradient>
        </defs>
        {[0.25, 0.5, 0.75].map((f) => <line key={f} x1={pad} x2={w - pad} y1={pad + (h - pad * 2) * f} y2={pad + (h - pad * 2) * f} stroke="var(--color-hairline)" />)}
        <path d={area} fill="url(#d)" />
        <path d={path} fill="none" stroke="var(--color-primary)" strokeWidth="2.5" />
        {points.map((p, i) => <circle key={i} cx={xs(i)} cy={ys(p.value)} r="3.5" fill="white" stroke="var(--color-primary)" strokeWidth="2" />)}
        {points.map((p, i) => <text key={p.date} x={xs(i)} y={h - 6} textAnchor="middle" fontSize="10" fill="currentColor" opacity="0.5" fontFamily="ui-monospace,monospace">{p.date}</text>)}
      </svg>
    </div>
  );
}
