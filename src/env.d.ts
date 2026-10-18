/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** FastAPI base URL; defaults to http://127.0.0.1:8000. */
  readonly VITE_API_URL?: string;
  /** "true" runs the app on the in-browser mock instead of the API. */
  readonly VITE_USE_MOCK?: string;
  /** "true" signs in by role against a backend run with PROOFSETTLE_DEV_AUTH=true. */
  readonly VITE_DEV_AUTH?: string;
  readonly VITE_SUPABASE_URL?: string;
  readonly VITE_SUPABASE_ANON_KEY?: string;
  readonly VITE_SUPABASE_PUBLISHABLE_KEY?: string;
}
