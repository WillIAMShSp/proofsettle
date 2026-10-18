import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { Link, useNavigate } from "@tanstack/react-router";
import {
  isSupabaseConfigured,
  fetchShipments,
  submitSupplierDecision,
  computeSHA256,
  type DbShipmentWithRelations,
} from "./supabase";

export type Role = "Buyer" | "Supplier";
export const STATUSES = [
  "Draft",
  "Agreed",
  "In Transit",
  "Inspection",
  "Proposed",
  "Accepted",
  "Disputed",
  "Resolved",
] as const;
export type Status = (typeof STATUSES)[number];

export type AuditEvent = {
  id?: string | undefined;
  at: string;
  actor: string;
  text: string;
  hash: string;
  tx_hash?: string | undefined;
};

export type Finding = {
  item: string;
  issue: string;
  conf: number;
  confirmed: boolean;
};

export type Shipment = {
  id: string;
  title: string;
  buyer: string;
  supplier: string;
  amount: number;
  status: Status;
  disputeReason?: string | undefined;
  events: AuditEvent[];
  creditRule?: number | undefined;
  findings?: Finding[] | undefined;
  goodsDescription?: string | undefined;
  buyerApproved?: boolean | undefined;
  supplierApproved?: boolean | undefined;
};

// Fast synchronous hash for instant UI fallback
const h = (s: string) => {
  let x = 2166136261;
  for (const c of s) x = Math.imul(x ^ c.charCodeAt(0), 16777619);
  return Array.from({ length: 8 }, (_, i) =>
    (((x >>> 0) * (i + 7)) % 0xffffffff).toString(16).padStart(8, "0")
  ).join("");
};
export const hashOf = h;

const seed: Shipment[] = [
  {
    id: "PS-1042",
    title: "100 metal components",
    buyer: "Northgate Assembly Ltd",
    supplier: "Ferro Precision Works",
    amount: 10000,
    status: "Proposed",
    creditRule: 100,
    goodsDescription: "100 machined metal components",
    buyerApproved: true,
    supplierApproved: true,
    findings: [
      { item: "Component #017", issue: "Bent flange", conf: 0.94, confirmed: true },
      { item: "Component #042", issue: "Surface crack near bore", conf: 0.91, confirmed: true },
      { item: "Component #078", issue: "Deep scratch on mating face", conf: 0.88, confirmed: true },
      { item: "Component #063", issue: "Possible discoloration", conf: 0.52, confirmed: false },
    ],
    events: ([
      ["Oct 09, 10:12", "Buyer", "Agreement drafted: 100 components, $10,000", "9f83c2672ea4e1836932463e264639e4a3b7238484e5699c277258380cf089d7"],
      ["Oct 09, 14:40", "Supplier", "Agreement approved by both parties", "4e07408562bedb8b60ce05c1decfe3ad16b72230967de01f640b7e4729b49fce"],
      ["Oct 11, 08:05", "Supplier", "Dispatch photos uploaded (4)", "4b227777d4dd1fc61c6f884f48641d02b4d121d3fd328cb08b5531fcacdabf8a"],
      ["Oct 11, 09:30", "System", "Shipment marked In Transit", "ef2d127de37b942baad06145e54b0c619a1f22327b2ebbcfbec78f5564afe39d"],
      ["Oct 15, 16:22", "Buyer", "Receipt photos uploaded (4)", "8c6976e5b5410415bde908bd4dee15dfb167a9c873fc4bb8a81f6f2ab448a918"],
      ["Oct 15, 16:31", "AI", "Inspection complete: 3 defects flagged", "a883dafc480d466ee04e0d6da986bd78eb1fdd2178d04693723da3a8f95d42f4"],
      ["Oct 15, 16:32", "System", "Adjustment proposed from agreement rule: $300", "9834876dcfb05cb167a5c24953eba58c4ac89b1adf57f28f2f9d09af107ee9f0"],
    ] as [string, string, string, string][]).map(([at, actor, text, realHash]) => ({
      at,
      actor,
      text,
      hash: realHash,
    })),
  },
  {
    id: "PS-1038",
    title: "40 hydraulic valves",
    buyer: "Northgate Assembly Ltd",
    supplier: "Kestrel Fluid Systems",
    amount: 6400,
    status: "In Transit",
    creditRule: 80,
    goodsDescription: "40 high-pressure hydraulic valves",
    buyerApproved: true,
    supplierApproved: true,
    events: [],
  },
  {
    id: "PS-1031",
    title: "250 steel brackets",
    buyer: "Northgate Assembly Ltd",
    supplier: "Ferro Precision Works",
    amount: 3750,
    status: "Resolved",
    creditRule: 25,
    goodsDescription: "250 structural steel brackets",
    buyerApproved: true,
    supplierApproved: true,
    events: [],
  },
];

type Ctx = {
  role: Role | null;
  setRole: (r: Role | null) => void;
  shipments: Shipment[];
  update: (id: string, f: (s: Shipment) => Shipment) => void;
  recordDecision: (shipmentId: string, decision: "Accepted" | "Disputed", reason?: string) => Promise<void>;
  addAuditEvent: (shipmentId: string, actor: string, text: string) => Promise<string>;
  isSupabaseLive: boolean;
  refreshFromSupabase: () => Promise<void>;
};

const C = createContext<Ctx | null>(null);

