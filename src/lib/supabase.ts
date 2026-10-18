import { createClient } from "@supabase/supabase-js";

// Bracket access satisfies noPropertyAccessFromIndexSignature.
const env = import.meta.env;
const supabaseUrl = (env["VITE_SUPABASE_URL"] as string | undefined) || "";
const supabaseAnonKey =
  (env["VITE_SUPABASE_ANON_KEY"] as string | undefined) ||
  (env["VITE_SUPABASE_PUBLISHABLE_KEY"] as string | undefined) ||
  "";

export const isSupabaseConfigured = Boolean(
  supabaseUrl &&
  supabaseAnonKey &&
  supabaseUrl !== "https://your-project-id.supabase.co" &&
  !supabaseUrl.includes("placeholder"),
);

// Dummy client when credentials are absent so importing this module never throws.
export const supabase = isSupabaseConfigured
  ? createClient(supabaseUrl, supabaseAnonKey)
  : createClient("https://placeholder.supabase.co", "placeholder-key");

export type ProfileRow = { name: string; role: string };

/** The signed-in account's profile. Workflow rows are not read or written here. */
export async function fetchProfile(userId: string): Promise<ProfileRow | null> {
  const { data, error } = await supabase
    .from("profiles")
    .select("name, role")
    .eq("id", userId)
    .maybeSingle();
  if (error || !data) return null;
  return { name: String(data.name ?? ""), role: String(data.role ?? "") };
}
