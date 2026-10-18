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
    # Used only to verify access tokens (GET /auth/v1/user). The role is then read from
    # public.profiles with the database connection, not from a request header.
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
    # Local dev only: accept `X-Dev-Role: Buyer|Supplier|Reviewer` in place of a Supabase
    # session, for when Supabase sign-up is unavailable. Lets any caller act as any role.
    dev_auth: bool = False

    # --- Solana anchoring (app/chain). Off unless the RPC URL and all four keypairs are set.
    # JSON-RPC endpoint, e.g. https://api.devnet.solana.com or http://127.0.0.1:8899.
    solana_rpc_url: str = ""
    # Defaults to the address in app/chain/proofsettle.json (the IDL `anchor build` wrote).
    solana_program_id: str = ""
    # Demo keys the backend signs with (custodial, see CHAIN_ALIGNMENT.md §5). Each is a path
    # to a Solana keypair file, or the keypair's JSON array itself. Never sent to clients.
    solana_buyer_keypair: str = ""
    solana_supplier_keypair: str = ""
    solana_authority_keypair: str = ""
    solana_reviewer_keypair: str = ""
    # Mixed into each shipment's PDA seed. Change it after POST /dev/reset so the reseeded
    # shipments get fresh on-chain accounts instead of an earlier run's.
    solana_shipment_salt: str = ""
    # Explorer `cluster` query for links in the UI: devnet, or for a local validator
    # "custom&customUrl=http://127.0.0.1:8899".
    solana_explorer_cluster: str = "devnet"

    @property
    def solana_enabled(self) -> bool:
        keys = (
            self.solana_buyer_keypair,
            self.solana_supplier_keypair,
            self.solana_authority_keypair,
            self.solana_reviewer_keypair,
        )
        return bool(self.solana_rpc_url) and all(keys)


settings = Settings()