function mapDbShipment(db: DbShipmentWithRelations): Shipment {
  const agreement = db.agreements?.[0];
  const auditEvents: AuditEvent[] = (db.audit_events || []).map((e) => ({
    id: e.id,
    at: new Date(e.created_at).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }),
    actor: e.actor || "System",
    text: e.event_text || e.event_type || "Event logged",
    hash: e.payload_hash,
    tx_hash: (e.tx_hash as string | undefined) ?? undefined,
  }));

  const findings: Finding[] = (db.inspections || []).map((i) => ({
    item: i.item_label || "Inspection Item",
    issue: i.issue || "Visual discrepancy",
    conf: Number(i.confidence ?? 0.9),
    confirmed: Boolean(i.confirmed),
  }));

  return {
    id: db.id,
    title: db.title || db.item_description || "100 metal components",
    buyer: db.buyer?.name || "Northgate Assembly Ltd",
    supplier: db.supplier?.name || "Ferro Precision Works",
    amount: Number(db.invoice_amount),
    status: (STATUSES.includes(db.status as Status) ? db.status : "Proposed") as Status,
    disputeReason: db.dispute_reason ?? undefined,
    events: auditEvents,
    creditRule: agreement?.credit_per_defect ? Number(agreement.credit_per_defect) : 100,
    goodsDescription: agreement?.goods_description || "100 machined metal components",
    buyerApproved: agreement?.buyer_approved ?? true,
    supplierApproved: agreement?.supplier_approved ?? true,
    findings: findings.length > 0 ? findings : undefined,
  };
}

export function StoreProvider({ children }: { children: ReactNode }) {
  const [role, setRoleS] = useState<Role | null>(null);
  const [shipments, setShipments] = useState<Shipment[]>(seed);
  const [isSupabaseLive, setIsSupabaseLive] = useState(isSupabaseConfigured);

  const refreshFromSupabase = async () => {
    if (!isSupabaseConfigured) return;
    const dbShipments = await fetchShipments();
    if (dbShipments && dbShipments.length > 0) {
      const mapped = dbShipments.map(mapDbShipment);
      setShipments(mapped);
      setIsSupabaseLive(true);
      localStorage.setItem("ps-shipments", JSON.stringify(mapped));
    }
  };

  useEffect(() => {
    const r = localStorage.getItem("ps-role") as Role | null;
    if (r) setRoleS(r);

    const s = localStorage.getItem("ps-shipments");
    if (s) {
      try {
        setShipments(JSON.parse(s));
      } catch {
        setShipments(seed);
      }
    }

    if (isSupabaseConfigured) {
      refreshFromSupabase();
    }
  }, []);

  const setRole = (r: Role | null) => {
    setRoleS(r);
    if (r) localStorage.setItem("ps-role", r);
    else localStorage.removeItem("ps-role");
  };

  const update = (id: string, f: (s: Shipment) => Shipment) =>
    setShipments((all) => {
      const n = all.map((s) => (s.id === id ? f(s) : s));
      localStorage.setItem("ps-shipments", JSON.stringify(n));
      return n;
    });

  const recordDecision = async (
    shipmentId: string,
    decision: "Accepted" | "Disputed",
    reason?: string
  ) => {
    const actor = role ?? "Supplier";
    const res = await submitSupplierDecision(shipmentId, decision, reason, actor);
    const eventText =
      decision === "Accepted"
        ? `${actor} accepted adjustment`
        : `${actor} disputed adjustment: ${reason?.trim() || "Unspecified reason"}`;

    update(shipmentId, (s) => ({
      ...s,
      status: decision,
      disputeReason: decision === "Disputed" ? reason : undefined,
      events: [
        ...s.events,
        {
          at: "Just now",
          actor,
          text: eventText,
          hash: res.hash,
        },
      ],
    }));
  };

  const addAuditEvent = async (shipmentId: string, actor: string, text: string) => {
    const hash = await computeSHA256(text);
    update(shipmentId, (s) => ({
      ...s,
      events: [
        ...s.events,
        {
          at: "Just now",
          actor,
          text,
          hash,
        },
      ],
    }));
    return hash;
  };

  return (
    <C.Provider
      value={{
        role,
        setRole,
        shipments,
        update,
        recordDecision,
        addAuditEvent,
        isSupabaseLive,
        refreshFromSupabase,
      }}
    >
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
  const { role, setRole, isSupabaseLive } = useStore();
  const nav = useNavigate();
  return (
    <header className="sticky top-0 z-10 border-b bg-background/80 backdrop-blur">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-6">
        <div className="flex items-center gap-4">
          <Logo />
          {isSupabaseLive ? (
            <span className="hidden items-center gap-1.5 rounded-full border border-success/40 bg-success/10 px-2.5 py-0.5 text-[11px] font-medium text-success sm:inline-flex">
              <span className="h-1.5 w-1.5 rounded-full bg-success animate-pulse" />
              Supabase Connected
            </span>
          ) : (
            <span className="hidden items-center gap-1.5 rounded-full border border-muted-foreground/30 px-2.5 py-0.5 text-[11px] font-medium text-muted-foreground sm:inline-flex">
              Demo Seed Mode
            </span>
          )}
        </div>
        <div className="flex items-center gap-4 text-sm">
          <Link to="/dashboard" className="text-muted-foreground hover:text-foreground">
            Shipments
          </Link>
          {role && (
            <span className="rounded-full border px-3 py-1 text-xs">
              Signed in as <span className="text-primary font-medium">{role}</span>
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
