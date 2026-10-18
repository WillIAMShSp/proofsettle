import { createFileRoute, Link } from "@tanstack/react-router";
import { useState, type ReactNode } from "react";
import { Check, AlertTriangle, ShieldCheck, Scale } from "lucide-react";
import { Chip, ErrorNote, Notice, PickRole, TopBar, useStore } from "@/lib/store";
import {
  ApiError,
  type EvidenceKind,
  type Finding,
  type FindingOutcome,
  type ShipmentDetail,
  type Status,
} from "@/lib/api";
import { api, useShipment, useShipmentWrite, useVerifyAudit } from "@/lib/queries";
import { formatAt, short, unitShort, usd } from "@/lib/format";

export const Route = createFileRoute("/shipments/$id")({
  head: ({ params }) => ({
    meta: [
      { title: `Shipment ${params.id} — ProofSettle` },
      {
        name: "description",
        content: "Agreement, evidence, AI inspection, and settlement for this shipment.",
      },
      { property: "og:title", content: `Shipment ${params.id} — ProofSettle` },
      { property: "og:description", content: "Evidence-backed settlement details." },
    ],
  }),
  component: Detail,
});

const STEPS: Status[] = ["Draft", "Agreed", "In Transit", "Inspection", "Proposed", "Accepted"];
const PARTIES = ["Buyer", "Supplier"] as const;

function Section({
  title,
  children,
  aside,
}: {
  title: string;
  children: ReactNode;
  aside?: ReactNode;
}) {
  return (
    <section className="card-surface p-8 fade-up">
      <div className="mb-6 flex items-center justify-between">
        <h2 className="text-xl font-semibold">{title}</h2>
        {aside}
      </div>
      {children}
    </section>
  );
}

function Page({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen">
      <TopBar />
      <main className="mx-auto max-w-5xl space-y-6 px-6 py-16">{children}</main>
    </div>
  );
}

function Detail() {
  const { id } = Route.useParams();
  const { role, hydrated } = useStore();
  const q = useShipment(id);

  if (hydrated && !role)
    return (
      <Page>
        <PickRole />
      </Page>
    );
  if (q.error instanceof ApiError && q.error.status === 404)
    return (
      <div className="min-h-screen">
        <TopBar />
        <p className="p-16 text-center text-muted-foreground">
          Shipment not found.{" "}
          <Link to="/dashboard" className="text-primary">
            Back
          </Link>
        </p>
      </div>
    );
  if (q.isError)
    return (
      <Page>
        <Notice tone="error">
          {q.error.message}{" "}
          <button onClick={() => q.refetch()} className="ml-2 text-primary">
            Retry
          </button>
        </Notice>
      </Page>
    );
  if (!q.data)
    return (
      <Page>
        <Notice>Loading shipment…</Notice>
      </Page>
    );
  // key: a different shipment starts with fresh local state (dispute form, verify result).
  return <ShipmentView key={id} s={q.data} />;
}

function ShipmentView({ s }: { s: ShipmentDetail }) {
  const stepIdx = s.status === "Disputed" || s.status === "Resolved" ? 5 : STEPS.indexOf(s.status);
  return (
    <Page>
      <div className="fade-up">
        <span className="font-mono text-xs text-muted-foreground">{s.id}</span>
        <div className="mt-1 flex flex-wrap items-center justify-between gap-4">
          <h1 className="text-4xl font-semibold tracking-tight">
            {s.title}, ${s.amount.toLocaleString()}
          </h1>
          <Chip status={s.status} />
        </div>
        <p className="mt-2 text-muted-foreground">
          {s.supplier} → {s.buyer}
        </p>
      </div>

      <div className="flex gap-2 fade-up">
        {STEPS.map((st, i) => {
          const label =
            i === 5 && (s.status === "Disputed" || s.status === "Resolved") ? s.status : st;
          const bad = label === "Disputed";
          return (
            <div key={st} className="flex-1">
              <div
                className={`h-1 rounded-full ${i <= stepIdx ? (bad && i === 5 ? "bg-destructive" : "bg-sol") : "bg-muted"}`}
              />
              <p
                className={`mt-2 text-xs ${i === stepIdx ? "text-foreground" : "text-muted-foreground"}`}
              >
                {label}
              </p>
            </div>
          );
        })}
      </div>

      <div className="flex items-center gap-3 rounded-2xl border border-primary/30 px-5 py-4 text-sm fade-up">
        <Scale className="h-4 w-4 shrink-0 text-primary" />
        <span>
          AI never decides the payment amount. The amount always comes from the agreement rules.
        </span>
      </div>

      <AgreementSection s={s} />
      <EvidenceSection s={s} />
      <InspectionSection s={s} />
      <AdjustmentSection s={s} />
      <DecisionSection s={s} />
      <AuditSection s={s} />
    </Page>
  );
}

