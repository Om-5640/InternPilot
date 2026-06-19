import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { LiveBackground } from "@/components/live-background";
import { Compass, ArrowRight, UserRound } from "lucide-react";
import { useState, useEffect, useRef } from "react";
import { authLogin, authSignup, authGoogleLogin, setGuestMode } from "@/lib/api-client";

const GOOGLE_CLIENT_ID: string = import.meta.env.VITE_GOOGLE_CLIENT_ID || "";

export const Route = createFileRoute("/auth")({
  head: () => ({ meta: [{ title: "Sign in — InternPilot" }, { name: "description", content: "Sign in to InternPilot." }] }),
  component: Auth,
});

function Auth() {
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const googleBtnRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!GOOGLE_CLIENT_ID || typeof window === "undefined") return;
    const initGoogle = () => {
      const g = (window as any).google;
      if (!g) return;
      g.accounts.id.initialize({
        client_id: GOOGLE_CLIENT_ID,
        callback: async (response: { credential: string }) => {
          setError(null);
          try {
            await authGoogleLogin(response.credential);
            navigate({ to: "/onboarding" });
          } catch (err: any) {
            setError(err?.message ?? "Google sign-in failed. Please try again.");
          }
        },
      });
      if (googleBtnRef.current) {
        g.accounts.id.renderButton(googleBtnRef.current, {
          theme: "outline",
          size: "large",
          width: googleBtnRef.current.offsetWidth || 360,
          text: "continue_with",
          shape: "pill",
        });
      }
    };
    if ((window as any).google?.accounts) {
      initGoogle();
    } else {
      const script = document.createElement("script");
      script.src = "https://accounts.google.com/gsi/client";
      script.async = true;
      script.defer = true;
      script.onload = initGoogle;
      document.head.appendChild(script);
    }
  }, []);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      setError("Enter a valid email address.");
      return;
    }
    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    if (mode === "signup" && !name.trim()) {
      setError("Please enter your name.");
      return;
    }
    setSubmitting(true);
    try {
      if (mode === "signup") {
        await authSignup(name.trim(), email, password);
      } else {
        await authLogin(email, password);
      }
      navigate({ to: "/onboarding" });
    } catch (err: any) {
      // err.message now comes directly from the backend (e.g. "Incorrect email or password")
      setError(err?.message ?? "Something went wrong. Please try again.");
    } finally {
      setSubmitting(false);
    }
  };

  const continueAsGuest = () => {
    setGuestMode(true);
    navigate({ to: "/feed" });
  };

  return (
    <div className="min-h-screen grid lg:grid-cols-2">
      <div className="relative hidden lg:block overflow-hidden">
        <LiveBackground />
        <div className="relative z-10 p-12 flex flex-col h-full">
          <Link to="/" className="inline-flex items-center gap-2">
            <span className="grid h-8 w-8 place-items-center rounded-full bg-primary text-primary-foreground">
              <Compass className="h-4 w-4" />
            </span>
            <span className="font-display text-lg font-semibold">InternPilot</span>
          </Link>
          <div className="mt-auto max-w-md">
            <p className="font-display text-4xl leading-tight tracking-tight text-balance">
              &ldquo;I&apos;d applied to 80 places. InternPilot cut my list to 12 — and got me three interviews in a week.&rdquo;
            </p>
            <p className="mt-4 text-sm text-muted-foreground font-mono">— Maya, CS @ Berkeley</p>
          </div>
        </div>
      </div>

      <div className="flex items-center justify-center p-8">
        <div className="w-full max-w-sm">
          <div className="lg:hidden mb-12 flex items-center gap-2">
            <span className="grid h-8 w-8 place-items-center rounded-full bg-primary text-primary-foreground">
              <Compass className="h-4 w-4" />
            </span>
            <span className="font-display text-lg font-semibold">InternPilot</span>
          </div>
          <h1 className="font-display text-4xl font-medium tracking-tight">
            {mode === "login" ? "Welcome back." : "Create account."}
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            {mode === "login" ? "Sign in to your InternPilot account." : "Join InternPilot — free to start."}
          </p>

          <div className="mt-8 flex rounded-full border overflow-hidden" style={{ borderColor: "var(--color-hairline)" }}>
            <button
              type="button"
              onClick={() => { setMode("login"); setError(null); }}
              className={`flex-1 py-2 text-sm font-medium transition ${mode === "login" ? "bg-primary text-primary-foreground" : "bg-white text-muted-foreground hover:bg-secondary"}`}
            >
              Sign in
            </button>
            <button
              type="button"
              onClick={() => { setMode("signup"); setError(null); }}
              className={`flex-1 py-2 text-sm font-medium transition ${mode === "signup" ? "bg-primary text-primary-foreground" : "bg-white text-muted-foreground hover:bg-secondary"}`}
            >
              Sign up
            </button>
          </div>

          <form className="mt-6 space-y-3" onSubmit={onSubmit} noValidate>
            {mode === "signup" && (
              <>
                <label className="sr-only" htmlFor="name">Full name</label>
                <input
                  id="name" name="name" type="text" autoComplete="name" required={mode === "signup"}
                  value={name} onChange={(e) => setName(e.target.value)}
                  placeholder="Full name"
                  className="w-full rounded-xl border bg-white px-4 py-3 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--ring)]"
                  style={{ borderColor: "var(--color-hairline)" }}
                />
              </>
            )}
            <label className="sr-only" htmlFor="email">Email</label>
            <input
              id="email" name="email" type="email" autoComplete="email" required
              value={email} onChange={(e) => setEmail(e.target.value)}
              placeholder="you@school.edu"
              className="w-full rounded-xl border bg-white px-4 py-3 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--ring)]"
              style={{ borderColor: "var(--color-hairline)" }}
            />
            <label className="sr-only" htmlFor="password">Password</label>
            <input
              id="password" name="password" type="password" autoComplete={mode === "signup" ? "new-password" : "current-password"} required minLength={8}
              value={password} onChange={(e) => setPassword(e.target.value)}
              placeholder="Password (8+ characters)"
              className="w-full rounded-xl border bg-white px-4 py-3 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--ring)]"
              style={{ borderColor: "var(--color-hairline)" }}
            />
            {error && (
              <div className="text-xs" role="alert" style={{ color: "var(--color-reject)" }}>{error}</div>
            )}
            <button
              type="submit" disabled={submitting}
              className="w-full inline-flex items-center justify-center gap-2 rounded-full bg-primary px-5 py-3 text-sm font-medium text-primary-foreground hover:bg-[color:var(--primary-hover)] transition disabled:opacity-60"
            >
              {submitting ? (mode === "signup" ? "Creating account…" : "Signing in…") : "Continue"} <ArrowRight className="h-4 w-4" />
            </button>
          </form>

          <div className="mt-4 relative">
            <div className="absolute inset-0 flex items-center"><div className="w-full border-t" style={{ borderColor: "var(--color-hairline)" }} /></div>
            <div className="relative flex justify-center"><span className="bg-white px-3 text-xs text-muted-foreground">or</span></div>
          </div>

          {GOOGLE_CLIENT_ID && (
            <div ref={googleBtnRef} className="mt-4 w-full flex justify-center" />
          )}

          <button
            type="button"
            onClick={continueAsGuest}
            className="mt-4 w-full inline-flex items-center justify-center gap-2 rounded-full border px-5 py-3 text-sm font-medium text-foreground hover:bg-secondary transition"
            style={{ borderColor: "var(--color-hairline)" }}
          >
            <UserRound className="h-4 w-4 text-muted-foreground" />
            Continue as guest
          </button>

          <p className="mt-8 text-xs text-muted-foreground">
            By continuing you agree to our terms. We never spray your applications.
          </p>
        </div>
      </div>
    </div>
  );
}
