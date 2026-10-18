import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { DEV_AUTH, USE_MOCK, isRole, type Role } from "@/lib/api";
import { Logo, useStore } from "@/lib/store";
import { fetchProfile, isSupabaseConfigured, supabase } from "@/lib/supabase";

export const Route = createFileRoute("/login")({
  head: () => ({
    meta: [
      { title: "Sign in — ProofSettle" },
      { name: "description", content: "Sign in to ProofSettle with your Supabase account." },
      { property: "og:title", content: "Sign in — ProofSettle" },
      { property: "og:description", content: "Continue as Buyer, Supplier or Reviewer." },
    ],
  }),
  component: Login,
});

const ROLES: Role[] = ["Buyer", "Supplier", "Reviewer"];

function Login() {
  const { setUser } = useStore();
  const nav = useNavigate();
  const [mode, setMode] = useState<"sign-in" | "sign-up">("sign-in");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [roleSelect, setRoleSelect] = useState<Role>("Buyer");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  const continueDemo = (role: Role) => {
    setUser({ id: `demo-${role}`, email: "", name: role, role });
    nav({ to: "/dashboard" });
  };

  async function handleSignUp(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setInfo(null);
    setLoading(true);
    try {
      const { data, error: signUpError } = await supabase.auth.signUp({ email, password });
      if (signUpError) {
        setError(signUpError.message);
        return;
      }
      const user = data.user;
      if (!user) {
        setError("No user returned from Supabase.");
        return;
      }
      const displayName = name.trim() || email.split("@")[0] || "User";
      const { error: upsertErr } = await supabase.from("profiles").upsert({
        id: user.id,
        name: displayName,
        role: roleSelect,
      });
      if (upsertErr) {
        setError(upsertErr.message);
        return;
      }
      if (!data.session) {
        setInfo("Account created. Check your email to confirm signup, then sign in.");
        setMode("sign-in");
        return;
      }
      setUser({ id: user.id, email: user.email ?? email, name: displayName, role: roleSelect });
      nav({ to: "/dashboard" });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  async function handleSignIn(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setInfo(null);
    setLoading(true);
    try {
      const { data, error: signInError } = await supabase.auth.signInWithPassword({
        email,
        password,
      });
      if (signInError) {
        setError(signInError.message);
        return;
      }
      const user = data.user;
      if (!user) {
        setError("No user returned from Supabase.");
        return;
      }
      const profile = await fetchProfile(user.id);
      if (!profile || !isRole(profile.role)) {
        setError("This account needs a Buyer, Supplier or Reviewer profile.");
        return;
      }
      setUser({
        id: user.id,
        email: user.email ?? email,
        name: profile.name || email,
        role: profile.role,
      });
      nav({ to: "/dashboard" });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
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
          {isSupabaseConfigured
            ? "Sign in with the email on your ProofSettle profile."
            : "Supabase auth is not configured in this build."}
        </p>

        {isSupabaseConfigured && (
          <form
            className="mt-6 space-y-3 text-left"
            onSubmit={mode === "sign-in" ? handleSignIn : handleSignUp}
          >
            {mode === "sign-up" && (
              <>
                <div>
                  <label className="text-[11px] font-medium text-muted-foreground">Name</label>
                  <input
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="Alex Vance"
                    className="mt-1 w-full rounded-lg border bg-background/50 px-3 py-2 text-sm outline-none focus:border-primary/60"
                  />
                </div>
                <div>
                  <label className="text-[11px] font-medium text-muted-foreground">Role</label>
                  <select
                    value={roleSelect}
                    onChange={(e) => setRoleSelect(e.target.value as Role)}
                    className="mt-1 w-full rounded-lg border bg-background/50 px-3 py-2 text-sm outline-none focus:border-primary/60"
                  >
                    {ROLES.map((role) => (
                      <option key={role} value={role}>
                        {role}
                      </option>
                    ))}
                  </select>
                </div>
              </>
            )}
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

            {error && <p className="text-xs text-destructive">{error}</p>}
            {info && <p className="text-xs text-success">{info}</p>}

            <div className="space-y-2 pt-2">
              <button
                disabled={loading}
                type="submit"
                className="w-full rounded-full bg-sol py-2.5 text-sm font-medium text-background transition hover:opacity-90 disabled:opacity-50"
              >
                {loading ? "Authenticating…" : mode === "sign-in" ? "Sign in" : "Create account"}
              </button>
              <button
                disabled={loading}
                type="button"
                onClick={() => {
                  setMode(mode === "sign-in" ? "sign-up" : "sign-in");
                  setError(null);
                  setInfo(null);
                }}
                className="w-full rounded-full border py-2.5 text-sm font-medium transition hover:border-primary/60 disabled:opacity-50"
              >
                {mode === "sign-in" ? "Create account" : "Have an account? Sign in"}
              </button>
            </div>
          </form>
        )}

        {(USE_MOCK || DEV_AUTH) && (
          <div className={`mt-6 ${isSupabaseConfigured ? "border-t pt-5" : ""}`}>
            <p className="mb-3 text-xs font-medium text-muted-foreground">
              {USE_MOCK ? "Offline demo" : "Local dev login (live API)"}
            </p>
            <div className="space-y-2.5">
              {ROLES.map((role) => (
                <button
                  key={role}
                  type="button"
                  onClick={() => continueDemo(role)}
                  className="w-full rounded-full border py-3 text-sm font-medium transition hover:border-primary/60"
                >
                  Continue as {role}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
