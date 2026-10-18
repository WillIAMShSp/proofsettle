import type { User } from "@supabase/supabase-js";
import { isRole, type Role } from "./api";
import { isSupabaseConfigured, supabase } from "./supabase";

/** Signed-in ProofSettle account. The role comes from public.profiles, not from a header. */
export type AuthAccount = {
  id: string;
  email: string;
  name: string;
  role: Role;
};

export type SignUpResult =
  | { pendingConfirmation: true; message: string }
  | { pendingConfirmation: false; account: AuthAccount };

type PostgrestError = { message: string; code?: string };

function authErrorMessage(error: { message: string; code?: string | undefined }): string {
  const message = error.message || "Authentication failed";
  if (error.code === "email_provider_disabled" || /email signups are disabled/i.test(message)) {
    return (
      "Email signups are disabled on this Supabase project. Open Authentication → Sign In / Providers → Email, " +
      "turn on Enable Email provider, and save. Allow new users to sign up is a different switch and does not enable the provider."
    );
  }
  if (/invalid api key/i.test(message)) {
    return "Supabase rejected the API key. Set VITE_SUPABASE_PUBLISHABLE_KEY to the sb_publishable_ key and restart the dev server.";
  }
  return message;
}

function isRlsError(error: PostgrestError): boolean {
  return (
    error.code === "42501" ||
    /row-level security|permission denied|insufficient privilege/i.test(error.message)
  );
}

function profileReadError(error: PostgrestError): string {
  if (isRlsError(error)) {
    return (
      "public.profiles blocked reading this account. Row Level Security is on without a policy for the signed-in user. " +
      "Run supabase/auth.sql in the Supabase SQL editor, then sign in again."
    );
  }
  return error.message;
}

function profileWriteError(error: PostgrestError): string {
  if (isRlsError(error)) {
    return (
      "The Auth account exists, but public.profiles blocked the profile write. " +
      "Row Level Security on public.profiles is the usual cause. Run supabase/auth.sql in the Supabase SQL editor, then sign in again."
    );
  }
  return error.message;
}

function metadataRole(user: User): Role | null {
  const raw = user.user_metadata?.["role"];
  return typeof raw === "string" && isRole(raw) ? raw : null;
}

function metadataName(user: User, email: string): string {
  const raw = user.user_metadata?.["name"];
  if (typeof raw === "string" && raw.trim()) return raw.trim();
  const local = email.split("@")[0];
  return local || "User";
}

async function readOwnProfile(userId: string): Promise<{ name: string; role: string } | null> {
  const { data, error } = await supabase
    .from("profiles")
    .select("name, role")
    .eq("id", userId)
    .maybeSingle();
  if (error) throw new Error(profileReadError(error));
  if (!data) return null;
  return { name: String(data.name ?? ""), role: String(data.role ?? "") };
}

/**
 * Profile for this Auth user. An existing row wins, so a later metadata edit
 * cannot change the role. A missing row is created from sign-up metadata.
 */
export async function accountFromUser(user: User): Promise<AuthAccount> {
  const email = user.email ?? "";
  const existing = await readOwnProfile(user.id);
  if (existing) {
    if (!isRole(existing.role)) {
      throw new Error("This account's profile role must be Buyer, Supplier or Reviewer.");
    }
    return {
      id: user.id,
      email,
      name: existing.name || metadataName(user, email),
      role: existing.role,
    };
  }

  const role = metadataRole(user);
  if (!role) {
    throw new Error(
      "This account has no public.profiles row. Sign up from this page so name and role are stored, " +
        "or run supabase/auth.sql. An empty result is also what Row Level Security returns when a row exists but the signed-in user cannot see it.",
    );
  }
  const name = metadataName(user, email);
  const { error } = await supabase
    .from("profiles")
    .upsert({ id: user.id, name, email: email || null, role }, { onConflict: "id" });
  if (error) throw new Error(profileWriteError(error));
  return { id: user.id, email, name, role };
}

export async function signUp(input: {
  email: string;
  password: string;
  name: string;
  role: Role;
}): Promise<SignUpResult> {
  if (!isSupabaseConfigured) throw new Error("Supabase auth is not configured in this build.");
  const name = input.name.trim() || input.email.split("@")[0] || "User";
  const { data, error } = await supabase.auth.signUp({
    email: input.email,
    password: input.password,
    options: { data: { name, role: input.role } },
  });
  if (error) throw new Error(authErrorMessage(error));
  if (!data.user) throw new Error("No user returned from Supabase.");
  if (!data.session) {
    return {
      pendingConfirmation: true,
      message:
        "Account created. Check your email to confirm signup, then sign in. " +
        "Name and role are stored on the Auth user and written to public.profiles on that sign-in. " +
        "Running supabase/auth.sql writes the profile at signup, before the email is confirmed.",
    };
  }
  return { pendingConfirmation: false, account: await accountFromUser(data.user) };
}

export async function signIn(input: { email: string; password: string }): Promise<AuthAccount> {
  if (!isSupabaseConfigured) throw new Error("Supabase auth is not configured in this build.");
  const { data, error } = await supabase.auth.signInWithPassword({
    email: input.email,
    password: input.password,
  });
  if (error) throw new Error(authErrorMessage(error));
  if (!data.user) throw new Error("No user returned from Supabase.");
  return accountFromUser(data.user);
}

export async function restoreAccount(): Promise<AuthAccount | null> {
  if (!isSupabaseConfigured) return null;
  const { data, error } = await supabase.auth.getSession();
  if (error || !data.session?.user) return null;
  try {
    return await accountFromUser(data.session.user);
  } catch {
    return null;
  }
}

export function subscribeToAccount(onAccount: (account: AuthAccount | null) => void): () => void {
  if (!isSupabaseConfigured) return () => {};
  const { data } = supabase.auth.onAuthStateChange((event, session) => {
    if (event === "SIGNED_OUT" || !session?.user) {
      onAccount(null);
      return;
    }
    if (event === "INITIAL_SESSION" || event === "SIGNED_IN" || event === "USER_UPDATED") {
      void accountFromUser(session.user)
        .then(onAccount)
        .catch(() => onAccount(null));
    }
  });
  return () => data.subscription.unsubscribe();
}

export async function signOutAccount(): Promise<void> {
  if (isSupabaseConfigured) await supabase.auth.signOut();
}
