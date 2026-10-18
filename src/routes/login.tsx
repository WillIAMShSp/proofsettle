import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { Logo, useStore, type Role } from "@/lib/store";
import { useState } from "react";
import { supabase } from "@/integrations/supabase/client";

export const Route = createFileRoute("/login")({
  head: () => ({
    meta: [
      { title: "Sign in — ProofSettle" },
      { name: "description", content: "Sign in to ProofSettle using Supabase auth." },
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
  const [roleSelect, setRoleSelect] = useState<Role | "Demo">("Buyer");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  const continueDemo = (r: Role) => {
    setRole(r);
    nav({ to: "/dashboard" });
  };

  async function handleSignUp(e?: React.FormEvent) {
    e?.preventDefault();
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

      // Create or update profile row
      const profileRole = roleSelect === "Supplier" ? "supplier" : "buyer";
      const { error: upsertErr } = await supabase
        .from("profiles")
        .upsert({ id: user.id, name: name || null, role: profileRole })
        .select();
      if (upsertErr) {
        // Non-fatal: still allow sign in flow
        console.warn("Profile upsert failed:", upsertErr);
      }

      setInfo("Check your email to confirm signup, then sign in.");
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }

  async function handleSignIn(e?: React.FormEvent) {
    e?.preventDefault();
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

      // Ensure profile exists / upsert
      const profileRole = roleSelect === "Supplier" ? "supplier" : "buyer";
      const { error: upsertErr } = await supabase
        .from("profiles")
        .upsert({ id: user.id, name: name || null, role: profileRole })
        .select();
      if (upsertErr) {
        console.warn("Profile upsert failed:", upsertErr);
      }

      // Map stored profile role (lowercase) to UI Role
      const r: Role = roleSelect === "Supplier" ? "Supplier" : "Buyer";
      setRole(r);
      nav({ to: "/dashboard" });
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-6">
      <div className="card-surface w-full max-w-sm p-10 text-center fade-up">
        <div className="flex justify-center"><Logo /></div>
        <h1 className="mt-8 text-2xl font-semibold">Sign in to ProofSettle</h1>
        <p className="mt-2 text-sm text-muted-foreground">Use your email and password, or try the demo.</p>

        <form className="mt-6 space-y-3" onSubmit={handleSignIn}>
          <input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="Email" type="email" className="w-full rounded-md border px-3 py-2 text-sm" required />
          <input value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Password" type="password" className="w-full rounded-md border px-3 py-2 text-sm" required />
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Your name (optional)" type="text" className="w-full rounded-md border px-3 py-2 text-sm" />
          <div className="flex gap-2">
            <select value={roleSelect} onChange={(e) => setRoleSelect(e.target.value as Role | "Demo") as void} className="flex-1 rounded-md border px-3 py-2 text-sm">
              <option>Buyer</option>
              <option>Supplier</option>
            </select>
          </div>

          {error && <div className="text-sm text-destructive">{error}</div>}
          {info && <div className="text-sm text-muted-foreground">{info}</div>}

          <div className="mt-3 space-y-2">
            <button disabled={loading} type="submit" onClick={handleSignIn} className="w-full rounded-full bg-sol py-3 font-medium text-background hover:opacity-90">
              {loading ? "Signing in…" : "Sign in"}
            </button>
            <button disabled={loading} type="button" onClick={handleSignUp} className="w-full rounded-full border py-3 font-medium hover:border-primary/60">
              {loading ? "Working…" : "Sign up"}
            </button>
          </div>
        </form>

        <div className="mt-6 border-t pt-4">
          <p className="text-sm text-muted-foreground">Or open the demo</p>
          <div className="mt-3 space-y-2">
            <button onClick={() => continueDemo("Buyer") } className="w-full rounded-full bg-sol py-3 font-medium text-background hover:opacity-90">Continue as Buyer</button>
            <button onClick={() => continueDemo("Supplier") } className="w-full rounded-full border py-3 font-medium hover:border-primary/60">Continue as Supplier</button>
          </div>
        </div>
      </div>
    </div>
  );
}
