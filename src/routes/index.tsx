import { createFileRoute, Link } from "@tanstack/react-router";
import {
  ArrowUpRight,
  Check,
  FileCheck2,
  Fingerprint,
  Scale,
  ScanEye,
  ShieldCheck,
} from "lucide-react";
import { useEffect, useRef } from "react";
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

const progress = ["Draft", "Agreed", "In Transit", "Inspection", "Proposed", "Accepted"];

function scrollToSteps() {
  document.getElementById("how-it-works")?.scrollIntoView({ behavior: "smooth", block: "start" });
}

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
                <div
                  className={`shipment-progress-segment h-1 rounded-full ${
                    i < 5 ? "shipment-progress-active bg-sol" : "bg-muted"
                  } ${i === 4 ? "shipment-progress-current" : ""}`}
                  style={{ animationDelay: `${i * 360}ms` }}
                />
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

function useScrollReveals() {
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const root = rootRef.current;
    if (!root || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    const items = [...root.querySelectorAll<HTMLElement>("[data-reveal]")];
    const revealVisible = () => {
      for (const item of items) {
        const rect = item.getBoundingClientRect();
        if (rect.top >= window.innerHeight * 0.9 || rect.bottom <= 0) continue;
        item.classList.add("is-revealed");
      }
    };

    revealVisible();
    window.addEventListener("scroll", revealVisible, { passive: true });
    return () => {
      window.removeEventListener("scroll", revealVisible);
    };
  }, []);

  return rootRef;
}

function CursorGlow() {
  const glowRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (window.matchMedia("(pointer: coarse), (prefers-reduced-motion: reduce)").matches) return;

    const glow = glowRef.current;
    if (!glow) return;

    const move = (event: PointerEvent) => {
      glow.style.transform = `translate3d(${event.clientX}px, ${event.clientY}px, 0) translate(-50%, -50%)`;
      glow.style.opacity = "1";
    };
    const leave = () => {
      glow.style.opacity = "0";
    };

    window.addEventListener("pointermove", move, { passive: true });
    document.documentElement.addEventListener("pointerleave", leave);

    return () => {
      window.removeEventListener("pointermove", move);
      document.documentElement.removeEventListener("pointerleave", leave);
    };
  }, []);

  return <div ref={glowRef} aria-hidden="true" className="cursor-glow" />;
}

