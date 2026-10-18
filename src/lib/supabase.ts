import { createClient } from "@supabase/supabase-js";

// Bracket access satisfies noPropertyAccessFromIndexSignature.
const env = import.meta.env;
const supabaseUrl = (env["VITE_SUPABASE_URL"] as string | undefined) || "";

// Lovable writes the current key as VITE_SUPABASE_PUBLISHABLE_KEY (sb_publishable_…).
// VITE_SUPABASE_ANON_KEY is the older JWT. This project’s JWT is rejected by Supabase
// ("Invalid API key"), so the publishable key wins when both are set.
const supabaseKey =
  (env["VITE_SUPABASE_PUBLISHABLE_KEY"] as string | undefined) ||
  (env["VITE_SUPABASE_ANON_KEY"] as string | undefined) ||
  "";

export const isSupabaseConfigured = Boolean(
  supabaseUrl &&
  supabaseKey &&
  supabaseUrl !== "https://your-project-id.supabase.co" &&
  !supabaseUrl.includes("placeholder"),
);

function isNewSupabaseApiKey(value: string): boolean {
  return value.startsWith("sb_publishable_") || value.startsWith("sb_secret_");
}

// sb_publishable_ keys are not JWTs. supabase-js sends them as Authorization: Bearer,
// and Supabase then answers "Invalid API key". Send them only as the apikey header.
function createSupabaseFetch(key: string): typeof fetch {
  return (input, init) => {
    const headers = new Headers(
      typeof Request !== "undefined" && input instanceof Request ? input.headers : undefined,
    );
    if (init?.headers) {
      new Headers(init.headers).forEach((value, name) => headers.set(name, value));
    }
    if (isNewSupabaseApiKey(key) && headers.get("Authorization") === `Bearer ${key}`) {
      headers.delete("Authorization");
    }
    headers.set("apikey", key);
    return fetch(input, { ...init, headers });
  };
}

// Dummy client when credentials are absent so importing this module never throws.
export const supabase = isSupabaseConfigured
  ? createClient(supabaseUrl, supabaseKey, {
      global: { fetch: createSupabaseFetch(supabaseKey) },
      auth: { persistSession: true, autoRefreshToken: true },
    })
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
