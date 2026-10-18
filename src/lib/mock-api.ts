// In-browser stand-in for the backend, used when VITE_USE_MOCK=true (e.g. the API is down
// during judging). It starts from a snapshot of the backend's seed and follows the same
// workflow rules and settlement formula, keeping its state in localStorage.
//
// Simplifications: hashes are real SHA-256 but not byte-identical to the backend's
// canonical JSON, and "Verify hashes" checks the event links rather than re-hashing files.

import dispatchImg from "@/assets/dispatch.jpg";
import receiptImg from "@/assets/receipt.jpg";
import {
  ApiError,
  getStoredRole,
  type Actions,
  type Actor,
  type Adjustment,
  type AgreementTerms,
  type Api,
  type AuditEvent,
  type Evidence,
  type Finding,
  type FindingOutcome,
  type Role,
  type ShipmentDetail,
  type ShipmentSummary,
  type Status,
} from "./api";
import { usd } from "./format";
import { MOCK_SEED } from "./mock-seed";

/** What the mock stores per shipment: the adjustment's numbers are recomputed on read. */
export type MockShipment = Omit<
  ShipmentDetail,
  "actions" | "inspection" | "adjustment" | "chain" | "recipientEmail"
> & {
  // Optional: the seed and older saved mock data have none. The mock has no accounts, so it
  // shows every shipment to everyone (like the backend's dev login).
  recipientEmail?: string | null;
  findings: Finding[];
  adjustment: Pick<
    Adjustment,
    "id" | "computedAt" | "buyerAcceptedAt" | "supplierAcceptedAt"
  > | null;
};

const STORAGE_KEY = "ps-mock-shipments";
const blobUrls = new Map<string, string>(); // uploaded files, for this browser session only

let cache: MockShipment[] | null = null;

function load(): MockShipment[] {
  if (cache) return cache;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return (cache = JSON.parse(raw) as MockShipment[]);
  } catch {
    // unreadable storage: start from the seed
  }
  return (cache = structuredClone(MOCK_SEED));
}

function save() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(cache));
  } catch {
    // storage full or blocked: keep the in-memory state
  }
}

function find(id: string): MockShipment {
  const s = load().find((x) => x.id === id);
  if (!s) throw new ApiError(404, `Unknown shipment ${id}`);
  return s;
}

function role(): Role {
  const r = getStoredRole();
  if (!r) throw new ApiError(400, "Sign in to continue");
  return r;
}

// --- Settlement engine (same rules and wording as backend/app/settlement.py) ---------------

const pct = (p: number) => `${Number((p * 100).toFixed(4))}%`;

function creditFor(terms: AgreementTerms, confirmed: number): [number, string] {
  const tolerance = terms.acceptance.defectToleranceUnits;
  const { amountPerUnit, maxCredit } = terms.compensation;
  const raw = Math.round(Math.max(0, confirmed - tolerance) * amountPerUnit * 100) / 100;
  let text =
    tolerance === 0
      ? `${confirmed} × ${usd(amountPerUnit)} = ${usd(raw)}`
      : confirmed > tolerance
        ? `(${confirmed} − ${tolerance} tolerated) × ${usd(amountPerUnit)} = ${usd(raw)}`
        : `${confirmed} confirmed, ${tolerance} tolerated = ${usd(raw)}`;
  if (raw > maxCredit) text += `, capped at ${usd(maxCredit)}`;
  return [Math.min(raw, maxCredit), text];
}

