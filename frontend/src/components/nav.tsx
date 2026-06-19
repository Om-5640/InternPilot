import { Link, useNavigate } from "@tanstack/react-router";
import { Compass, LogOut, User, ChevronDown, Github } from "lucide-react";
import { useState, useEffect, useRef } from "react";
import { getStoredUser, authLogout, isGuestMode, type User as AppUser } from "@/lib/api-client";

const links = [
  { to: "/", label: "Home" },
  { to: "/feed", label: "Match Feed" },
  { to: "/tracker", label: "Tracker" },
  { to: "/dashboard", label: "Dashboard" },
  { to: "/referrals", label: "Referrals" },
  { to: "/outreach", label: "Outreach" },
];

function getInitials(name: string): string {
  const parts = name.trim().split(/\s+/);
  if (parts.length === 1) return parts[0][0]?.toUpperCase() ?? "?";
  return ((parts[0][0] ?? "") + (parts[parts.length - 1][0] ?? "")).toUpperCase();
}

export function Nav() {
  const navigate = useNavigate();
  const [authUser, setAuthUser] = useState<AppUser | null>(null);
  const [guest, setGuest] = useState(false);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setAuthUser(getStoredUser());
    setGuest(isGuestMode());
  }, []);

  // Close dropdown when clicking outside
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setDropdownOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const handleLogout = async () => {
    await authLogout();
    setAuthUser(null);
    setGuest(false);
    setDropdownOpen(false);
    navigate({ to: "/auth" });
  };

  const loggedIn = !!authUser;

  return (
    <header className="sticky top-0 z-40 w-full">
      <div className="mx-auto max-w-7xl px-6">
        <div className="mt-4 flex items-center justify-between rounded-full border border-hairline bg-white/70 px-5 py-2.5 backdrop-blur-xl shadow-soft"
             style={{ borderColor: "var(--color-hairline)", boxShadow: "var(--shadow-soft)" }}>
          <Link to="/" className="flex items-center gap-2 group">
            <span className="grid h-8 w-8 place-items-center rounded-full bg-primary text-primary-foreground">
              <Compass className="h-4 w-4" />
            </span>
            <span className="font-display text-lg font-semibold tracking-tight">InternPilot</span>
          </Link>
          <nav className="hidden md:flex items-center gap-1 text-sm text-muted-foreground">
            {links.map((l) => (
              <Link
                key={l.to}
                to={l.to}
                activeOptions={{ exact: l.to === "/" }}
                className="px-3 py-1.5 rounded-full transition-colors hover:text-foreground hover:bg-secondary"
                activeProps={{ className: "px-3 py-1.5 rounded-full text-foreground bg-secondary" }}
              >
                {l.label}
              </Link>
            ))}
          </nav>
          <div className="flex items-center gap-2">
            {loggedIn ? (
              <div className="relative" ref={dropdownRef}>
                <button
                  onClick={() => setDropdownOpen((o) => !o)}
                  className="flex items-center gap-2 rounded-full border px-3 py-1.5 text-sm font-medium hover:bg-secondary transition"
                  style={{ borderColor: "var(--color-hairline)" }}
                >
                  <span className="grid h-7 w-7 place-items-center rounded-full bg-primary text-primary-foreground text-xs font-bold">
                    {getInitials(authUser.name)}
                  </span>
                  <span className="hidden sm:block">{authUser.name.split(" ")[0]}</span>
                  <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
                </button>
                {dropdownOpen && (
                  <div className="absolute right-0 mt-2 w-44 rounded-xl border bg-white shadow-lg py-1 text-sm"
                       style={{ borderColor: "var(--color-hairline)" }}>
                    <Link
                      to="/onboarding"
                      onClick={() => setDropdownOpen(false)}
                      className="flex items-center gap-2 px-4 py-2 text-foreground hover:bg-secondary transition"
                    >
                      <User className="h-4 w-4 text-muted-foreground" />
                      Profile
                    </Link>
                    <button
                      onClick={handleLogout}
                      className="w-full flex items-center gap-2 px-4 py-2 text-foreground hover:bg-secondary transition"
                    >
                      <LogOut className="h-4 w-4 text-muted-foreground" />
                      Sign out
                    </button>
                  </div>
                )}
              </div>
            ) : guest ? (
              <>
                <span className="hidden sm:inline-flex text-xs text-muted-foreground bg-secondary rounded-full px-3 py-1.5">
                  Guest mode
                </span>
                <Link
                  to="/auth"
                  className="inline-flex items-center rounded-full bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-[color:var(--primary-hover)]"
                >
                  Sign up
                </Link>
              </>
            ) : (
              <>
                <Link to="/auth" className="hidden sm:inline-flex text-sm text-muted-foreground hover:text-foreground px-3 py-1.5">
                  Sign in
                </Link>
                <Link
                  to="/onboarding"
                  className="inline-flex items-center rounded-full bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-[color:var(--primary-hover)]"
                >
                  Get started
                </Link>
              </>
            )}
          </div>
        </div>
      </div>
    </header>
  );
}

export function Footer() {
  return (
    <footer className="mt-32 border-t border-hairline" style={{ borderColor: "var(--color-hairline)" }}>
      <div className="mx-auto max-w-7xl px-6 py-16 grid gap-12 md:grid-cols-4">
        <div className="md:col-span-2">
          <div className="flex items-center gap-2">
            <span className="grid h-8 w-8 place-items-center rounded-full bg-primary text-primary-foreground">
              <Compass className="h-4 w-4" />
            </span>
            <span className="font-display text-lg font-semibold">InternPilot</span>
          </div>
          <p className="mt-4 max-w-md text-sm text-muted-foreground">
            The opposite of mass-blast bots. Apply only where you can actually win.
          </p>
        </div>
        <div className="text-sm">
          <div className="font-medium mb-3">Product</div>
          <ul className="space-y-2 text-muted-foreground">
            <li><Link to="/feed" className="hover:text-foreground">Match feed</Link></li>
            <li><Link to="/tracker" className="hover:text-foreground">Tracker</Link></li>
            <li><Link to="/dashboard" className="hover:text-foreground">Dashboard</Link></li>
          </ul>
        </div>
        <div className="text-sm">
          <div className="font-medium mb-3">Get started</div>
          <ul className="space-y-2 text-muted-foreground">
            <li><Link to="/onboarding" className="hover:text-foreground">Build your Career Twin</Link></li>
            <li><Link to="/auth" className="hover:text-foreground">Sign in</Link></li>
            <li><Link to="/referrals" search={{ posting_id: undefined }} className="hover:text-foreground">Referrals</Link></li>
          </ul>
        </div>
      </div>
      <div className="mx-auto max-w-7xl px-6 pb-10 text-xs text-muted-foreground flex items-center justify-between">
        <span>© 2026 InternPilot</span>
        <a
          href="https://github.com/Om-5640/InternPilot"
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1.5 hover:text-foreground transition-colors"
        >
          <Github className="h-3.5 w-3.5" />
          GitHub
        </a>
        <span className="font-mono">v0.9 · platform IQ rising</span>
      </div>
    </footer>
  );
}