// --- Shared bits ------------------------------------------------------------------------

/** A party's state as a pill: green with a check when done, muted while pending. */
function PartyBadge({ done, children }: { done: boolean; children: ReactNode }) {
  return done ? (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-success/40 px-3 py-1 text-xs text-success">
      <Check className="h-3 w-3" />
      {children}
    </span>
  ) : (
    <span className="inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs text-muted-foreground">
      {children}
    </span>
  );
}

const primaryBtn =
  "rounded-full bg-sol px-8 py-2.5 font-medium text-background hover:opacity-90 disabled:opacity-40";
const smallBtn =
  "rounded-full border px-4 py-2 text-sm hover:border-primary/60 disabled:opacity-40";

const plural = (word: string, n: number) => (n === 1 || word.endsWith("s") ? word : `${word}s`);

// --- Agreement --------------------------------------------------------------------------

function AgreementSection({ s }: { s: ShipmentDetail }) {
  const { role } = useStore();
  const write = useShipmentWrite();
  const a = s.agreement;
  const t = a?.terms;
  const approved = { Buyer: a?.buyerApproved ?? false, Supplier: a?.supplierApproved ?? false };
  const canApprove =
    s.status === "Draft" && (role === "Buyer" || role === "Supplier") && !approved[role];
  const tolerance = t?.acceptance.defectToleranceUnits ?? 0;
  return (
    <Section title="Agreement">
      <dl className="grid gap-6 text-sm md:grid-cols-3">
        <div>
          <dt className="text-muted-foreground">Goods</dt>
          <dd className="mt-1 text-base">
            {t ? `${t.quantity} ${plural(t.itemDescription.toLowerCase(), t.quantity)}` : "—"}
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Contract value</dt>
          <dd className="mt-1 text-base">${s.amount.toLocaleString()}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Credit rule</dt>
          <dd className="mt-1 text-base">
            {t ? (
              <>
                {usd(t.compensation.amountPerUnit)} per confirmed defective unit
                {tolerance > 0 && `, first ${tolerance} tolerated`}
                {t.compensation.maxCredit < t.invoiceAmount &&
                  `, capped at ${usd(t.compensation.maxCredit)}`}
              </>
            ) : (
              "—"
            )}
          </dd>
        </div>
      </dl>
      <div className="mt-6 flex flex-wrap items-center gap-3">
        {PARTIES.map((p) => (
          <PartyBadge key={p} done={approved[p]}>
            {p} {approved[p] ? "approved" : "approval pending"}
          </PartyBadge>
        ))}
        {canApprove && (
          <button
            disabled={write.isPending}
            onClick={() => write.mutate(() => api.approveAgreement(s.id))}
            className={smallBtn}
          >
            {write.isPending ? "Approving…" : "Approve terms"}
          </button>
        )}
      </div>
      <ErrorNote error={write.error} />
    </Section>
  );
}

// --- Evidence ---------------------------------------------------------------------------

const KINDS: [EvidenceKind, string][] = [
  ["dispatch", "Dispatch"],
  ["receipt", "Receipt"],
];