function computeAdjustment(terms: AgreementTerms, findings: Finding[]) {
  const { acceptance } = terms;
  const counted: FindingOutcome[] = [];
  const excluded: FindingOutcome[] = [];
  const needsReview: FindingOutcome[] = [];
  const out = (f: Finding, reason: FindingOutcome["reason"], detail: string) => ({
    findingId: f.id,
    unitRef: f.unitRef,
    reason,
    detail,
  });
  for (const f of findings) {
    if (f.reviewOverride === "rejected")
      excluded.push(out(f, "review_rejected", "Rejected by Reviewer"));
    else if (f.reviewOverride === "confirmed")
      counted.push(out(f, "review_confirmed", "Confirmed by Reviewer"));
    else if (!acceptance.defectTypes.includes(f.defectType))
      excluded.push(
        out(f, "defect_type_not_covered", `${f.defectType} is not a covered defect type`),
      );
    else if (f.presentInDispatch)
      excluded.push(out(f, "present_in_dispatch", "Already visible in dispatch photos"));
    else if (f.confidence < acceptance.minConfidence)
      needsReview.push(
        out(
          f,
          "below_confidence",
          `${pct(f.confidence)} confidence is below the ${pct(acceptance.minConfidence)} threshold`,
        ),
      );
    else
      counted.push(
        out(
          f,
          "meets_threshold",
          `${pct(f.confidence)} confidence, at or above ${pct(acceptance.minConfidence)}`,
        ),
      );
  }
  const units = new Set(counted.map((o) => o.unitRef));
  const [credit, creditRule] = creditFor(terms, units.size);
  const [ifConfirmed] = creditFor(
    terms,
    new Set([...units, ...needsReview.map((o) => o.unitRef)]).size,
  );
  const settlement = Math.round((terms.invoiceAmount - credit) * 100) / 100;
  const tol = acceptance.defectToleranceUnits;
  return {
    confirmedDefects: units.size,
    credit,
    settlementAmount: settlement,
    appliedRule: {
      credit: creditRule,
      settlement: `${usd(terms.invoiceAmount)} − ${usd(credit)} = ${usd(settlement)}`,
    },
    counted,
    excluded,
    needsReview,
    amountIfReviewedConfirmed: ifConfirmed,
    assumptions: [
      `Only findings at ≥ ${pct(acceptance.minConfidence)} confidence count as confirmed, unless a Reviewer decides`,
      `Covered defect types: ${acceptance.defectTypes.join(", ")}`,
      "Defects already visible in dispatch photos are excluded",
      tol
        ? `First ${tol} defective unit${tol !== 1 ? "s" : ""} accepted without credit`
        : "No defect tolerance: every confirmed defective unit is credited",
      `Credit rule taken unchanged from the signed agreement: ${usd(terms.compensation.amountPerUnit)} per defective unit, capped at ${usd(terms.compensation.maxCredit)}`,
    ],
    status: needsReview.length ? ("needs_review" as const) : ("ready" as const),
  };
}

// --- Reads ---------------------------------------------------------------------------------

function liveAdjustment(s: MockShipment): Adjustment | null {
  if (!s.adjustment || !s.agreement) return null;
  return { ...s.adjustment, ...computeAdjustment(s.agreement.terms, s.findings) };
}

function actionsFor(s: MockShipment, r: Role | null, adj: Adjustment | null): Actions {
  const proposed = s.status === "Proposed" && adj !== null;
  const notYet =
    (r === "Buyer" && !adj?.buyerAcceptedAt) || (r === "Supplier" && !adj?.supplierAcceptedAt);
  const canReview = r === "Reviewer" && s.status === "Disputed";
  return {
    canAccept: proposed && notYet,
    canDispute: proposed && notYet,
    canReview,
    canResolve: canReview && adj !== null && adj.needsReview.length === 0,
  };
}

function detail(s: MockShipment): ShipmentDetail {
  const { findings, adjustment: _stored, ...rest } = s;
  const adjustment = liveAdjustment(s);
  return structuredClone({
    ...rest,
    recipientEmail: s.recipientEmail ?? null,
    inspection: findings.length ? { findings } : null,
    adjustment,
    actions: actionsFor(s, getStoredRole(), adjustment),
    chain: null, // the mock has no blockchain
  });
}

const summary = ({
  id,
  title,
  buyer,
  supplier,
  amount,
  status,
  recipientEmail,
}: MockShipment): ShipmentSummary => ({
  id,
  title,
  buyer,
  supplier,
  amount,
  status,
  recipientEmail: recipientEmail ?? null,
});

// --- Writes --------------------------------------------------------------------------------

