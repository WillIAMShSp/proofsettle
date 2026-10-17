import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { Logo, useStore, type Role } from "@/lib/store";

export const Route = createFileRoute("/login")({
  head: () => ({
    meta: [
      { title: "Sign in — ProofSettle" },
      { name: "description", content: "Choose a demo role to explore ProofSettle." },
      { property: "og:title", content: "Sign in — ProofSettle" },
      { property: "og:description", content: "Continue as Buyer, Supplier or Reviewer." },
    ],
  }),
  component: Login,
});

function Login() {
  const { setRole } = useStore();
  const nav = useNavigate();
  const go = (r: Role) => {
    setRole(r);
    nav({ to: "/dashboard" });
  };
  return (
    <div className="flex min-h-screen items-center justify-center px-6">
      <div className="card-surface w-full max-w-sm p-10 text-center fade-up">
        <div className="flex justify-center">
          <Logo />
        </div>
        <h1 className="mt-8 text-2xl font-semibold">Open the demo</h1>
        <p className="mt-2 text-sm text-muted-foreground">Pick a side of the deal.</p>
        <div className="mt-8 space-y-3">
          <button
            onClick={() => go("Buyer")}
            className="w-full rounded-full bg-sol py-3 font-medium text-background hover:opacity-90"
          >
            Continue as Buyer
          </button>
          <button
            onClick={() => go("Supplier")}
            className="w-full rounded-full border py-3 font-medium hover:border-primary/60"
          >
            Continue as Supplier
          </button>
          <button
            onClick={() => go("Reviewer")}
            className="w-full rounded-full py-2 text-sm text-muted-foreground hover:text-foreground"
          >
            Continue as Reviewer
          </button>
        </div>
      </div>
    </div>
  );
}