function EvidenceSection({ s }: { s: ShipmentDetail }) {
  const { role } = useStore();
  const write = useShipmentWrite();
  const req = s.agreement?.terms.evidenceRequirements;
  const uploadKind: EvidenceKind | null =
    s.status === "Agreed" && role === "Supplier"
      ? "dispatch"
      : s.status === "In Transit" && role === "Buyer"
        ? "receipt"
        : null;

  return (
    <Section title="Evidence">
      {KINDS.map(([kind, label]) => {
        const items = s.evidence.filter((e) => e.kind === kind);
        const min = kind === "dispatch" ? req?.minDispatchPhotos : req?.minReceiptPhotos;
        return (
          <div key={kind} className="mb-8 last:mb-0">
            <div className="mb-3 flex items-center justify-between gap-4">
              <h3 className="text-sm text-muted-foreground">
                {label} photos
                {min !== undefined && items.length < min && ` (${items.length} of ${min} required)`}
              </h3>
              {uploadKind === kind && (
                <label
                  className={`${smallBtn} cursor-pointer ${write.isPending ? "pointer-events-none opacity-40" : ""}`}
                >
                  {write.isPending ? "Uploading…" : `Upload ${kind} photos`}
                  <input
                    type="file"
                    accept="image/jpeg,image/png"
                    multiple
                    className="hidden"
                    onChange={(e) => {
                      const files = Array.from(e.target.files ?? []);
                      e.target.value = ""; // so picking the same files again still fires
                      if (files.length) write.mutate(() => api.uploadEvidence(s.id, files));
                    }}
                  />
                </label>
              )}
            </div>
            {items.length ? (
              <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
                {items.map((ev, n) => (
                  <figure key={ev.id}>
                    <img
                      src={api.evidenceFileUrl(ev)}
                      alt={`${label} photo ${n + 1}`}
                      loading="lazy"
                      className="aspect-square w-full rounded-xl object-cover"
                      style={{ objectPosition: `${(n % 4) * 33}% ${(n % 4) * 25}%` }}
                    />
                    <figcaption className="mt-2 flex items-center justify-between text-xs">
                      <span className="font-mono text-muted-foreground" title={ev.sha256}>
                        {short(ev.sha256)}
                      </span>
                      {ev.verified === true ? (
                        <span className="flex items-center gap-1 text-success">
                          <Check className="h-3 w-3" />
                          Verified
                        </span>
                      ) : ev.verified === false ? (
                        <span className="flex items-center gap-1 text-destructive">
                          <AlertTriangle className="h-3 w-3" />
                          Changed
                        </span>
                      ) : (
                        <span className="text-muted-foreground">Not checked</span>
                      )}
                    </figcaption>
                  </figure>
                ))}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">No {kind} photos yet.</p>
            )}
          </div>
        );
      })}
      <ErrorNote error={write.error} />
    </Section>
  );
}

// --- AI inspection ----------------------------------------------------------------------

type Outcome = "counted" | "needsReview" | "excluded";

/** Which of the engine's three lists each finding is in. */
function outcomes(s: ShipmentDetail): Map<string, { kind: Outcome; outcome: FindingOutcome }> {
  const m = new Map<string, { kind: Outcome; outcome: FindingOutcome }>();
  const adj = s.adjustment;
  if (!adj) return m;
  for (const kind of ["counted", "needsReview", "excluded"] as const)
    for (const outcome of adj[kind]) m.set(outcome.findingId, { kind, outcome });
  return m;
}

function InspectionSection({ s }: { s: ShipmentDetail }) {
  const { role } = useStore();
  const inspect = useShipmentWrite();
  const review = useShipmentWrite();
  const findings = s.inspection?.findings ?? [];
  const byId = outcomes(s);
  const minConfidence = s.agreement?.terms.acceptance.minConfidence ?? 0;
  const canInspect = s.status === "Inspection" && (role === "Buyer" || role === "Supplier");

  return (
    <Section
      title="AI Inspection"
      aside={
        canInspect && (
          <button
            disabled={inspect.isPending}
            onClick={() => inspect.mutate(() => api.inspect(s.id))}
            className={smallBtn}
          >
            {inspect.isPending ? "Inspecting…" : "Run inspection"}
          </button>
        )
      }
    >
      {findings.length ? (
        <div className="grid gap-4 md:grid-cols-2">
          {findings.map((f) => (
            <FindingCard
              key={f.id}
              f={f}
              // Before a proposal exists, fall back to the agreement's confidence threshold.
              kind={
                byId.get(f.id)?.kind ?? (f.confidence >= minConfidence ? "counted" : "needsReview")
              }
              detail={byId.get(f.id)?.outcome.detail}
              canReview={s.actions.canReview}
              busy={review.isPending}
              onReview={(decision) => review.mutate(() => api.reviewFinding(f.id, decision))}
            />
          ))}
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">
          {s.status === "Inspection"
            ? "Receipt photos are in. Run the inspection to analyze them."
            : "No inspection yet. It runs once the receipt photos are uploaded."}
        </p>
      )}
      <ErrorNote error={inspect.error ?? review.error} />
      <p className="mt-6 text-sm text-muted-foreground">
        AI can detect visible damage but cannot prove when or where it occurred. Findings are
        evidence for both parties, not a verdict.
      </p>
    </Section>
  );
}