async function sha256(data: string | ArrayBuffer): Promise<string> {
  const bytes = typeof data === "string" ? new TextEncoder().encode(data) : data;
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}

const now = () => new Date().toISOString().replace(/\.\d+Z$/, "Z");

function nextId(prefix: string, used: string[]): string {
  const max = Math.max(0, ...used.map((x) => Number(x.split("_")[1]) || 0));
  return `${prefix}_${String(max + 1).padStart(2, "0")}`;
}

async function log(
  s: MockShipment,
  actor: Actor,
  type: string,
  text: string,
  payload: object = {},
) {
  const prev = s.events.at(-1);
  const at = now();
  const payloadHash = await sha256(JSON.stringify(payload));
  const event: Omit<AuditEvent, "hash"> = {
    id: nextId(
      "evt",
      load().flatMap((x) => x.events.map((e) => e.id)),
    ),
    seq: (prev?.seq ?? 0) + 1,
    at,
    actor,
    type,
    text,
    payloadHash,
    prevHash: prev?.hash ?? null,
    txHash: null,
    chainStatus: "skipped",
  };
  s.events.push({ ...event, hash: await sha256(JSON.stringify(event)) });
}

function move(s: MockShipment, from: Status, to: Status) {
  if (s.status !== from) throw new ApiError(409, `Cannot move from ${s.status} to ${to}`);
  s.status = to;
}

function party(r: Role, what: string): "Buyer" | "Supplier" {
  if (r === "Reviewer") throw new ApiError(403, `Reviewer cannot ${what}`);
  return r;
}

async function write(
  id: string,
  f: (s: MockShipment, r: Role) => Promise<void>,
): Promise<ShipmentDetail> {
  const r = role();
  const s = find(id);
  const before = structuredClone(s);
  try {
    await f(s, r);
  } catch (e) {
    Object.assign(s, before); // a refused write leaves no trace
    throw e;
  }
  save();
  return detail(s);
}

// Pinned to the receipt photos by position, like the backend's MockProvider fixture.
const MOCK_FINDINGS = [
  ["Component #017", "bend", 0.94, "Bent flange"],
  ["Component #042", "crack", 0.91, "Surface crack near bore"],
  ["Component #078", "deep_scratch", 0.88, "Deep scratch on mating face"],
  ["Component #063", "discoloration", 0.52, "Possible discoloration"],
] as const;

