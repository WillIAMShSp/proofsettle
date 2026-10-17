import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { Link, useNavigate } from "@tanstack/react-router";
import { ROLE_KEY, getStoredRole, type Role, type Status } from "./api";

export { STATUSES, type Role, type Status } from "./api";

// `hydrated` turns true once the role has been read from localStorage in the browser, so
// pages can tell "not loaded yet" (SSR, first render) from "no role picked".
type Ctx = { role: Role | null; setRole: (r: Role | null) => void; hydrated: boolean };
const C = createContext<Ctx | null>(null);

export function StoreProvider({ children }: { children: ReactNode }) {
  const [role, setRoleS] = useState<Role | null>(null);
  const [hydrated, setHydrated] = useState(false);
  useEffect(() => {
    setRoleS(getStoredRole());
    setHydrated(true);
  }, []);
  const setRole = (r: Role | null) => {
    setRoleS(r);
    try {
      if (r) localStorage.setItem(ROLE_KEY, r);
      else localStorage.removeItem(ROLE_KEY);
    } catch {
      // storage blocked: the role lasts for this page only
    }
  };
  return <C.Provider value={{ role, setRole, hydrated }}>{children}</C.Provider>;
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
  const { role, setRole } = useStore();
  const nav = useNavigate();
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
              Signed in as <span className="text-primary">{role}</span>
            </span>
          )}
          <button
            onClick={() => {
              setRole(null);
              nav({ to: "/login" });
            }}
            className="text-muted-foreground hover:text-foreground"
          >
            Switch role
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

/** Shown in place of page content when no role is picked yet. */
export function PickRole() {
  return (
    <Notice>
      Pick a demo role to continue.{" "}
      <Link to="/login" className="text-primary">
        Sign in
      </Link>
    </Notice>
  );
}
