import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { Link, useNavigate } from "@tanstack/react-router";

export type Role = "Buyer" | "Supplier";
export const STATUSES = ["Draft", "Agreed", "In Transit", "Inspection", "Proposed", "Accepted", "Disputed", "Resolved"] as const;
export type Status = (typeof STATUSES)[number];
export type AuditEvent = { at: string; actor: string; text: string; hash: string };
export type Shipment = {
  id: string; title: string; buyer: string; supplier: string; amount: number; status: Status;
  disputeReason?: string; events: AuditEvent[];
};

const h = (s: string) => {
  let x = 2166136261;
  for (const c of s) x = Math.imul(x ^ c.charCodeAt(0), 16777619);
  return Array.from({ length: 8 }, (_, i) => ((x >>> 0) * (i + 7) % 0xffffffff).toString(16).padStart(8, "0")).join("");
};
export const hashOf = h;

const seed: Shipment[] = [
  {
    id: "PS-1042", title: "100 metal components", buyer: "Northgate Assembly Ltd", supplier: "Ferro Precision Works",
    amount: 10000, status: "Proposed",
    events: [
      ["Oct 09, 10:12", "Buyer", "Agreement drafted: 100 components, $10,000"],
      ["Oct 09, 14:40", "Supplier", "Agreement approved by both parties"],
      ["Oct 11, 08:05", "Supplier", "Dispatch photos uploaded (4)"],
      ["Oct 11, 09:30", "System", "Shipment marked In Transit"],
      ["Oct 15, 16:22", "Buyer", "Receipt photos uploaded (4)"],
      ["Oct 15, 16:31", "AI", "Inspection complete: 3 defects flagged"],
      ["Oct 15, 16:32", "System", "Adjustment proposed from agreement rule: $300"],
    ].map(([at, actor, text]) => ({ at, actor, text, hash: h(text) })),
  },
  { id: "PS-1038", title: "40 hydraulic valves", buyer: "Northgate Assembly Ltd", supplier: "Kestrel Fluid Systems", amount: 6400, status: "In Transit", events: [] },
  { id: "PS-1031", title: "250 steel brackets", buyer: "Northgate Assembly Ltd", supplier: "Ferro Precision Works", amount: 3750, status: "Resolved", events: [] },
];

type Ctx = { role: Role | null; setRole: (r: Role | null) => void; shipments: Shipment[]; update: (id: string, f: (s: Shipment) => Shipment) => void };
const C = createContext<Ctx | null>(null);

export function StoreProvider({ children }: { children: ReactNode }) {
  const [role, setRoleS] = useState<Role | null>(null);
  const [shipments, setShipments] = useState<Shipment[]>(seed);
  useEffect(() => {
    const r = localStorage.getItem("ps-role") as Role | null;
    if (r) setRoleS(r);
    const s = localStorage.getItem("ps-shipments");
    if (s) setShipments(JSON.parse(s));
  }, []);
  const setRole = (r: Role | null) => { setRoleS(r); r ? localStorage.setItem("ps-role", r) : localStorage.removeItem("ps-role"); };
  const update = (id: string, f: (s: Shipment) => Shipment) =>
    setShipments((all) => { const n = all.map((s) => (s.id === id ? f(s) : s)); localStorage.setItem("ps-shipments", JSON.stringify(n)); return n; });
  return <C.Provider value={{ role, setRole, shipments, update }}>{children}</C.Provider>;
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
  return <span className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-medium ${statusTone[status]}`}>{status}</span>;
}

export function Logo() {
  return <Link to="/" className="flex items-center gap-2 font-semibold tracking-tight"><span className="h-5 w-5 rounded-md bg-sol" />ProofSettle</Link>;
}

export function TopBar() {
  const { role, setRole } = useStore();
  const nav = useNavigate();
  return (
    <header className="sticky top-0 z-10 border-b bg-background/80 backdrop-blur">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-6">
        <Logo />
        <div className="flex items-center gap-4 text-sm">
          <Link to="/dashboard" className="text-muted-foreground hover:text-foreground">Shipments</Link>
          {role && <span className="rounded-full border px-3 py-1 text-xs">Signed in as <span className="text-primary">{role}</span></span>}
          <button onClick={() => { setRole(null); nav({ to: "/login" }); }} className="text-muted-foreground hover:text-foreground">Switch role</button>
        </div>
      </div>
    </header>
  );
}
