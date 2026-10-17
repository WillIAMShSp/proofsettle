/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** FastAPI base URL; defaults to http://127.0.0.1:8000. */
  readonly VITE_API_URL?: string;
  /** "true" runs the app on the in-browser mock instead of the API. */
  readonly VITE_USE_MOCK?: string;
}
