import { createFileRoute, Link } from "@tanstack/react-router";
import { Chip, TopBar, useStore } from "@/lib/store";

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
  const { shipments } = useStore();
  return (
    <div className="min-h-screen">
      <TopBar />
      <main className="mx-auto max-w-6xl px-6 py-16 fade-up">
        <h1 className="text-4xl font-semibold tracking-tight">Shipments</h1>
        <p className="mt-2 text-muted-foreground">{shipments.length} active agreements</p>
        <div className="mt-10 space-y-3">
          {shipments.map((s) => (
            <Link key={s.id} to="/shipments/$id" params={{ id: s.id }} className="card-surface flex items-center justify-between p-6">
              <div>
                <span className="font-mono text-xs text-muted-foreground">{s.id}</span>
                <h3 className="mt-1 text-lg font-medium">{s.title}</h3>
                <p className="text-sm text-muted-foreground">{s.supplier} → {s.buyer}</p>
              </div>
              <div className="flex items-center gap-6">
                <span className="text-lg font-medium">${s.amount.toLocaleString()}</span>
                <Chip status={s.status} />
              </div>
            </Link>
          ))}
        </div>
      </main>
    </div>
  );
}
