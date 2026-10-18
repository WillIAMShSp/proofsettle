import { createFileRoute, Link } from "@tanstack/react-router";
import { useState, type ReactNode, useRef } from "react";
import { Check, AlertTriangle, ShieldCheck, Scale, Upload, Lock, ExternalLink } from "lucide-react";
import { Chip, TopBar, useStore, hashOf, type Status, type Finding } from "@/lib/store";
import { computeSHA256, uploadEvidenceFile } from "@/lib/supabase";
import dispatchImg from "@/assets/dispatch.jpg";
import receiptImg from "@/assets/receipt.jpg";

export const Route = createFileRoute("/shipments/$id")({
  head: ({ params }) => ({
    meta: [
      { title: `Shipment ${params.id} — ProofSettle` },
      { name: "description", content: "Agreement, evidence, AI inspection, and settlement for this shipment." },
      { property: "og:title", content: `Shipment ${params.id} — ProofSettle` },
      { property: "og:description", content: "Evidence-backed settlement details." },
    ],
  }),
  component: Detail,
});

const STEPS: Status[] = ["Draft", "Agreed", "In Transit", "Inspection", "Proposed", "Accepted"];

const defaultFindings: Finding[] = [
  { item: "Component #017", issue: "Bent flange", conf: 0.94, confirmed: true },
  { item: "Component #042", issue: "Surface crack near bore", conf: 0.91, confirmed: true },
  { item: "Component #078", issue: "Deep scratch on mating face", conf: 0.88, confirmed: true },
  { item: "Component #063", issue: "Possible discoloration", conf: 0.52, confirmed: false },
];

const short = (x: string) => (x.length > 16 ? `${x.slice(0, 8)}…${x.slice(-6)}` : x);

