// Typed client for the FastAPI backend. Types mirror backend/API_CONTRACT.md exactly.

import { isSupabaseConfigured, supabase } from "./supabase";

export type Role = "Buyer" | "Supplier" | "Reviewer";
export type Actor = Role | "System" | "AI";
export const ROLES: readonly Role[] = ["Buyer", "Supplier", "Reviewer"];

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

/** Dollars, at most 2 decimal places. */
export type Money = number;
/** ISO 8601 UTC, e.g. "2026-10-09T10:12:00Z". */
export type IsoDateTime = string;
/** Lowercase hex SHA-256, 64 characters. */
export type Sha256 = string;

// --- Agreement terms -------------------------------------------------------------------

export type AgreementTerms = {
  itemDescription: string;
  quantity: number;
  unitPrice: Money;
  invoiceAmount: Money;
  evidenceRequirements: {
    minDispatchPhotos: number;
    minReceiptPhotos: number;
    inspectionWindowHours: number;
  };
  acceptance: {
    defectTypes: string[];
    minConfidence: number;
    defectToleranceUnits: number;
  };
  compensation: {
    type: "per_defective_unit";
    amountPerUnit: Money;
    maxCredit: Money;
  };
};

export type Agreement = {
  terms: AgreementTerms;
  buyerApproved: boolean;
  supplierApproved: boolean;
  termsHash: Sha256;
};

// --- Evidence, findings, adjustment -----------------------------------------------------

export type EvidenceKind = "dispatch" | "receipt";

export type Evidence = {
  id: string;
  kind: EvidenceKind;
  /** Relative to the API base URL, e.g. "/evidence/ev_01/file". */
  url: string;
  sha256: Sha256;
  uploadedBy: Actor;
  at: IsoDateTime;
  /** Result of the last verify run; null = never checked. */
  verified: boolean | null;
};

export type ReviewOverride = "confirmed" | "rejected";

export type Finding = {
  id: string;
  unitRef: string;
  defectType: string;
  confidence: number;
  evidenceIds: string[];
  description: string;
  presentInDispatch: boolean;
  reviewOverride: ReviewOverride | null;
  reviewedBy: Actor | null;
  reviewedAt: IsoDateTime | null;
};

export type OutcomeReason =
  | "review_confirmed"
  | "meets_threshold"
  | "review_rejected"
  | "defect_type_not_covered"
  | "present_in_dispatch"
  | "below_confidence";

export type FindingOutcome = {
  findingId: string;
  unitRef: string;
  reason: OutcomeReason;
  detail: string;
};

export type Adjustment = {
  id: string;
  computedAt: IsoDateTime;
  confirmedDefects: number;
  credit: Money;
  settlementAmount: Money;
  appliedRule: { credit: string; settlement: string };
  counted: FindingOutcome[];
  excluded: FindingOutcome[];
  needsReview: FindingOutcome[];
  amountIfReviewedConfirmed: Money;
  assumptions: string[];
  status: "ready" | "needs_review";
  buyerAcceptedAt: IsoDateTime | null;
  supplierAcceptedAt: IsoDateTime | null;
};

export type Actions = {
  canAccept: boolean;
  canDispute: boolean;
  canReview: boolean;
  canResolve: boolean;
};

export type ChainStatus = "pending" | "confirmed" | "failed" | "skipped";

export type AuditEvent = {
  id: string;
  seq: number;
  at: IsoDateTime;
  actor: Actor;
  type: string;
  text: string;
  hash: Sha256;
  payloadHash: Sha256;
  prevHash: Sha256 | null;
  txHash: string | null;
  chainStatus: ChainStatus;
};

// --- Responses ---------------------------------------------------------------------------

export type Health = { status: "ok"; db: "ok" | "unavailable" };

export type ShipmentSummary = {
  id: string;
  title: string;
  buyer: string;
  supplier: string;
  amount: Money;
  status: Status;
};

/** Where the shipment's record lives on Solana. Null when the backend has no chain configured. */
export type ChainInfo = {
  programId: string;
  /** The shipment's program account (PDA). */
  address: string;
  /** Solana Explorer `cluster` query value, e.g. "devnet". */
  explorerCluster: string;
};

export type ShipmentDetail = ShipmentSummary & {
  disputeReason: string | null;
  agreement: Agreement | null;
  evidence: Evidence[];
  inspection: { findings: Finding[] } | null;
  adjustment: Adjustment | null;
  actions: Actions;
  events: AuditEvent[];
  chain: ChainInfo | null;
};

export type EventCheck = {
  id: string;
  seq: number;
  storedHash: Sha256;
  recomputedHash: Sha256;
  payloadOk: boolean;
  linkOk: boolean;
  ok: boolean;
};

export type AuditTrail = {
  shipmentId: string;
  verified: boolean;
  checked: number;
  events: AuditEvent[];
  checks: EventCheck[];
};

export type HashCheck = {
  id: string;
  storedHash: Sha256;
  /** null when the evidence file is missing. */
  recomputedHash: Sha256 | null;
  ok: boolean;
};

export type Verification = {
  shipmentId: string;
  verified: boolean;
  checked: number;
  agreement: HashCheck | null;
  events: EventCheck[];
  evidence: HashCheck[];
  chain: { available: boolean; anchored: number; mismatches: string[] };
  verifiedAt: IsoDateTime;
};

export type ResetResult = { shipments: string[] };

export type NewShipment = { title: string; supplier: string; terms: AgreementTerms };