function Landing() {
  const revealRef = useScrollReveals();

  return (
    <div ref={revealRef} className="relative min-h-screen overflow-x-clip">
      <div className="hero-atmosphere pointer-events-none absolute inset-x-0 top-0 h-svh" />
      <CursorGlow />

      <nav className="relative z-10 mx-auto flex h-16 max-w-6xl items-center justify-between px-6">
        <Logo />
        <div className="flex items-center gap-5 sm:gap-6">
          <button
            type="button"
            onClick={scrollToSteps}
            className="hidden cursor-pointer text-sm text-muted-foreground transition-colors hover:text-foreground md:inline"
          >
            How it works
          </button>
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

      <section className="relative z-10 mx-auto grid min-h-[calc(100svh-4rem)] max-w-6xl items-center gap-14 px-6 pb-16 pt-8 lg:grid-cols-[minmax(0,0.92fr)_minmax(0,1.08fr)] lg:gap-12 lg:pb-20">
        <div className="hero-copy-enter">
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
            <button
              type="button"
              onClick={scrollToSteps}
              className="inline-flex cursor-pointer rounded-full border px-7 py-3 text-sm font-medium transition-colors hover:bg-card"
            >
              How it works
            </button>
          </div>
        </div>

        <div className="relative hero-preview-enter">
          <div className="absolute -inset-8 -z-10 rounded-[2.5rem] bg-primary/20 blur-3xl" />
          <div className="absolute -bottom-6 -right-2 -z-10 h-40 w-40 rounded-full bg-success/15 blur-3xl" />
          <div className="preview-float rounded-[1.85rem] border bg-card/60 p-2.5 sm:p-3">
            <ProductPreview />
          </div>
        </div>
      </section>

      <section
        aria-labelledby="onchain-title"
        className="relative z-10 mx-auto max-w-6xl px-6 pb-20"
      >
        <div className="relative overflow-hidden rounded-3xl border bg-card/55 p-6 sm:p-10">
          <div className="pointer-events-none absolute -right-20 -top-28 h-72 w-72 rounded-full bg-primary/15 blur-3xl" />
          <div className="relative grid items-center gap-10 lg:grid-cols-[1fr_0.9fr] lg:gap-16">
            <div data-reveal="left">
              <span className="inline-flex items-center gap-2 rounded-full border border-primary/25 bg-primary/10 px-3 py-1 text-[11px] font-medium tracking-wide text-primary">
                <span className="h-1.5 w-1.5 rounded-full bg-primary" />
                BUILT WITH SOLANA
              </span>
              <h2
                id="onchain-title"
                className="mt-5 max-w-lg text-3xl font-semibold leading-tight tracking-tight sm:text-4xl"
              >
                Keep the documents private.{" "}
                <span className="text-sol">Put the proof on-chain.</span>
              </h2>
              <p className="mt-4 max-w-lg text-sm leading-relaxed text-muted-foreground sm:text-base">
                When anchoring is enabled, shipment milestones and cryptographic fingerprints can be
                checked against Solana—helping reveal if agreed terms or evidence were changed
                later.
              </p>
              <div className="mt-6 inline-flex items-center gap-2 text-sm text-foreground/80">
                <ShieldCheck className="h-4 w-4 text-success" />
                Agreements and photos stay off-chain.
              </div>
            </div>

            <div
              aria-label="Illustration of agreement and evidence fingerprints anchored to Solana"
              className="relative rounded-2xl border bg-background/80 p-4 sm:p-5"
              data-reveal="right"
              style={{ animationDelay: "120ms" }}
            >
              <div className="mb-5 flex items-center justify-between gap-3">
                <div>
                  <p className="text-sm font-medium">Shipment proof</p>
                  <p className="mt-1 font-mono text-[10px] text-muted-foreground">
                    PS-1042 · illustrative
                  </p>
                </div>
                <span className="inline-flex items-center gap-1.5 rounded-full border border-success/30 bg-success/5 px-2.5 py-1 text-[10px] text-success">
                  <ShieldCheck className="h-3 w-3" />
                  VERIFIABLE
                </span>
              </div>
              <div className="relative">
                <div
                  className="relative flex items-center gap-3 rounded-xl border bg-card p-3"
                  data-reveal="up"
                  style={{ animationDelay: "100ms" }}
                >
                  <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg border border-primary/25 bg-primary/10 text-primary">
                    <FileCheck2 className="h-4 w-4" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-xs font-medium">Agreed terms</p>
                    <p className="mt-1 truncate font-mono text-[10px] text-muted-foreground">
                      SHA-256 · 8c2a…71f4
                    </p>
                  </div>
                  <ArrowUpRight className="h-3.5 w-3.5 text-muted-foreground" />
                </div>
                <div
                  aria-hidden="true"
                  className="ml-[28.5px] h-3 w-px bg-gradient-to-b from-primary/60 to-primary/30"
                />
                <div
                  className="relative flex items-center gap-3 rounded-xl border bg-card p-3"
                  data-reveal="up"
                  style={{ animationDelay: "220ms" }}
                >
                  <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg border border-primary/25 bg-primary/10 text-primary">
                    <Fingerprint className="h-4 w-4" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-xs font-medium">Evidence fingerprint</p>
                    <p className="mt-1 truncate font-mono text-[10px] text-muted-foreground">
                      SHA-256 · 14d9…a630
                    </p>
                  </div>
                  <ArrowUpRight className="h-3.5 w-3.5 text-muted-foreground" />
                </div>
                <div
                  aria-hidden="true"
                  className="ml-[28.5px] h-3 w-px bg-gradient-to-b from-primary/30 to-success/60"
                />
                <div
                  className="relative flex items-center gap-3 rounded-xl border border-success/25 bg-success/5 p-3"
                  data-reveal="up"
                  style={{ animationDelay: "340ms" }}
                >
                  <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg border border-success/25 bg-success/10 text-success">
                    <ShieldCheck className="h-4 w-4" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-xs font-medium">Solana audit record</p>
                    <p className="mt-1 text-[10px] text-muted-foreground">
                      Milestones ready for verification
                    </p>
                  </div>
                  <span className="rounded-full border border-success/25 px-2 py-0.5 text-[9px] text-success">
                    ON-CHAIN
                  </span>
                </div>
              </div>
              <p className="mt-4 text-center text-[10px] text-muted-foreground">
                Anchoring is optional and depends on deployment configuration.
              </p>
            </div>
          </div>
        </div>
      </section>

      <section
        id="how-it-works"
        aria-label="A clearer way to settle"
        className="relative z-10 mx-auto max-w-6xl scroll-mt-8 px-6 pb-20 pt-8"
      >
        <div className="rounded-3xl border bg-card/55 p-6 sm:p-8">
          <div className="mb-6">
            <p className="text-xs font-medium uppercase tracking-[0.16em] text-primary">
              Settlement without surprises
            </p>
            <h2 className="mt-2 text-xl font-semibold tracking-tight sm:text-2xl">
              Clarity for both sides.
            </h2>
          </div>
          <div className="grid gap-6 sm:grid-cols-3 sm:gap-4">
            <div
              className="flex items-start gap-3"
              data-reveal="left"
              style={{ animationDelay: "80ms" }}
            >
              <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl border border-primary/25 bg-primary/10 text-primary">
                <FileCheck2 className="h-4 w-4" />
              </span>
              <div>
                <h3 className="text-sm font-medium">Agree before shipping</h3>
                <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
                  Confirm terms and credit rules up front.
                </p>
              </div>
            </div>
            <div
              className="flex items-start gap-3"
              data-reveal="up"
              style={{ animationDelay: "180ms" }}
            >
              <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl border border-primary/25 bg-primary/10 text-primary">
                <ScanEye className="h-4 w-4" />
              </span>
              <div>
                <h3 className="text-sm font-medium">Keep evidence in view</h3>
                <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
                  Give both parties a shared, verifiable record.
                </p>
              </div>
            </div>
            <div
              className="flex items-start gap-3"
              data-reveal="right"
              style={{ animationDelay: "280ms" }}
            >
              <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl border border-success/25 bg-success/10 text-success">
                <Scale className="h-4 w-4" />
              </span>
              <div>
                <h3 className="text-sm font-medium">Settle by the rules</h3>
                <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
                  Adjustments follow the agreement, not an AI guess.
                </p>
              </div>
            </div>
          </div>
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