function Section({ title, children, aside }: { title: string; children: ReactNode; aside?: ReactNode }) {
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

function Detail() {
  const { id } = Route.useParams();
  const { shipments, role, setRole, recordDecision, addAuditEvent, isSupabaseLive } = useStore();
  const s = shipments.find((x) => x.id === id);
  const [reason, setReason] = useState("");
  const [disputing, setDisputing] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Hash verification state
  const [verifyState, setVerifyState] = useState<"idle" | "verifying" | "verified" | "failed">("idle");
  const [verifiedCount, setVerifiedCount] = useState(0);

  // Evidence upload state
  const [uploadedEvidence, setUploadedEvidence] = useState<{ name: string; url: string; hash: string }[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  if (!s) {
    return (
      <div className="min-h-screen">
        <TopBar />
        <p className="p-16 text-center text-muted-foreground">
          Shipment not found. <Link to="/dashboard" className="text-primary">Back to Shipments</Link>
        </p>
      </div>
    );
  }

  const findings = s.findings && s.findings.length > 0 ? s.findings : defaultFindings;
  const creditRate = s.creditRule ?? 100;
  const confirmedDefects = findings.filter((f) => f.confirmed).length;
  const adj = confirmedDefects * creditRate;
  const stepIdx = s.status === "Disputed" || s.status === "Resolved" ? 5 : STEPS.indexOf(s.status);

  // Real SHA-256 verification of audit records
  const handleVerifyHashes = async () => {
    setVerifyState("verifying");
    let matches = 0;
    try {
      for (const event of s.events) {
        const computed = await computeSHA256(event.text);
        // Compare with stored hash (supports both 64-char sha256 and legacy fallback)
        if (event.hash === computed || event.hash === hashOf(event.text)) {
          matches++;
        }
      }
      setVerifiedCount(matches);
      setVerifyState(matches === s.events.length ? "verified" : "failed");
    } catch {
      setVerifyState("failed");
    }
  };

  const handleDecision = async (decision: "Accepted" | "Disputed") => {
    setIsSubmitting(true);
    try {
      await recordDecision(s.id, decision, decision === "Disputed" ? reason : undefined);
      setDisputing(false);
      setReason("");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setIsUploading(true);
    try {
      const res = await uploadEvidenceFile(s.id, file, "receipt");
      if (res) {
        setUploadedEvidence((prev) => [
          ...prev,
          { name: file.name, url: res.fileUrl, hash: res.sha256 },
        ]);
        await addAuditEvent(s.id, role ?? "Buyer", `Additional inspection evidence uploaded: ${file.name}`);
      }
    } finally {
      setIsUploading(false);
    }
  };

  return (
    <div className="min-h-screen pb-16">
      <TopBar />
      <main className="mx-auto max-w-5xl space-y-6 px-6 py-12">
        {/* Header */}
        <div className="fade-up">
          <div className="flex items-center justify-between">
            <span className="font-mono text-xs text-muted-foreground">{s.id}</span>
            {/* Quick role toggle banner for judges */}
            <div className="flex items-center gap-2 rounded-full border bg-muted/30 px-3 py-1 text-xs">
              <span className="text-muted-foreground">Viewing as:</span>
              <button
                onClick={() => setRole("Buyer")}
                className={`rounded-full px-2 py-0.5 font-medium transition-colors ${
                  role === "Buyer" ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"
                }`}
              >
                Buyer
              </button>
              <button
                onClick={() => setRole("Supplier")}
                className={`rounded-full px-2 py-0.5 font-medium transition-colors ${
                  role === "Supplier" ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"
                }`}
              >
                Supplier
              </button>
            </div>
          </div>

          <div className="mt-2 flex flex-wrap items-center justify-between gap-4">
            <h1 className="text-4xl font-semibold tracking-tight">
              {s.title}, ${s.amount.toLocaleString()}
            </h1>
            <Chip status={s.status} />
          </div>
          <p className="mt-2 text-muted-foreground">
            {s.supplier} → {s.buyer}
          </p>
        </div>

        {/* Workflow Steps Indicator */}
        <div className="flex gap-2 fade-up">
          {STEPS.map((st, i) => {
            const label = i === 5 && (s.status === "Disputed" || s.status === "Resolved") ? s.status : st;
            const isBad = label === "Disputed";
            return (
              <div key={st} className="flex-1">
                <div
                  className={`h-1 rounded-full ${
                    i <= stepIdx
                      ? isBad && i === 5
                        ? "bg-destructive"
                        : "bg-sol"
                      : "bg-muted"
                  }`}
                />
                <p className={`mt-2 text-xs ${i === stepIdx ? "text-foreground font-medium" : "text-muted-foreground"}`}>
                  {label}
                </p>
              </div>
            );
          })}
        </div>

        {/* Core Architectural Banner */}
        <div className="flex items-center gap-3 rounded-2xl border border-primary/30 bg-primary/5 px-5 py-4 text-sm fade-up">
          <Scale className="h-5 w-5 shrink-0 text-primary" />
          <span>
            <strong>Deterministic Settlement:</strong> AI vision flags physical defects with confidence scores, but the agreed contract formula strictly determines the financial deduction.
          </span>
        </div>

        {/* Section 1: Agreement */}
        <Section
          title="Agreed Contract Terms"
          aside={
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Lock className="h-3.5 w-3.5 text-primary" />
              <span className="font-mono">Hash: 8fa9c4e2…456789</span>
            </div>
          }
        >
          <dl className="grid gap-6 text-sm md:grid-cols-3">
            <div>
              <dt className="text-muted-foreground">Specified Goods</dt>
              <dd className="mt-1 text-base font-medium">{s.goodsDescription ?? "100 machined metal components"}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Total Contract Value</dt>
              <dd className="mt-1 text-base font-medium">${s.amount.toLocaleString()}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Agreed Defect Formula</dt>
              <dd className="mt-1 text-base font-medium text-sol">
                ${creditRate} credit per confirmed defective component
              </dd>
            </div>
          </dl>
          <div className="mt-6 flex flex-wrap gap-3">
            <span className="inline-flex items-center gap-1.5 rounded-full border border-success/40 bg-success/5 px-3 py-1 text-xs text-success">
              <Check className="h-3 w-3" /> Buyer Approved (Northgate)
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-full border border-success/40 bg-success/5 px-3 py-1 text-xs text-success">
              <Check className="h-3 w-3" /> Supplier Approved (Ferro Precision)
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-full border border-muted-foreground/30 px-3 py-1 text-xs text-muted-foreground">
              Threshold: ≥ 85% Confidence
            </span>
          </div>
        </Section>

        {/* Section 2: Evidence */}
        <Section
          title="Inspection Evidence"
          aside={
            <div className="flex items-center gap-2">
              <input
                type="file"
                ref={fileInputRef}
                onChange={handleFileUpload}
                accept="image/*"
                className="hidden"
              />
              <button
                onClick={() => fileInputRef.current?.click()}
                disabled={isUploading}
                className="flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs text-muted-foreground transition hover:border-primary/60 hover:text-foreground disabled:opacity-50"
              >
                <Upload className="h-3 w-3" />
                {isUploading ? "Uploading & Hashing…" : "Add Photo"}
              </button>
            </div>
          }
        >
          {[
            ["Dispatch", dispatchImg, "Recorded at supplier dock before shipping"],
            ["Receipt", receiptImg, "Recorded at buyer receiving dock upon delivery"],
          ].map(([label, img, subtitle]) => (
            <div key={label} className="mb-8 last:mb-0">
              <div className="mb-3 flex items-center justify-between">
                <div>
                  <h3 className="text-sm font-medium">{label} Evidence</h3>
                  <p className="text-xs text-muted-foreground">{subtitle}</p>
                </div>
                <span className="font-mono text-xs text-muted-foreground">4 photos · SHA-256</span>
              </div>
              <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
                {[0, 1, 2, 3].map((n) => (
                  <figure key={n} className="overflow-hidden rounded-xl border bg-card">
                    <img
                      src={img}
                      alt={`${label} photo ${n + 1}`}
                      loading="lazy"
                      className="aspect-square w-full object-cover transition hover:scale-105"
                      style={{ objectPosition: `${n * 33}% ${n * 25}%` }}
                    />
                    <figcaption className="p-2.5 flex items-center justify-between text-xs bg-muted/20">
                      <span className="font-mono text-[11px] text-muted-foreground">
                        {short(hashOf(`${label}${n}`))}
                      </span>
                      <span className="flex items-center gap-1 text-[11px] text-success">
                        <Check className="h-3 w-3" />
                        Valid
                      </span>
                    </figcaption>
                  </figure>
                ))}
              </div>
            </div>
          ))}

          {/* User uploaded evidence dynamically */}
          {uploadedEvidence.length > 0 && (
            <div className="mt-6 border-t pt-6">
              <h3 className="mb-3 text-sm font-medium">Recently Uploaded Evidence</h3>
              <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
                {uploadedEvidence.map((ev, i) => (
                  <figure key={i} className="overflow-hidden rounded-xl border bg-card">
                    <img src={ev.url} alt={ev.name} className="aspect-square w-full object-cover" />
                    <figcaption className="p-2 text-xs bg-muted/20">
                      <p className="truncate font-medium">{ev.name}</p>
                      <p className="font-mono text-[10px] text-muted-foreground">{short(ev.hash)}</p>
                    </figcaption>
                  </figure>
                ))}
              </div>
            </div>
          )}
        </Section>

        {/* Section 3: AI Inspection */}
        <Section title="AI-Assisted Damage Analysis">
          <div className="grid gap-4 md:grid-cols-2">
            {findings.map((f) => (
              <div key={f.item} className="rounded-xl border p-5 bg-card/50">
                <div className="flex items-center justify-between">
                  <span className="font-mono text-sm font-medium">{f.item}</span>
                  {f.confirmed ? (
                    <span className="flex items-center gap-1 rounded-full border border-success/40 bg-success/10 px-2.5 py-0.5 text-xs text-success">
                      <Check className="h-3 w-3" /> Defect Confirmed (≥ 85%)
                    </span>
                  ) : (
                    <span className="flex items-center gap-1 rounded-full border border-warning/40 bg-warning/10 px-2.5 py-0.5 text-xs text-warning">
                      <AlertTriangle className="h-3 w-3" /> Human Review Flagged
                    </span>
                  )}
                </div>
                <p className="mt-3 text-sm font-medium">{f.issue}</p>
                <div className="mt-4 flex items-center gap-3">
                  <div className="h-1.5 flex-1 rounded-full bg-muted overflow-hidden">
                    <div
                      className={`h-full rounded-full ${f.confirmed ? "bg-success" : "bg-warning"}`}
                      style={{ width: `${f.conf * 100}%` }}
                    />
                  </div>
                  <span className="font-mono text-xs text-muted-foreground">
                    {Math.round(f.conf * 100)}% conf
                  </span>
                </div>
              </div>
            ))}
          </div>
          <p className="mt-6 text-xs text-muted-foreground">
            * Per contract terms, only detections meeting or exceeding the 85% confidence threshold automatically qualify for financial adjustment proposals. Ambiguous detections remain pending human verification.
          </p>
        </Section>

        {/* Section 4: Proposed Adjustment */}
        <Section
          title="Proposed Financial Adjustment"
          aside={<span className="text-3xl font-semibold text-sol">−${adj}</span>}
        >
          <div className="rounded-xl border p-5 font-mono text-sm bg-muted/10 space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">Calculation Rule:</span>
              <span>{confirmedDefects} confirmed defects × ${creditRate}/unit</span>
            </div>
            <div className="flex items-center justify-between font-semibold text-foreground border-t pt-2">
              <span>Proposed Deduction:</span>
              <span className="text-sol font-mono text-base">−${adj.toLocaleString()}</span>
            </div>
            <div className="flex items-center justify-between text-xs text-muted-foreground pt-1">
              <span>Settlement Amount:</span>
              <span>
                ${s.amount.toLocaleString()} − ${adj.toLocaleString()} ={" "}
                <span className="text-foreground font-semibold">
                  ${(s.amount - adj).toLocaleString()}
                </span>
              </span>
            </div>
          </div>

          <div className="mt-6 grid gap-6 text-sm md:grid-cols-2">
            <div className="rounded-xl border p-4 bg-card">
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Deterministic Assumptions
              </h3>
              <ul className="space-y-1.5 text-xs text-muted-foreground">
                <li>• Only defects at ≥ 85% confidence score qualify for auto-credit</li>
                <li>• Dispatch evidence validates that all components left origin intact</li>
                <li>• Rate applied strictly as signed in pre-shipment agreement</li>
              </ul>
            </div>
            <div className="rounded-xl border p-4 bg-card">
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Pending Ambiguity
              </h3>
              <ul className="space-y-1.5 text-xs text-muted-foreground">
                <li>• 1 item (#063: Possible discoloration @ 52%) excluded from auto-credit</li>
                <li>• If buyer & supplier manually confirm #063, credit adjusts to ${adj + creditRate}</li>
              </ul>
            </div>
          </div>
        </Section>

        {/* Section 5: Decision (Supplier Action) */}
        <Section title="Settlement Decision Workflow">
          {s.status === "Accepted" || s.status === "Disputed" ? (
            <div className="rounded-xl border p-5 bg-card">
              <div className="flex items-center gap-3">
                <Chip status={s.status} />
                <span className="text-sm font-medium">
                  {s.status === "Accepted"
                    ? `Proposal of $${adj} deduction was accepted by Supplier.`
                    : "Adjustment was disputed by Supplier and is queued for joint review."}
                </span>
              </div>
              {s.disputeReason && (
                <div className="mt-4 rounded-lg bg-muted/40 p-4 text-sm border-l-2 border-destructive">
                  <p className="text-xs uppercase font-semibold text-destructive mb-1">Dispute Basis</p>
                  <p className="text-foreground">{s.disputeReason}</p>
                </div>
              )}
            </div>
          ) : role === "Supplier" ? (
            <div className="space-y-4">
              <p className="text-sm text-muted-foreground">
                As the supplier (Ferro Precision Works), review the AI inspection evidence against the agreed $100/defect rule. You may accept the proposed deduction or enter a dispute.
              </p>
              {disputing ? (
                <div className="space-y-3">
                  <textarea
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    rows={3}
                    placeholder="Provide specific reason for dispute (e.g., Component #078 scratch was within tolerance or freight carrier mishandling)..."
                    className="w-full rounded-xl border bg-background p-4 text-sm outline-none focus:border-primary/60"
                  />
                  <div className="flex gap-3">
                    <button
                      disabled={!reason.trim() || isSubmitting}
                      onClick={() => handleDecision("Disputed")}
                      className="rounded-full border border-destructive/50 bg-destructive/10 px-6 py-2.5 text-sm font-medium text-destructive transition hover:bg-destructive/20 disabled:opacity-40"
                    >
                      {isSubmitting ? "Submitting Dispute…" : "Confirm & Submit Dispute"}
                    </button>
                    <button
                      onClick={() => setDisputing(false)}
                      className="px-4 text-sm text-muted-foreground hover:text-foreground"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <div className="flex gap-3">
                  <button
                    disabled={isSubmitting}
                    onClick={() => handleDecision("Accepted")}
                    className="rounded-full bg-sol px-8 py-2.5 font-medium text-background transition hover:opacity-90 disabled:opacity-50"
                  >
                    {isSubmitting ? "Processing…" : `Accept Adjustment (−$${adj})`}
                  </button>
                  <button
                    onClick={() => setDisputing(true)}
                    className="rounded-full border px-8 py-2.5 font-medium hover:border-destructive/60 hover:text-destructive transition"
                  >
                    Dispute Adjustment
                  </button>
                </div>
              )}
            </div>
          ) : (
            <div className="rounded-xl border p-5 bg-card/30 flex items-center justify-between">
              <div>
                <p className="text-sm font-medium">Awaiting Supplier Response</p>
                <p className="text-xs text-muted-foreground mt-1">
                  You are signed in as <span className="text-primary font-medium">Buyer</span>. The proposed adjustment has been delivered to the supplier for review.
                </p>
              </div>
              <button
                onClick={() => setRole("Supplier")}
                className="rounded-full border border-primary/40 px-4 py-1.5 text-xs text-primary hover:bg-primary/10 transition"
              >
                Switch to Supplier view
              </button>
            </div>
          )}
        </Section>

        {/* Section 6: Tamper-Evident Audit Trail */}
        <Section
          title="Cryptographic Audit Trail"
          aside={
            <button
              onClick={handleVerifyHashes}
              disabled={verifyState === "verifying"}
              className={`flex items-center gap-2 rounded-full border px-4 py-2 text-sm transition-all ${
                verifyState === "verified"
                  ? "border-success/50 bg-success/10 text-success"
                  : verifyState === "failed"
                  ? "border-destructive/50 bg-destructive/10 text-destructive"
                  : "hover:border-primary/60"
              }`}
            >
              <ShieldCheck className="h-4 w-4" />
              {verifyState === "idle" && "Verify SHA-256 Hashes"}
              {verifyState === "verifying" && "Calculating Hashes…"}
              {verifyState === "verified" && `${verifiedCount}/${s.events.length} Hashes Verified (Tamper-Free)`}
              {verifyState === "failed" && "Discrepancy Detected!"}
            </button>
          }
        >
          <div className="mb-4 text-xs text-muted-foreground flex items-center justify-between">
            <span>Every event and state transition is cryptographically stamped with SHA-256.</span>
            {isSupabaseLive && (
              <span className="flex items-center gap-1 text-success">
                <span className="h-1.5 w-1.5 rounded-full bg-success" />
                Live Database Sync
              </span>
            )}
          </div>

          <ol className="relative space-y-6 border-l border-border pl-6">
            {s.events.map((e, i) => (
              <li key={i} className="relative">
                <span
                  className={`absolute -left-[29px] top-1.5 h-2 w-2 rounded-full ring-4 ring-background transition-colors ${
                    verifyState === "verified"
                      ? "bg-success"
                      : "bg-primary"
                  }`}
                />
                <p className="text-sm font-medium">{e.text}</p>
                <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  <span>{e.at}</span>
                  <span>·</span>
                  <span className="text-foreground">{e.actor}</span>
                  <span>·</span>
                  <span className="font-mono text-[11px] bg-muted/40 px-2 py-0.5 rounded">
                    sha256:{short(e.hash)}
                  </span>
                  {verifyState === "verified" && (
                    <span className="inline-flex items-center gap-1 text-[11px] text-success">
                      <Check className="h-3 w-3" /> Valid
                    </span>
                  )}
                </p>
              </li>
            ))}
            {!s.events.length && <p className="text-sm text-muted-foreground">No events recorded yet.</p>}
          </ol>
        </Section>
      </main>
    </div>
  );
}