/** Every endpoint in API_CONTRACT.md. The HTTP client and the mock both implement it. */
export interface Api {
  health(): Promise<Health>;
  listShipments(): Promise<ShipmentSummary[]>;
  getShipment(id: string): Promise<ShipmentDetail>;
  getAudit(id: string): Promise<AuditTrail>;
  /** URL for an <img src>; the file route needs no role header. */
  evidenceFileUrl(evidence: Evidence): string;
  createShipment(body: NewShipment): Promise<ShipmentDetail>;
  approveAgreement(id: string): Promise<ShipmentDetail>;
  uploadEvidence(id: string, files: File[]): Promise<ShipmentDetail>;
  inspect(id: string): Promise<ShipmentDetail>;
  accept(id: string): Promise<ShipmentDetail>;
  dispute(id: string, reason: string): Promise<ShipmentDetail>;
  reviewFinding(findingId: string, decision: ReviewOverride): Promise<ShipmentDetail>;
  resolve(id: string): Promise<ShipmentDetail>;
  /** Send whatever of the history isn't on Solana yet (retries failed anchoring). */
  anchor(id: string): Promise<ShipmentDetail>;
  verifyAudit(id: string): Promise<Verification>;
  devReset(): Promise<ResetResult>;
}

// --- Errors and role ---------------------------------------------------------------------

/** A failed request. `detail` is the API's {"detail": ...} message, ready to show. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
  ) {
    super(detail);
    this.name = "ApiError";
  }
}

export const ROLE_KEY = "ps-role";

/** Offline demo (`VITE_USE_MOCK=true`) keeps the role in localStorage. The HTTP API does not. */
export const USE_MOCK = import.meta.env.VITE_USE_MOCK === "true";

/** Local dev login (`VITE_DEV_AUTH=true`): pick a role and send it to the real API as
 * `X-Dev-Role`. The backend accepts it only when run with PROOFSETTLE_DEV_AUTH=true. */
export const DEV_AUTH = !USE_MOCK && import.meta.env.VITE_DEV_AUTH === "true";

export const isRole = (value: unknown): value is Role => ROLES.includes(value as Role);

/** Mock-mode or dev-login role. Null on the server. */
export function getStoredRole(): Role | null {
  if (typeof window === "undefined") return null;
  try {
    const role = localStorage.getItem(ROLE_KEY);
    return isRole(role) ? role : null;
  } catch {
    return null;
  }
}

// --- HTTP client -------------------------------------------------------------------------

export const API_URL = (import.meta.env.VITE_API_URL || "http://127.0.0.1:8000").replace(
  /\/+$/,
  "",
);

type Body = { json: unknown } | { form: FormData };

// FastAPI's detail is a string, or for 422 a list of {loc, msg} validation errors.
function detailText(body: unknown, fallback: string): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const msgs = detail.map((d: { msg?: unknown }) => d.msg).filter((m) => typeof m === "string");
    if (msgs.length) return msgs.join("; ");
  }
  return fallback;
}

async function authHeaders(): Promise<Record<string, string>> {
  if (isSupabaseConfigured) {
    const { data } = await supabase.auth.getSession();
    const token = data.session?.access_token;
    if (token) return { Authorization: `Bearer ${token}` };
  }
  const devRole = DEV_AUTH ? getStoredRole() : null;
  return devRole ? { "X-Dev-Role": devRole } : {};
}

async function request<T>(method: "GET" | "POST", path: string, body?: Body): Promise<T> {
  const headers: Record<string, string> = await authHeaders();
  let payload: BodyInit | undefined;
  if (body && "json" in body) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body.json);
  } else if (body) {
    payload = body.form; // the browser sets the multipart boundary
  }

  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, { method, headers, body: payload ?? null });
  } catch {
    throw new ApiError(0, `Can't reach the API at ${API_URL}. Is the backend running?`);
  }
  const data: unknown = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, detailText(data, `${res.status} ${res.statusText}`));
  return data as T;
}

const enc = encodeURIComponent;

export const httpApi: Api = {
  health: () => request("GET", "/health"),
  listShipments: () => request("GET", "/shipments"),
  getShipment: (id) => request("GET", `/shipments/${enc(id)}`),
  getAudit: (id) => request("GET", `/shipments/${enc(id)}/audit`),
  evidenceFileUrl: (evidence) => `${API_URL}${evidence.url}`,
  createShipment: (body) => request("POST", "/shipments", { json: body }),
  approveAgreement: (id) => request("POST", `/shipments/${enc(id)}/agreement/approve`),
  uploadEvidence: (id, files) => {
    const form = new FormData();
    for (const f of files) form.append("files", f);
    return request("POST", `/shipments/${enc(id)}/evidence`, { form });
  },
  inspect: (id) => request("POST", `/shipments/${enc(id)}/inspect`),
  accept: (id) => request("POST", `/shipments/${enc(id)}/accept`),
  dispute: (id, reason) => request("POST", `/shipments/${enc(id)}/dispute`, { json: { reason } }),
  reviewFinding: (findingId, decision) =>
    request("POST", `/findings/${enc(findingId)}/review`, { json: { decision } }),
  resolve: (id) => request("POST", `/shipments/${enc(id)}/resolve`),
  anchor: (id) => request("POST", `/shipments/${enc(id)}/chain/anchor`),
  verifyAudit: (id) => request("POST", `/shipments/${enc(id)}/audit/verify`),
  devReset: () => request("POST", "/dev/reset"),
};
