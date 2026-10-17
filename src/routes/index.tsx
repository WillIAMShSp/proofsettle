import { createFileRoute, Link } from "@tanstack/react-router";
import { Logo } from "@/lib/store";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "ProofSettle — Payments backed by agreed evidence" },
      { name: "description", content: "B2B settlement where payment adjustments come from agreed rules and verified evidence." },
      { property: "og:title", content: "ProofSettle — Payments backed by agreed evidence" },
      { property: "og:description", content: "Agree, inspect, settle. AI flags evidence, the agreement sets the amount." },
    ],
  }),
  component: Landing,
});

const steps = [
  ["01", "Agree", "Buyer and supplier sign off on terms and credit rules before anything ships."],
  ["02", "Inspect", "Dispatch and receipt photos are hashed. AI flags possible defects for review."],
  ["03", "Settle", "The agreement rule calculates the adjustment. Both parties accept or dispute."],
];

function Landing() {
  return (
    <div className="min-h-screen">
      <nav className="mx-auto flex h-16 max-w-6xl items-center justify-between px-6">
        <Logo />
        <Link to="/login" className="text-sm text-muted-foreground hover:text-foreground">Sign in</Link>
      </nav>
      <section className="mx-auto max-w-4xl px-6 pb-32 pt-36 text-center fade-up">
        <p className="mb-6 text-sm text-muted-foreground">B2B settlement for industrial supply</p>
        <h1 className="text-5xl font-semibold leading-[1.05] tracking-tight md:text-7xl">
          Payments backed by <span className="text-sol">agreed evidence</span>
        </h1>
        <p className="mx-auto mt-6 max-w-xl text-lg text-muted-foreground">
          AI inspects the evidence. Your agreement sets the amount. Nobody argues over photos for weeks.
        </p>
        <Link to="/login" className="mt-10 inline-flex rounded-full bg-sol px-8 py-3.5 font-medium text-background transition-opacity hover:opacity-90">
          Open demo
        </Link>
      </section>
      <section className="mx-auto grid max-w-6xl gap-6 px-6 pb-32 md:grid-cols-3">
        {steps.map(([n, t, d], i) => (
          <div key={t} className="card-surface p-8 fade-up" style={{ animationDelay: `${i * 100}ms` }}>
            <span className="font-mono text-xs text-muted-foreground">{n}</span>
            <h3 className="mt-4 text-2xl font-semibold">{t}</h3>
            <p className="mt-3 text-muted-foreground">{d}</p>
          </div>
        ))}
      </section>
      <footer className="border-t">
        <div className="mx-auto flex max-w-6xl justify-between px-6 py-8 text-sm text-muted-foreground">
          <span>ProofSettle</span><span>HackGB Industrial track, 2026</span>
        </div>
      </footer>
    </div>
  );
}
