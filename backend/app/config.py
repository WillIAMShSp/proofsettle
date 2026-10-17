from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PROOFSETTLE_", env_file=".env")

    # Any SQLAlchemy URL. SQLite for local dev and tests; for the demo, the Supabase
    # Postgres URL, e.g. postgresql+psycopg://user:pass@host:5432/postgres.
    database_url: str = "sqlite:///./proofsettle.db"
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