function FindingCard(props: {
  f: Finding;
  kind: Outcome;
  detail: string | undefined;
  canReview: boolean;
  busy: boolean;
  onReview: (decision: "confirmed" | "rejected") => void;
}) {
  const { f, kind, detail, canReview, busy, onReview } = props;
  const bar =
    kind === "counted"
      ? "bg-success"
      : kind === "needsReview"
        ? "bg-warning"
        : "bg-muted-foreground";
  return (
    <div className="rounded-xl border p-5">
      <div className="flex items-center justify-between">
        <span className="font-mono text-sm">{f.unitRef}</span>
        {kind === "counted" ? (
          <span className="text-xs text-success">
            {f.reviewOverride === "confirmed" ? "Confirmed by Reviewer" : "Defect flagged"}
          </span>
        ) : kind === "needsReview" ? (
          <span className="flex items-center gap-1 rounded-full border border-warning/40 px-2.5 py-0.5 text-xs text-warning">
            <AlertTriangle className="h-3 w-3" />
            Needs review
          </span>
        ) : (
          <span className="text-xs text-muted-foreground">Excluded</span>
        )}
      </div>
      <p className="mt-2">{f.description}</p>
      {kind === "excluded" && detail && (
        <p className="mt-1 text-xs text-muted-foreground">{detail}</p>
      )}
      <div className="mt-4 flex items-center gap-3">
        <div className="h-1 flex-1 rounded-full bg-muted">
          <div className={`h-1 rounded-full ${bar}`} style={{ width: `${f.confidence * 100}%` }} />
        </div>
        <span className="font-mono text-xs text-muted-foreground">
          {Math.round(f.confidence * 100)}%
        </span>
      </div>
      {canReview && (
        <div className="mt-4 flex gap-2">
          {(["confirmed", "rejected"] as const).map((d) => (
            <button
              key={d}
              disabled={busy}
              onClick={() => onReview(d)}
              className={`rounded-full border px-4 py-1.5 text-xs disabled:opacity-40 ${
                f.reviewOverride === d
                  ? d === "confirmed"
                    ? "border-success/50 text-success"
                    : "border-destructive/50 text-destructive"
                  : "text-muted-foreground hover:border-primary/60 hover:text-foreground"
              }`}
            >
              {d === "confirmed" ? "Confirm" : "Reject"}
              {f.reviewOverride === d && "ed"}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// --- Adjustment -------------------------------------------------------------------------

function AdjustmentSection({ s }: { s: ShipmentDetail }) {
  const adj = s.adjustment;
  const title = s.status === "Resolved" ? "Resolved Adjustment" : "Proposed Adjustment";
  if (!adj)
    return (
      <Section title={title}>
        <p className="text-sm text-muted-foreground">
          No adjustment yet. The rules engine proposes one from the agreement once the inspection is
          done.
        </p>
      </Section>
    );
  const pending = adj.needsReview;
  return (
    <Section
      title={title}
      aside={<span className="text-3xl font-semibold text-sol">−{usd(adj.credit)}</span>}
    >
      <div className="rounded-xl border p-5 font-mono text-sm">
        <span className="text-muted-foreground">rule:</span>{" "}
        <span className="text-foreground">{adj.appliedRule.credit}</span>
        <div className="mt-2 text-muted-foreground">settlement: {adj.appliedRule.settlement}</div>
      </div>
      <div className="mt-6 grid gap-6 text-sm md:grid-cols-2">
        <div>
          <h3 className="mb-2 text-muted-foreground">Assumptions</h3>
          <ul className="space-y-1.5">
            {adj.assumptions.map((a) => (
              <li key={a}>{a}</li>
            ))}
          </ul>
        </div>
        <div>
          <h3 className="mb-2 text-muted-foreground">Uncertainty</h3>
          <ul className="space-y-1.5">
            {pending.length ? (
              <>
                <li>
                  {pending.length} item{pending.length === 1 ? "" : "s"} (
                  {pending.map((o) => unitShort(o.unitRef)).join(", ")}) need
                  {pending.length === 1 ? "s" : ""} human review, excluded from total
                </li>
                <li>If confirmed, adjustment would rise to {usd(adj.amountIfReviewedConfirmed)}</li>
              </>
            ) : (
              <li>No findings are waiting for human review</li>
            )}
            {adj.excluded.map((o) => (
              <li key={o.findingId}>
                {unitShort(o.unitRef)} excluded: {o.detail}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </Section>
  );
}

// --- Decision ---------------------------------------------------------------------------

function DecisionSection({ s }: { s: ShipmentDetail }) {
  const { role } = useStore();
  const write = useShipmentWrite();
  const [reason, setReason] = useState("");
  const [disputing, setDisputing] = useState(false);
  const adj = s.adjustment;
  const credit = adj ? usd(adj.credit) : "";
  const accepted = { Buyer: !!adj?.buyerAcceptedAt, Supplier: !!adj?.supplierAcceptedAt };
  const acceptance = adj && (
    <div className="flex flex-wrap gap-3">
      {PARTIES.map((p) => (
        <PartyBadge key={p} done={accepted[p]}>
          {p} {accepted[p] ? "accepted" : "has not accepted"}
        </PartyBadge>
      ))}
    </div>
  );
  const reasonLine = s.disputeReason && (
    <p className="mt-4 text-sm text-muted-foreground">Reason: {s.disputeReason}</p>
  );

  let body: ReactNode;
  if (s.status === "Proposed" && (s.actions.canAccept || s.actions.canDispute)) {
    body = (
      <div className="space-y-4">
        {acceptance}
        <p className="text-muted-foreground">
          Accept the {credit} adjustment, or dispute it with a reason.
        </p>
        {disputing ? (
          <div className="space-y-3">
            <textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={3}
              maxLength={400}
              placeholder="Why do you dispute this adjustment?"
              className="w-full rounded-xl border bg-background p-4 text-sm outline-none focus:border-primary/60"
            />
            <div className="flex gap-3">
              <button
                disabled={!reason.trim() || write.isPending}
                onClick={() => write.mutate(() => api.dispute(s.id, reason.trim()))}
                className="rounded-full border border-destructive/50 px-6 py-2.5 text-destructive disabled:opacity-40"
              >
                Submit dispute
              </button>
              <button onClick={() => setDisputing(false)} className="px-4 text-muted-foreground">
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <div className="flex gap-3">
            {s.actions.canAccept && (
              <button
                disabled={write.isPending}
                onClick={() => write.mutate(() => api.accept(s.id))}
                className={primaryBtn}
              >
                Accept
              </button>
            )}
            {s.actions.canDispute && (
              <button
                onClick={() => setDisputing(true)}
                className="rounded-full border px-8 py-2.5 hover:border-destructive/60"
              >
                Dispute
              </button>
            )}
          </div>
        )}
      </div>
    );
  } else if (s.status === "Proposed") {
    const waitingFor = PARTIES.filter((p) => !accepted[p]).join(" and ");
    body = (
      <div className="space-y-4">
        {acceptance}
        <p className="text-muted-foreground">
          {role === "Reviewer" ? "" : "You accepted. "}Waiting for {waitingFor} to accept or
          dispute.
        </p>
      </div>
    );
  } else if (s.status === "Accepted") {
    body = (
      <div className="space-y-4">
        <Chip status={s.status} />
        {acceptance}
        <p className="text-muted-foreground">Both parties accepted the {credit} adjustment.</p>
      </div>
    );
  } else if (s.status === "Disputed") {
    const left = adj?.needsReview.length ?? 0;
    body = (
      <div>
        <Chip status={s.status} />
        {reasonLine}
        {s.actions.canReview ? (
          <div className="mt-6 space-y-4 rounded-xl border p-5">
            <p className="text-sm">
              <span className="text-primary">Reviewer</span>: confirm or reject findings under AI
              Inspection. Resolving applies the agreement rule to the reviewed findings; you never
              enter an amount.
            </p>
            {left > 0 && (
              <p className="text-sm text-warning">
                {left} finding{left === 1 ? "" : "s"} still need{left === 1 ? "s" : ""} a decision
                before resolving.
              </p>
            )}
            <button
              disabled={!s.actions.canResolve || write.isPending}
              onClick={() => write.mutate(() => api.resolve(s.id))}
              className={primaryBtn}
            >
              Resolve at {credit}
            </button>
          </div>
        ) : (
          <p className="mt-4 text-muted-foreground">
            Waiting for a Reviewer to rule on the disputed findings.
          </p>
        )}
      </div>
    );
  } else if (s.status === "Resolved") {
    body = (
      <div>
        <Chip status={s.status} />
        {reasonLine}
        {adj && (
          <p className="mt-4 text-muted-foreground">
            Resolved by a Reviewer: {credit} credit, {usd(adj.settlementAmount)} to be paid.
          </p>
        )}
      </div>
    );
  } else {
    body = (
      <p className="text-muted-foreground">
        No adjustment to decide on yet. Current status:{" "}
        <span className="text-foreground">{s.status}</span>
      </p>
    );
  }

  return (
    <Section title="Decision">
      {body}
      <ErrorNote error={write.error} />
    </Section>
  );
}

// --- Audit trail ------------------------------------------------------------------------

function AuditSection({ s }: { s: ShipmentDetail }) {
  const verify = useVerifyAudit(s.id);
  const v = verify.data;
  const checks = new Map(v?.events.map((c) => [c.id, c.ok]));
  const failed = v ? [v.agreement, ...v.events, ...v.evidence].filter((c) => !c?.ok).length : 0;
  const label = verify.isPending
    ? "Verifying…"
    : verify.isError
      ? "Verification failed"
      : !v
        ? "Verify hashes"
        : v.verified
          ? `${v.checked} hashes verified`
          : `${failed} of ${v.checked} hashes failed`;
  const tone =
    verify.isError || (v && !v.verified)
      ? "border-destructive/50 text-destructive"
      : v
        ? "border-success/50 text-success"
        : "hover:border-primary/60";

  return (
    <Section
      title="Audit Trail"
      aside={
        <button
          disabled={verify.isPending}
          onClick={() => verify.mutate()}
          className={`flex items-center gap-2 rounded-full border px-4 py-2 text-sm ${tone}`}
        >
          <ShieldCheck className="h-4 w-4" />
          {label}
        </button>
      }
    >
      <ol className="relative space-y-6 border-l pl-6">
        {s.events.map((e) => {
          const ok = checks.get(e.id);
          return (
            <li key={e.id} className="relative">
              <span
                className={`absolute -left-[29px] top-1.5 h-2 w-2 rounded-full ${ok === true ? "bg-success" : ok === false ? "bg-destructive" : "bg-muted-foreground"}`}
              />
              <p>{e.text}</p>
              <p className="mt-1 text-xs text-muted-foreground">
                {formatAt(e.at)} · {e.actor} ·{" "}
                <span className="font-mono" title={e.hash}>
                  {short(e.hash)}
                </span>
                {ok === false && <span className="text-destructive"> · hash or link mismatch</span>}
              </p>
            </li>
          );
        })}
        {!s.events.length && <p className="text-sm text-muted-foreground">No events yet.</p>}
      </ol>
      {v && (
        <ul className="mt-8 grid gap-2 border-t pt-6 text-sm md:grid-cols-2">
          <CheckLine ok={v.agreement?.ok ?? false}>
            Agreement terms {v.agreement?.ok ? "match their hash" : "do not match their hash"}
          </CheckLine>
          <CheckLine ok={v.evidence.every((c) => c.ok)}>
            {v.evidence.filter((c) => c.ok).length} of {v.evidence.length} evidence files match
            {v.evidence.some((c) => !c.ok) &&
              ` (changed: ${v.evidence
                .filter((c) => !c.ok)
                .map((c) => c.id)
                .join(", ")})`}
          </CheckLine>
          <CheckLine ok={v.events.every((c) => c.ok)}>
            {v.events.filter((c) => c.ok).length} of {v.events.length} events match and link
          </CheckLine>
          <li className="text-muted-foreground">
            {v.chain.available
              ? `${v.chain.anchored} events anchored on Solana`
              : "Not anchored on-chain yet; checked against local hashes"}
          </li>
        </ul>
      )}
      <ErrorNote error={verify.error} />
    </Section>
  );
}

function CheckLine({ ok, children }: { ok: boolean; children: ReactNode }) {
  return (
    <li className={`flex items-center gap-2 ${ok ? "text-success" : "text-destructive"}`}>
      {ok ? (
        <Check className="h-3.5 w-3.5 shrink-0" />
      ) : (
        <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
      )}
      <span>{children}</span>
    </li>
  );
}
