import { createFileRoute, Link } from "@tanstack/react-router";
import { Check, Scale } from "lucide-react";
import { Chip, Logo } from "@/lib/store";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "ProofSettle — Payments backed by agreed evidence" },
      {
        name: "description",
        content:
          "B2B settlement where payment adjustments come from agreed rules and verified evidence.",
      },
      { property: "og:title", content: "ProofSettle — Payments backed by agreed evidence" },
      {
        property: "og:description",
        content: "Agree, inspect, settle. AI flags evidence, the agreement sets the amount.",
      },
    ],
  }),
  component: Landing,
});

const steps = [
  ["01", "Agree", "Buyer and supplier sign off on terms and credit rules before anything ships."],
  [
    "02",
    "Inspect",
    "Dispatch and receipt photos are hashed. AI flags possible defects for review.",
  ],
  ["03", "Settle", "The agreement rule calculates the adjustment. Both parties accept or dispute."],
];

const progress = ["Draft", "Agreed", "In Transit", "Inspection", "Proposed", "Accepted"];

function ProductPreview() {
  return (
    <div aria-hidden className="overflow-hidden rounded-[1.25rem] border bg-background">
      <div className="flex items-center justify-between gap-3 border-b px-4 py-3">
        <span className="flex items-center gap-1.5 text-xs font-semibold tracking-tight">
          <span className="h-3.5 w-3.5 rounded-[4px] bg-sol" />
          ProofSettle
        </span>
        <span className="flex items-center gap-3 text-[11px] text-muted-foreground">
          <span className="hidden sm:inline">Shipments</span>
          <span className="rounded-full border px-2 py-0.5">
            Signed in as <span className="text-primary">Buyer</span>
          </span>
        </span>
      </div>

      <div className="space-y-4 p-4 sm:p-5">
        <div>
          <p className="font-mono text-[11px] text-muted-foreground">PS-1042</p>
          <div className="mt-1 flex items-start justify-between gap-3">
            <h2 className="text-lg font-semibold leading-tight tracking-tight sm:text-xl">
              100 metal components, $10,000
            </h2>
            <Chip status="Proposed" />
          </div>
          <p className="mt-1.5 text-xs text-muted-foreground">
            <span className="block sm:inline">Ferro Precision Works</span>
            <span className="hidden sm:inline"> → </span>
            <span className="block sm:inline">
              <span className="sm:hidden">→ </span>Northgate Assembly Ltd
            </span>
          </p>
        </div>

        <div>
          <div className="flex gap-1.5">
            {progress.map((label, i) => (
              <div key={label} className="min-w-0 flex-1">
                <div className={`h-1 rounded-full ${i < 5 ? "bg-sol" : "bg-muted"}`} />
                <p
                  className={`mt-2 hidden whitespace-nowrap text-[10px] leading-none sm:block ${i === 4 ? "text-foreground" : "text-muted-foreground"}`}
                >
                  {label}
                </p>
              </div>
            ))}
          </div>
          <p className="mt-2 text-[11px] text-muted-foreground sm:hidden">
            <span className="text-foreground">Proposed</span> · step 5 of 6
          </p>
        </div>

        <div className="flex items-start gap-2 rounded-xl border border-primary/30 px-3 py-2.5 text-xs leading-relaxed">
          <Scale className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />
          <span>
            AI never decides the payment amount. The amount always comes from the agreement rules.
          </span>
        </div>

        <div className="rounded-2xl border bg-card p-4">
          <h3 className="text-sm font-semibold">Agreement</h3>
          <dl className="mt-3 grid gap-3 text-xs leading-snug sm:grid-cols-3">
            <div>
              <dt className="text-muted-foreground">Goods</dt>
              <dd className="mt-1">100 machined metal components</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Contract value</dt>
              <dd className="mt-1">$10,000</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Credit rule</dt>
              <dd className="mt-1">$100 per confirmed defective component</dd>
            </div>
          </dl>
          <div className="mt-4 flex flex-wrap gap-2">
            {["Buyer", "Supplier"].map((party) => (
              <span
                key={party}
                className="inline-flex items-center gap-1 rounded-full border border-success/40 px-2 py-0.5 text-[10px] text-success"
              >
                <Check className="h-3 w-3" />
                {party} approved
              </span>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function Landing() {
  return (
    <div className="relative min-h-screen">
      <div className="hero-atmosphere pointer-events-none absolute inset-x-0 top-0 h-[880px]" />

      <nav className="relative z-10 mx-auto flex h-16 max-w-6xl items-center justify-between px-6">
        <Logo />
        <div className="flex items-center gap-5 sm:gap-6">
          <a
            href="#how-it-works"
            className="hidden text-sm text-muted-foreground transition-colors hover:text-foreground md:inline"
          >
            How it works
          </a>
          <Link
            to="/login"
            className="text-sm text-muted-foreground transition-colors hover:text-foreground"
          >
            Sign in
          </Link>
          <Link
            to="/login"
            className="rounded-full bg-sol px-4 py-2 text-sm font-medium text-background transition-opacity hover:opacity-90"
          >
            Open demo
          </Link>
        </div>
      </nav>

      <section className="relative z-10 mx-auto grid max-w-6xl items-center gap-14 px-6 pb-20 pt-10 lg:grid-cols-[minmax(0,0.92fr)_minmax(0,1.08fr)] lg:gap-12 lg:pb-28 lg:pt-14">
        <div className="fade-up">
          <p className="inline-flex items-center gap-2 rounded-full border bg-card/80 px-3 py-1 text-xs text-muted-foreground">
            <span className="h-1.5 w-1.5 rounded-full bg-sol" />
            B2B settlement for industrial supply
          </p>
          <h1 className="mt-6 text-[2.35rem] font-semibold leading-[1.02] tracking-tight sm:text-5xl lg:text-[3.15rem]">
            <span className="block">Payments backed</span>
            <span className="mt-1 block sm:whitespace-nowrap">
              by <span className="text-sol">agreed evidence</span>
            </span>
          </h1>
          <p className="mt-6 max-w-md text-base leading-relaxed text-muted-foreground sm:text-lg">
            AI inspects the evidence. Your agreement sets the amount. Nobody argues over photos for
            weeks.
          </p>
          <div className="mt-8 flex flex-wrap items-center gap-3">
            <Link
              to="/login"
              className="inline-flex rounded-full bg-sol px-7 py-3 text-sm font-medium text-background transition-opacity hover:opacity-90"
            >
              Open demo
            </Link>
            <a
              href="#how-it-works"
              className="inline-flex rounded-full border px-7 py-3 text-sm font-medium transition-colors hover:bg-card"
            >
              How it works
            </a>
          </div>
          <div className="mt-12 flex gap-8 sm:gap-10">
            <div>
              <p className="text-2xl font-semibold tracking-tight">−$300</p>
              <p className="mt-1 max-w-[10rem] text-xs leading-relaxed text-muted-foreground">
                Proposed from the signed credit rule
              </p>
            </div>
            <div className="w-px self-stretch bg-border" />
            <div>
              <p className="text-2xl font-semibold tracking-tight">3</p>
              <p className="mt-1 max-w-[10rem] text-xs leading-relaxed text-muted-foreground">
                Defects flagged on shipment PS-1042
              </p>
            </div>
          </div>
        </div>

        <div className="relative fade-up" style={{ animationDelay: "120ms" }}>
          <div className="absolute -inset-8 -z-10 rounded-[2.5rem] bg-primary/20 blur-3xl" />
          <div className="absolute -bottom-6 -right-2 -z-10 h-40 w-40 rounded-full bg-success/15 blur-3xl" />
          <div className="rounded-[1.85rem] border bg-card/60 p-2.5 sm:p-3">
            <ProductPreview />
          </div>
        </div>
      </section>

      <section id="how-it-works" className="relative z-10 mx-auto max-w-6xl scroll-mt-8 px-6 pb-24">
        <div className="mb-8 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <h2 className="text-2xl font-semibold tracking-tight">Agree, inspect, settle</h2>
          <p className="max-w-sm text-sm leading-relaxed text-muted-foreground">
            The model can flag a photo. Only the agreement both sides signed can change the payment.
          </p>
        </div>
        <div className="grid overflow-hidden rounded-2xl border bg-card/40 md:grid-cols-3">
          {steps.map(([n, title, detail], i) => (
            <div
              key={title}
              className="border-b p-7 last:border-b-0 fade-up md:border-r md:border-b-0 md:last:border-r-0"
              style={{ animationDelay: `${i * 80}ms` }}
            >
              <span className="font-mono text-xs text-muted-foreground">{n}</span>
              <h3 className="mt-4 text-xl font-semibold">{title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{detail}</p>
            </div>
          ))}
        </div>
      </section>

      <footer className="relative z-10 border-t">
        <div className="mx-auto flex max-w-6xl justify-between px-6 py-8 text-sm text-muted-foreground">
          <span>ProofSettle</span>
          <span>HackGB Industrial track, 2026</span>
        </div>
      </footer>
    </div>
  );
}
