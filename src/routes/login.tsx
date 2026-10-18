import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { Logo, useStore, type Role } from "@/lib/store";
import { supabase, isSupabaseConfigured } from "@/lib/supabase";

export const Route = createFileRoute("/login")({
  head: () => ({
    meta: [
      { title: "Sign in — ProofSettle" },
      { name: "description", content: "Sign in to ProofSettle using Supabase auth or instant demo roles." },
      { property: "og:title", content: "Sign in — ProofSettle" },
      { property: "og:description", content: "Continue as Buyer or Supplier." },
    ],
  }),
  component: Login,
});

function Login() {
  const { setRole } = useStore();
  const nav = useNavigate();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [roleSelect, setRoleSelect] = useState<Role>("Buyer");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  const continueDemo = (r: Role) => {
    setRole(r);
    nav({ to: "/dashboard" });
  };

  async function handleSignUp(e?: React.FormEvent) {
    e?.preventDefault();
    if (!isSupabaseConfigured) {
      continueDemo(roleSelect);
      return;
    }
    setError(null);
    setInfo(null);
    setLoading(true);
    try {
      const { data, error: signUpError } = await supabase.auth.signUp({ email, password });
      if (signUpError) {
        setError(signUpError.message ?? String(signUpError));
        setLoading(false);
        return;
      }
      const user = data.user;
      if (!user) {
        setError("No user returned from Supabase.");
        setLoading(false);
        return;
      }

      // Upsert profile
      const { error: upsertErr } = await supabase
        .from("profiles")
        .upsert({
          id: user.id,
          name: name || email.split("@")[0],
          role: roleSelect,
        });

      if (upsertErr) {
        console.warn("Profile upsert warning:", upsertErr);
      }

      setInfo("Account created. Check your email to confirm signup, or sign in now.");
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }

  async function handleSignIn(e?: React.FormEvent) {
    e?.preventDefault();
    if (!isSupabaseConfigured) {
      continueDemo(roleSelect);
      return;
    }
    setError(null);
    setInfo(null);
    setLoading(true);
    try {
      const { data, error: signInError } = await supabase.auth.signInWithPassword({ email, password });
      if (signInError) {
        setError(signInError.message ?? String(signInError));
        setLoading(false);
        return;
      }
      const user = data.user;
      if (!user) {
        setError("No user returned from Supabase.");
        setLoading(false);
        return;
      }

      // Read profile role if available
      const { data: profile } = await supabase
        .from("profiles")
        .select("role")
        .eq("id", user.id)
        .maybeSingle();

      const userRole = (profile?.role === "Supplier" ? "Supplier" : "Buyer") as Role;
      setRole(userRole);
      nav({ to: "/dashboard" });
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-6 py-12">
      <div className="card-surface w-full max-w-sm p-8 text-center fade-up">
        <div className="flex justify-center">
          <Logo />
        </div>
        <h1 className="mt-6 text-2xl font-semibold tracking-tight">Access ProofSettle</h1>
        <p className="mt-1 text-xs text-muted-foreground">
          {isSupabaseConfigured ? "Sign in with your credentials or launch an instant demo." : "Choose your demo role to explore the workflow."}
        </p>

        {isSupabaseConfigured && (
          <form className="mt-6 space-y-3 text-left" onSubmit={handleSignIn}>
            <div>
              <label className="text-[11px] font-medium text-muted-foreground">Email</label>
              <input
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="name@company.com"
                type="email"
                className="mt-1 w-full rounded-lg border bg-background/50 px-3 py-2 text-sm outline-none focus:border-primary/60"
                required
              />
            </div>
            <div>
              <label className="text-[11px] font-medium text-muted-foreground">Password</label>
              <input
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                type="password"
                className="mt-1 w-full rounded-lg border bg-background/50 px-3 py-2 text-sm outline-none focus:border-primary/60"
                required
              />
            </div>
            <div>
              <label className="text-[11px] font-medium text-muted-foreground">Role</label>
              <select
                value={roleSelect}
                onChange={(e) => setRoleSelect(e.target.value as Role)}
                className="mt-1 w-full rounded-lg border bg-background/50 px-3 py-2 text-sm outline-none focus:border-primary/60"
              >
                <option value="Buyer">Buyer (Northgate Assembly)</option>
                <option value="Supplier">Supplier (Ferro Precision)</option>
              </select>
            </div>

            {error && <p className="text-xs text-destructive">{error}</p>}
            {info && <p className="text-xs text-success">{info}</p>}

            <div className="pt-2 space-y-2">
              <button
                disabled={loading}
                type="submit"
                className="w-full rounded-full bg-sol py-2.5 text-sm font-medium text-background transition hover:opacity-90 disabled:opacity-50"
              >
                {loading ? "Authenticating…" : "Sign In with Supabase"}
              </button>
              <button
                disabled={loading}
                type="button"
                onClick={handleSignUp}
                className="w-full rounded-full border py-2.5 text-sm font-medium transition hover:border-primary/60 disabled:opacity-50"
              >
                Create Account
              </button>
            </div>
          </form>
        )}

        <div className={`mt-6 ${isSupabaseConfigured ? "border-t pt-5" : ""}`}>
          <p className="text-xs text-muted-foreground font-medium mb-3">
            {isSupabaseConfigured ? "Or open instant demo role" : "Pick a side of the transaction"}
          </p>
          <div className="space-y-2.5">
            <button
              type="button"
              onClick={() => continueDemo("Buyer")}
              className="w-full rounded-full bg-sol py-3 font-medium text-background hover:opacity-90 transition text-sm"
            >
              Continue as Buyer
            </button>
            <button
              type="button"
              onClick={() => continueDemo("Supplier")}
              className="w-full rounded-full border py-3 font-medium hover:border-primary/60 transition text-sm"
            >
              Continue as Supplier
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
