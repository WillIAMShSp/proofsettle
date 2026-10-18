from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/config.py -> repository root, so `uv run` from backend/ still sees /.env.
_REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PROOFSETTLE_",
        env_file=(Path(".env"), Path("../.env"), _REPO_ROOT / ".env"),
        extra="ignore",
    )

    # Any SQLAlchemy URL. SQLite for local dev and tests; for the demo, the Supabase
    # Postgres URL, e.g. postgresql+psycopg://user:pass@host:5432/postgres.
    # On Postgres, workflow tables are created in the `proofsettle` schema, not `public`.
    database_url: str = "sqlite:///./proofsettle.db"
    # Used to verify access tokens (GET /auth/v1/user) and to read public.profiles
    # through PostgREST as that user. The workflow database is only a fallback.
    supabase_url: str = Field(
        default="",
        validation_alias=AliasChoices("PROOFSETTLE_SUPABASE_URL", "SUPABASE_URL", "VITE_SUPABASE_URL"),
    )
    supabase_anon_key: str = Field(
        default="",
        validation_alias=AliasChoices(
            "PROOFSETTLE_SUPABASE_ANON_KEY",
            # The sb_publishable_ key is the one Supabase currently accepts. The legacy
            # anon JWT in .env is rejected with "Invalid API key".
            "SUPABASE_PUBLISHABLE_KEY",
            "VITE_SUPABASE_PUBLISHABLE_KEY",
            "SUPABASE_ANON_KEY",
            "VITE_SUPABASE_ANON_KEY",
        ),
    )
    # Uploaded evidence files, named by evidence id.
    evidence_dir: Path = Path("./storage/evidence")
    # The frontend dev server: @lovable.dev/vite-tanstack-config pins it to port 8080.
    cors_origins: list[str] = ["http://localhost:8080", "http://127.0.0.1:8080", "http://[::1]:8080"]
    # Per uploaded evidence file, and files per upload request.
    max_evidence_bytes: int = 10 * 1024 * 1024
    max_evidence_files: int = 20
    # Enables POST /dev/reset, which drops every table and reloads the demo seed.
    dev_mode: bool = False


settings = Settings()
