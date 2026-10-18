import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { Link, useNavigate } from "@tanstack/react-router";
import { DEV_AUTH, ROLE_KEY, USE_MOCK, getStoredRole, isRole, type Role, type Status } from "./api";
import { fetchProfile, isSupabaseConfigured, supabase } from "./supabase";

export { STATUSES, type Role, type Status } from "./api";

/** The signed-in account. Shipments are not kept here; the API is the only writer. */
export type SessionUser = {
  id: string;
  email: string;
  name: string;
  role: Role;
};

type Ctx = {
  user: SessionUser | null;
  role: Role | null;
  hydrated: boolean;
  setUser: (user: SessionUser | null) => void;
  signOut: () => Promise<void>;
};

const C = createContext<Ctx | null>(null);

// Mock mode and dev login keep the picked role in localStorage; Supabase keeps real sessions.
const LOCAL_ROLE = USE_MOCK || DEV_AUTH;

function rememberMockRole(user: SessionUser | null) {
  if (!LOCAL_ROLE) return;
  try {
    if (user) localStorage.setItem(ROLE_KEY, user.role);
    else localStorage.removeItem(ROLE_KEY);
  } catch {
    // storage blocked: the mock role lasts for this page only
  }
}

export function StoreProvider({ children }: { children: ReactNode }) {
  const [user, setUserState] = useState<SessionUser | null>(null);
  const [hydrated, setHydrated] = useState(false);

  const setUser = (next: SessionUser | null) => {
    setUserState(next);
    rememberMockRole(next);
  };

  const signOut = async () => {
    if (isSupabaseConfigured) await supabase.auth.signOut();
    try {
      localStorage.removeItem(ROLE_KEY);
    } catch {
      // ignore
    }
    setUserState(null);
  };

  useEffect(() => {
    let cancel = false;

    const applyProfile = async (id: string, email: string) => {
      const profile = await fetchProfile(id);
      if (cancel || !profile || !isRole(profile.role)) return;
      setUser({
        id,
        email,
        name: profile.name || email || profile.role,
        role: profile.role,
      });
    };

    const boot = async () => {
      try {
        let sessionUser = null;
        if (isSupabaseConfigured) {
          const { data } = await supabase.auth.getSession();
          sessionUser = data.session?.user ?? null;
          if (sessionUser) await applyProfile(sessionUser.id, sessionUser.email ?? "");
        }
        if (!sessionUser && LOCAL_ROLE) {
          const role = getStoredRole();
          if (role) setUser({ id: `demo-${role}`, email: "", name: role, role });
        }
      } finally {
        if (!cancel) setHydrated(true);
      }
    };
    void boot();

    if (!isSupabaseConfigured)
      return () => {
        cancel = true;
      };

    const { data: sub } = supabase.auth.onAuthStateChange((event, session) => {
      if (event === "SIGNED_OUT" || !session?.user) {
        // No Supabase session is normal for a mock or dev-login user; keep them signed in.
        if (event !== "SIGNED_OUT" && LOCAL_ROLE && getStoredRole()) return;
        setUserState(null);
        return;
      }
      if (event === "INITIAL_SESSION" || event === "SIGNED_IN" || event === "USER_UPDATED") {
        void applyProfile(session.user.id, session.user.email ?? "");
      }
    });
    return () => {
      cancel = true;
      sub.subscription.unsubscribe();
    };
  }, []);

  return (
    <C.Provider value={{ user, role: user?.role ?? null, hydrated, setUser, signOut }}>
      {children}
    </C.Provider>
  );
}

export const useStore = () => useContext(C)!;

export const statusTone: Record<Status, string> = {
  Draft: "text-muted-foreground border-border",
  Agreed: "text-primary border-primary/40",
  "In Transit": "text-foreground border-border",
  Inspection: "text-warning border-warning/40",
  Proposed: "text-primary border-primary/40",
  Accepted: "text-success border-success/40",
  Disputed: "text-destructive border-destructive/40",
  Resolved: "text-success border-success/40",
};

export function Chip({ status }: { status: Status }) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-medium ${statusTone[status]}`}
    >
      {status}
    </span>
  );
}

export function Logo() {
  return (
    <Link to="/" className="flex items-center gap-2 font-semibold tracking-tight">
      <span className="h-5 w-5 rounded-md bg-sol" />
      ProofSettle
    </Link>
  );
}

export function TopBar() {
  const { user, role, signOut } = useStore();
  const nav = useNavigate();
  const label = user && user.name && user.name !== role ? `${user.name} · ${role}` : role;
  return (
    <header className="sticky top-0 z-10 border-b bg-background/80 backdrop-blur">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-6">
        <Logo />
        <div className="flex items-center gap-4 text-sm">
          <Link to="/dashboard" className="text-muted-foreground hover:text-foreground">
            Shipments
          </Link>
          {role && (
            <span className="rounded-full border px-3 py-1 text-xs">
              Signed in as <span className="font-medium text-primary">{label}</span>
            </span>
          )}
          <button
            onClick={() => {
              void signOut().then(() => nav({ to: "/login" }));
            }}
            className="text-muted-foreground hover:text-foreground"
          >
            Sign out
          </button>
        </div>
      </div>
    </header>
  );
}

/** A card-styled placeholder for loading, empty and error states. */
export function Notice({ children, tone }: { children: ReactNode; tone?: "error" }) {
  return (
    <div
      className={`card-surface p-8 text-center fade-up ${tone === "error" ? "text-destructive" : "text-muted-foreground"}`}
    >
      {children}
    </div>
  );
}

/** The API's "detail" for a failed write, in the existing destructive style. */
export function ErrorNote({ error }: { error: Error | null }) {
  if (!error) return null;
  return (
    <p className="mt-4 rounded-xl border border-destructive/40 px-4 py-3 text-sm text-destructive">
      {error.message}
    </p>
  );
}

/** Shown in place of page content when nobody is signed in yet. */
export function PickRole() {
  return (
    <Notice>
      Sign in to continue.{" "}
      <Link to="/login" className="text-primary">
        Sign in
      </Link>
    </Notice>
  );
}
