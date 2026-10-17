import { createFileRoute, Link } from "@tanstack/react-router";
import { useState, type ReactNode } from "react";
import { Check, AlertTriangle, ShieldCheck, Scale } from "lucide-react";
import { Chip, TopBar, useStore, hashOf, type Status } from "@/lib/store";
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
const CREDIT = 100;
const findings = [
  { item: "Component #017", issue: "Bent flange", conf: 0.94, confirmed: true },
  { item: "Component #042", issue: "Surface crack near bore", conf: 0.91, confirmed: true },
  { item: "Component #078", issue: "Deep scratch on mating face", conf: 0.88, confirmed: true },
  { item: "Component #063", issue: "Possible discoloration", conf: 0.52, confirmed: false },
];
const short = (x: string) => `${x.slice(0, 8)}…${x.slice(-6)}`;

function Section({ title, children, aside }: { title: string; children: ReactNode; aside?: ReactNode }) {
  return (
    <section className="card-surface p-8 fade-up">
      <div className="mb-6 flex items-center justify-between"><h2 className="text-xl font-semibold">{title}</h2>{aside}</div>
      {children}
    </section>
  );
}

function Detail() {
  const { id } = Route.useParams();
  const { shipments, role, update } = useStore();
  const s = shipments.find((x) => x.id === id);
  const [reason, setReason] = useState("");
  const [disputing, setDisputing] = useState(false);
  const [verify, setVerify] = useState<"idle" | "run" | "ok">("idle");
  if (!s) return <div className="min-h-screen"><TopBar /><p className="p-16 text-center text-muted-foreground">Shipment not found. <Link to="/dashboard" className="text-primary">Back</Link></p></div>;

  const defects = findings.filter((f) => f.confirmed).length;
  const adj = defects * CREDIT;
  const stepIdx = s.status === "Disputed" || s.status === "Resolved" ? 5 : STEPS.indexOf(s.status);
  const log = (text: string, status: Status, extra = {}) =>
    update(s.id, (x) => ({ ...x, ...extra, status, events: [...x.events, { at: "Just now", actor: role ?? "User", text, hash: hashOf(text) }] }));

  return (
    <div className="min-h-screen">
      <TopBar />
      <main className="mx-auto max-w-5xl space-y-6 px-6 py-16">
        <div className="fade-up">
          <span className="font-mono text-xs text-muted-foreground">{s.id}</span>
          <div className="mt-1 flex flex-wrap items-center justify-between gap-4">
            <h1 className="text-4xl font-semibold tracking-tight">{s.title}, ${s.amount.toLocaleString()}</h1>
            <Chip status={s.status} />
          </div>
          <p className="mt-2 text-muted-foreground">{s.supplier} → {s.buyer}</p>
        </div>

        <div className="flex gap-2 fade-up">
          {STEPS.map((st, i) => {
            const label = i === 5 && (s.status === "Disputed" || s.status === "Resolved") ? s.status : st;
            const bad = label === "Disputed";
            return (
              <div key={st} className="flex-1">
                <div className={`h-1 rounded-full ${i <= stepIdx ? (bad && i === 5 ? "bg-destructive" : "bg-sol") : "bg-muted"}`} />
                <p className={`mt-2 text-xs ${i === stepIdx ? "text-foreground" : "text-muted-foreground"}`}>{label}</p>
              </div>
            );
          })}
        </div>

        <div className="flex items-center gap-3 rounded-2xl border border-primary/30 px-5 py-4 text-sm fade-up">
          <Scale className="h-4 w-4 shrink-0 text-primary" />
          <span>AI never decides the payment amount. The amount always comes from the agreement rules.</span>
        </div>

        <Section title="Agreement">
          <dl className="grid gap-6 text-sm md:grid-cols-3">
            <div><dt className="text-muted-foreground">Goods</dt><dd className="mt-1 text-base">100 machined metal components</dd></div>
            <div><dt className="text-muted-foreground">Contract value</dt><dd className="mt-1 text-base">${s.amount.toLocaleString()}</dd></div>
            <div><dt className="text-muted-foreground">Credit rule</dt><dd className="mt-1 text-base">${CREDIT} per confirmed defective component</dd></div>
          </dl>
          <div className="mt-6 flex gap-3">
            {["Buyer", "Supplier"].map((p) => (
              <span key={p} className="inline-flex items-center gap-1.5 rounded-full border border-success/40 px-3 py-1 text-xs text-success"><Check className="h-3 w-3" />{p} approved</span>
            ))}
          </div>
        </Section>

        <Section title="Evidence">
          {[["Dispatch", dispatchImg], ["Receipt", receiptImg]].map(([label, img]) => (
            <div key={label} className="mb-8 last:mb-0">
              <h3 className="mb-3 text-sm text-muted-foreground">{label} photos</h3>
              <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
                {[0, 1, 2, 3].map((n) => (
                  <figure key={n}>
                    <img src={img} alt={`${label} photo ${n + 1}`} loading="lazy" className="aspect-square w-full rounded-xl object-cover" style={{ objectPosition: `${n * 33}% ${n * 25}%` }} />
                    <figcaption className="mt-2 flex items-center justify-between text-xs">
                      <span className="font-mono text-muted-foreground">{short(hashOf(`${label}${n}`))}</span>
                      <span className="flex items-center gap-1 text-success"><Check className="h-3 w-3" />Verified</span>
                    </figcaption>
                  </figure>
                ))}
              </div>
            </div>
          ))}
        </Section>

        <Section title="AI Inspection">
          <div className="grid gap-4 md:grid-cols-2">
            {findings.map((f) => (
              <div key={f.item} className="rounded-xl border p-5">
                <div className="flex items-center justify-between">
                  <span className="font-mono text-sm">{f.item}</span>
                  {f.confirmed
                    ? <span className="text-xs text-success">Defect flagged</span>
                    : <span className="flex items-center gap-1 rounded-full border border-warning/40 px-2.5 py-0.5 text-xs text-warning"><AlertTriangle className="h-3 w-3" />Needs review</span>}
                </div>
                <p className="mt-2">{f.issue}</p>
                <div className="mt-4 flex items-center gap-3">
                  <div className="h-1 flex-1 rounded-full bg-muted"><div className={`h-1 rounded-full ${f.confirmed ? "bg-success" : "bg-warning"}`} style={{ width: `${f.conf * 100}%` }} /></div>
                  <span className="font-mono text-xs text-muted-foreground">{Math.round(f.conf * 100)}%</span>
                </div>
              </div>
            ))}
          </div>
          <p className="mt-6 text-sm text-muted-foreground">AI can detect visible damage but cannot prove when or where it occurred. Findings are evidence for both parties, not a verdict.</p>
        </Section>

        <Section title="Proposed Adjustment" aside={<span className="text-3xl font-semibold text-sol">−${adj}</span>}>
          <div className="rounded-xl border p-5 font-mono text-sm">
            <span className="text-muted-foreground">rule:</span> {defects} confirmed defects × ${CREDIT} = <span className="text-foreground">${adj}</span>
            <div className="mt-2 text-muted-foreground">settlement: ${s.amount.toLocaleString()} − ${adj} = ${(s.amount - adj).toLocaleString()}</div>
          </div>
          <div className="mt-6 grid gap-6 text-sm md:grid-cols-2">
            <div><h3 className="mb-2 text-muted-foreground">Assumptions</h3>
              <ul className="space-y-1.5"><li>Only findings at ≥ 85% confidence count as confirmed</li><li>Dispatch photos show all 100 components intact</li><li>Credit rule taken unchanged from the signed agreement</li></ul></div>
            <div><h3 className="mb-2 text-muted-foreground">Uncertainty</h3>
              <ul className="space-y-1.5"><li>1 item (#063) needs human review, excluded from total</li><li>If confirmed, adjustment would rise to ${adj + CREDIT}</li></ul></div>
          </div>
        </Section>

        <Section title="Decision">
          {s.status === "Accepted" || s.status === "Disputed" ? (
            <div>
              <Chip status={s.status} />
              {s.disputeReason && <p className="mt-4 text-sm text-muted-foreground">Reason: {s.disputeReason}</p>}
            </div>
          ) : role === "Supplier" ? (
            <div className="space-y-4">
              <p className="text-muted-foreground">Accept the ${adj} adjustment, or dispute it with a reason.</p>
              {disputing ? (
                <div className="space-y-3">
                  <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={3} placeholder="Why do you dispute this adjustment?" className="w-full rounded-xl border bg-background p-4 text-sm outline-none focus:border-primary/60" />
                  <div className="flex gap-3">
                    <button disabled={!reason.trim()} onClick={() => log(`Supplier disputed adjustment: ${reason.trim()}`, "Disputed", { disputeReason: reason.trim() })} className="rounded-full border border-destructive/50 px-6 py-2.5 text-destructive disabled:opacity-40">Submit dispute</button>
                    <button onClick={() => setDisputing(false)} className="px-4 text-muted-foreground">Cancel</button>
                  </div>
                </div>
              ) : (
                <div className="flex gap-3">
                  <button onClick={() => log(`Supplier accepted $${adj} adjustment`, "Accepted")} className="rounded-full bg-sol px-8 py-2.5 font-medium text-background hover:opacity-90">Accept</button>
                  <button onClick={() => setDisputing(true)} className="rounded-full border px-8 py-2.5 hover:border-destructive/60">Dispute</button>
                </div>
              )}
            </div>
          ) : (
            <p className="text-muted-foreground">Awaiting supplier response. Current status: <span className="text-foreground">{s.status}</span></p>
          )}
        </Section>

        <Section title="Audit Trail" aside={
          <button onClick={() => { setVerify("run"); setTimeout(() => setVerify("ok"), 900); }} className={`flex items-center gap-2 rounded-full border px-4 py-2 text-sm ${verify === "ok" ? "border-success/50 text-success" : "hover:border-primary/60"}`}>
            <ShieldCheck className="h-4 w-4" />{verify === "idle" ? "Verify hashes" : verify === "run" ? "Verifying…" : `${s.events.length} hashes verified`}
          </button>
        }>
          <ol className="relative space-y-6 border-l pl-6">
            {s.events.map((e, i) => (
              <li key={i} className="relative">
                <span className={`absolute -left-[29px] top-1.5 h-2 w-2 rounded-full ${verify === "ok" ? "bg-success" : "bg-muted-foreground"}`} />
                <p>{e.text}</p>
                <p className="mt-1 text-xs text-muted-foreground">{e.at} · {e.actor} · <span className="font-mono">{short(e.hash)}</span></p>
              </li>
            ))}
            {!s.events.length && <p className="text-sm text-muted-foreground">No events yet.</p>}
          </ol>
        </Section>
      </main>
    </div>
  );
}
