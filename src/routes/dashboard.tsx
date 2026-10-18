import { createFileRoute, Link } from "@tanstack/react-router";
import { useState } from "react";
import { Chip, FrozenTag, Notice, PickRole, TopBar, useStore } from "@/lib/store";
import { isFrozen } from "@/lib/format";
import { ApiError } from "@/lib/api";
import { USE_MOCK, useDevReset, useShipments } from "@/lib/queries";
import { NewShipmentForm } from "@/components/NewShipmentForm";

export const Route = createFileRoute("/dashboard")({
  head: () => ({
    meta: [
      { title: "Shipments — ProofSettle" },
      { name: "description", content: "All shipments and their settlement status." },
      { property: "og:title", content: "Shipments — ProofSettle" },
      { property: "og:description", content: "Track shipments from agreement to settlement." },
    ],
  }),
  component: Dashboard,
});

function Dashboard() {
  const { role, hydrated } = useStore();
  const list = useShipments();
  const shipments = list.data ?? [];
  const [creating, setCreating] = useState(false);
  return (
    <div className="min-h-screen">
      <TopBar />
      <main className="mx-auto max-w-6xl px-6 py-16 fade-up">
        <div className="flex items-end justify-between gap-4">
          <div>
            <h1 className="text-4xl font-semibold tracking-tight">Shipments</h1>
            <p className="mt-2 text-muted-foreground">
              {list.data ? `${shipments.length} active agreements` : " "}
              {USE_MOCK && <span className="ml-2 text-xs">(offline demo data)</span>}
            </p>
          </div>
          <div className="flex items-start gap-3">
            {role === "Buyer" && !creating && (
              <button
                onClick={() => setCreating(true)}
                className="rounded-full bg-sol px-5 py-1.5 text-xs font-medium text-background hover:opacity-90"
              >
                New shipment
              </button>
            )}
            {role && <ResetDemo />}
          </div>
        </div>
        {role === "Buyer" && creating && (
          <div className="mt-10">
            <NewShipmentForm onCancel={() => setCreating(false)} />
          </div>
        )}
        <div className="mt-10 space-y-3">
          {hydrated && !role ? (
            <PickRole />
          ) : list.isError ? (
            <Notice tone="error">
              {list.error.message}{" "}
              <button onClick={() => list.refetch()} className="ml-2 text-primary">
                Retry
              </button>
            </Notice>
          ) : !list.data ? (
            <Notice>Loading shipments…</Notice>
          ) : !shipments.length ? (
            <Notice>No shipments yet.</Notice>
          ) : (
            shipments.map((s) => (
              <Link
                key={s.id}
                to="/shipments/$id"
                params={{ id: s.id }}
                className="card-surface flex items-center justify-between p-6"
              >
                <div>
                  <span className="font-mono text-xs text-muted-foreground">{s.id}</span>
                  <h3 className="mt-1 text-lg font-medium">{s.title}</h3>
                  <p className="text-sm text-muted-foreground">
                    {s.supplier} → {s.buyer}
                    {s.recipientEmail && <span> · shared with {s.recipientEmail}</span>}
                  </p>
                </div>
                <div className="flex items-center gap-6">
                  <span className="text-lg font-medium">${s.amount.toLocaleString()}</span>
                  <div className="flex items-center gap-2">
                    {isFrozen(s.status) && <FrozenTag />}
                    <Chip status={s.status} />
                  </div>
                </div>
              </Link>
            ))
          )}
        </div>
      </main>
    </div>
  );
}

// POST /dev/reset works only when the backend runs with PROOFSETTLE_DEV_MODE=true and
// answers 404 otherwise. There is no way to ask first without resetting, so the button
// hides itself after a 404 and stays hidden for the browser session.
const RESET_OFF_KEY = "ps-reset-unavailable";
const is404 = (e: unknown) => e instanceof ApiError && e.status === 404;

function ResetDemo() {
  const reset = useDevReset();
  // Only rendered once a role is known, i.e. in the browser, so sessionStorage exists here.
  const [unavailable, setUnavailable] = useState(
    () => sessionStorage.getItem(RESET_OFF_KEY) === "1",
  );
  if (unavailable) return null;
  const run = () => {
    if (!window.confirm("Reset all shipments to the demo seed?")) return;
    reset.mutate(undefined, {
      onError: (e) => {
        if (!is404(e)) return;
        sessionStorage.setItem(RESET_OFF_KEY, "1");
        setUnavailable(true);
      },
    });
  };
  return (
    <div className="text-right">
      <button
        onClick={run}
        disabled={reset.isPending}
        className="rounded-full border px-4 py-1.5 text-xs text-muted-foreground hover:border-primary/60 hover:text-foreground disabled:opacity-40"
      >
        {reset.isPending ? "Resetting…" : "Reset demo"}
      </button>
      {reset.isError && !is404(reset.error) && (
        <p className="mt-2 text-xs text-destructive">{reset.error.message}</p>
      )}
    </div>
  );
}