export const mockApi: Api = {
  health: async () => ({ status: "ok", db: "ok" }),
  listShipments: async () => {
    role();
    return load().map(summary);
  },
  getShipment: async (id) => {
    role();
    return detail(find(id));
  },
  getAudit: async (id) => {
    role();
    const v = await mockApi.verifyAudit(id);
    return {
      shipmentId: id,
      verified: v.verified,
      checked: v.events.length,
      events: find(id).events,
      checks: v.events,
    };
  },
  evidenceFileUrl: (ev) =>
    blobUrls.get(ev.id) ?? (ev.kind === "dispatch" ? dispatchImg : receiptImg),

  createShipment: async ({ title, supplier, terms, recipientEmail }) => {
    if (role() !== "Buyer") throw new ApiError(403, `${role()} cannot create a shipment`);
    const all = load();
    const id = `PS-${Math.max(1000, ...all.map((x) => Number(x.id.slice(3)))) + 1}`;
    const s: MockShipment = {
      id,
      title,
      buyer: "Northgate Assembly Ltd",
      supplier,
      recipientEmail: recipientEmail?.trim().toLowerCase() || null,
      amount: terms.invoiceAmount,
      status: "Draft",
      disputeReason: null,
      agreement: {
        terms,
        buyerApproved: false,
        supplierApproved: false,
        termsHash: await sha256(JSON.stringify(terms)),
      },
      evidence: [],
      findings: [],
      adjustment: null,
      events: [],
    };
    all.unshift(s);
    await log(
      s,
      "Buyer",
      "agreement.drafted",
      `Agreement drafted: ${terms.quantity} × ${terms.itemDescription}, ${usd(terms.invoiceAmount)}`,
    );
    save();
    return detail(s);
  },

  approveAgreement: (id) =>
    write(id, async (s, r) => {
      const p = party(r, "approve an agreement");
      if (s.status !== "Draft" || !s.agreement)
        throw new ApiError(409, `The agreement can only be approved while Draft, not ${s.status}`);
      if (p === "Buyer") s.agreement.buyerApproved = true;
      else s.agreement.supplierApproved = true;
      const both = s.agreement.buyerApproved && s.agreement.supplierApproved;
      await log(
        s,
        p,
        "agreement.approved",
        both ? "Agreement approved by both parties" : `Agreement approved by ${p}`,
      );
      if (both) move(s, "Draft", "Agreed");
    }),

  uploadEvidence: (id, files) =>
    write(id, async (s, r) => {
      const kind =
        s.status === "Agreed" ? "dispatch" : s.status === "In Transit" ? "receipt" : null;
      if (!kind) throw new ApiError(409, `Evidence can't be uploaded while ${s.status}`);
      const uploader = kind === "dispatch" ? "Supplier" : "Buyer";
      if (r !== uploader) throw new ApiError(403, `${r} cannot upload ${kind} evidence`);
      for (const f of files) {
        if (!/^image\/(jpeg|png)$/.test(f.type))
          throw new ApiError(415, `${f.name} is not a JPEG or PNG image`);
        const evId = nextId(
          "ev",
          load().flatMap((x) => x.evidence.map((e) => e.id)),
        );
        const ev: Evidence = {
          id: evId,
          kind,
          url: `/evidence/${evId}/file`,
          sha256: await sha256(await f.arrayBuffer()),
          uploadedBy: r,
          at: now(),
          verified: null,
        };
        s.evidence.push(ev);
        blobUrls.set(evId, URL.createObjectURL(f));
      }
      const req = s.agreement?.terms.evidenceRequirements;
      const have = s.evidence.filter((e) => e.kind === kind).length;
      const min = kind === "dispatch" ? req?.minDispatchPhotos : req?.minReceiptPhotos;
      const target: Status | null =
        have >= (min ?? 1) ? (kind === "dispatch" ? "In Transit" : "Inspection") : null;
      const label = kind === "dispatch" ? "Dispatch" : "Receipt";
      await log(
        s,
        r,
        "evidence.uploaded",
        `${label} photos uploaded (${files.length})${target ? `; shipment moved to ${target}` : ""}`,
      );
      if (target) s.status = target;
    }),

  inspect: (id) =>
    write(id, async (s, r) => {
      party(r, "run an inspection");
      if (s.status !== "Inspection")
        throw new ApiError(409, `Inspection can only run while Inspection, not ${s.status}`);
      const receipts = s.evidence.filter((e) => e.kind === "receipt");
      const used = load().flatMap((x) => x.findings.map((f) => f.id));
      s.findings = MOCK_FINDINGS.map(([unitRef, defectType, confidence, description], i) => {
        const fId = nextId("fnd", used);
        used.push(fId);
        return {
          id: fId,
          unitRef,
          defectType,
          confidence,
          description,
          evidenceIds: [receipts[i % receipts.length]?.id ?? "ev_00"],
          presentInDispatch: false,
          reviewOverride: null,
          reviewedBy: null,
          reviewedAt: null,
        };
      });
      const n = s.findings.length;
      await log(
        s,
        "AI",
        "inspection.completed",
        `Inspection complete: ${n} finding${n !== 1 ? "s" : ""} flagged`,
      );
      s.adjustment = {
        id: nextId(
          "adj",
          load().flatMap((x) => (x.adjustment ? [x.adjustment.id] : [])),
        ),
        computedAt: now(),
        buyerAcceptedAt: null,
        supplierAcceptedAt: null,
      };
      move(s, "Inspection", "Proposed");
      await log(
        s,
        "System",
        "adjustment.proposed",
        `Adjustment proposed from agreement rule: ${usd(liveAdjustment(s)?.credit ?? 0)}`,
      );
    }),

  accept: (id) =>
    write(id, async (s, r) => {
      const p = party(r, "accept an adjustment");
      const adj = liveAdjustment(s);
      if (s.status !== "Proposed" || !adj || !s.adjustment)
        throw new ApiError(409, `Only a Proposed adjustment can be accepted, not ${s.status}`);
      const key = p === "Buyer" ? "buyerAcceptedAt" : "supplierAcceptedAt";
      if (s.adjustment[key]) return; // accepting twice is a no-op
      s.adjustment[key] = now();
      await log(s, p, "adjustment.accepted", `${p} accepted ${usd(adj.credit)} adjustment`);
      if (s.adjustment.buyerAcceptedAt && s.adjustment.supplierAcceptedAt)
        move(s, "Proposed", "Accepted");
    }),

  dispute: (id, reason) =>
    write(id, async (s, r) => {
      const p = party(r, "dispute an adjustment");
      const text = reason.trim();
      if (!text) throw new ApiError(400, "A dispute needs a reason");
      if (!actionsFor(s, p, liveAdjustment(s)).canDispute)
        throw new ApiError(
          409,
          s.status === "Proposed"
            ? `${p} has already accepted`
            : `Cannot dispute while ${s.status}`,
        );
      move(s, "Proposed", "Disputed");
      s.disputeReason = text;
      await log(s, p, "adjustment.disputed", `Adjustment disputed: ${text}`);
    }),

  reviewFinding: async (findingId, decision) => {
    const s = load().find((x) => x.findings.some((f) => f.id === findingId));
    if (!s) throw new ApiError(404, `Unknown finding ${findingId}`);
    return write(s.id, async (sh, r) => {
      if (r !== "Reviewer") throw new ApiError(403, `${r} cannot review findings`);
      if (sh.status !== "Disputed")
        throw new ApiError(409, `Findings can only be reviewed while Disputed, not ${sh.status}`);
      const f = sh.findings.find((x) => x.id === findingId);
      if (!f) return;
      Object.assign(f, { reviewOverride: decision, reviewedBy: "Reviewer", reviewedAt: now() });
      await log(sh, "Reviewer", "finding.reviewed", `Reviewer ${decision} ${f.id} (${f.unitRef})`);
    });
  },

  resolve: (id) =>
    write(id, async (s, r) => {
      if (r !== "Reviewer") throw new ApiError(403, `${r} cannot resolve a dispute`);
      const adj = liveAdjustment(s);
      if (adj?.needsReview.length)
        throw new ApiError(409, "Every needs-review finding must be confirmed or rejected first");
      move(s, "Disputed", "Resolved");
      await log(
        s,
        "Reviewer",
        "dispute.resolved",
        `Dispute resolved: ${usd(adj?.credit ?? 0)} credit`,
      );
    }),

  anchor: async () => {
    throw new ApiError(409, "Solana anchoring is not configured");
  },

  verifyAudit: async (id) => {
    role();
    const s = find(id);
    const events = s.events.map((e, i) => {
      const linkOk = e.seq === i + 1 && e.prevHash === (s.events[i - 1]?.hash ?? null);
      return {
        id: e.id,
        seq: e.seq,
        storedHash: e.hash,
        recomputedHash: e.hash,
        payloadOk: true,
        linkOk,
        ok: linkOk,
      };
    });
    const evidence = s.evidence.map((e) => ({
      id: e.id,
      storedHash: e.sha256,
      recomputedHash: e.sha256,
      ok: true,
    }));
    for (const e of s.evidence) e.verified = true;
    save();
    const agreement = s.agreement
      ? {
          id: "agr",
          storedHash: s.agreement.termsHash,
          recomputedHash: s.agreement.termsHash,
          ok: true,
        }
      : null;
    return {
      shipmentId: id,
      verified: events.every((e) => e.ok),
      checked: events.length + evidence.length + 1,
      agreement,
      events,
      evidence,
      chain: { available: false, anchored: 0, mismatches: [] },
      verifiedAt: now(),
    };
  },

  devReset: async () => {
    cache = structuredClone(MOCK_SEED);
    save();
    return { shipments: cache.map((s) => s.id) };
  },
};
