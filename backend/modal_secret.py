"""Create or update the Modal secret the deployed backend reads its settings from.

    uv run python modal_secret.py --frontend https://your-frontend.example [--frontend ...]

Reads the settings exactly as the local backend does (backend/.env plus the root .env, via
app.config.Settings), and stores them in the Modal secret `proofsettle-backend`:

- Solana keypairs that are file paths here are stored as the keypair itself (its JSON
  array), since those files don't exist on Modal.
- PROOFSETTLE_CORS_ORIGINS becomes the given frontend address(es), plus localhost:8080 so a
  local frontend can use the deployed backend (leave out with --no-localhost).
- Development switches (dev mode, dev login) are never copied.

Values are never printed: they go to a temporary file, used once by `modal secret create`
and deleted. It refuses to run while the database is still the local SQLite file, since a
Modal container keeps nothing on disk.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from app.chain.program import load_keypair
from app.config import Settings

SECRET_NAME = "proofsettle-backend"
LOCAL_FRONTEND = ["http://localhost:8080", "http://127.0.0.1:8080"]


def keypair_value(raw: str) -> str:
    """The keypair as its JSON array (reading the file if `raw` is a path); checked to load."""
    text = raw.strip()
    if text and not text.startswith("["):
        text = Path(text).read_text(encoding="utf-8").strip()
    load_keypair(text)  # raises if it isn't a valid keypair
    return text


def build(settings: Settings, frontends: list[str], localhost: bool) -> dict[str, str]:
    if settings.database_url.startswith("sqlite"):
        sys.exit("PROOFSETTLE_DATABASE_URL is still the local SQLite file; set the Supabase Postgres URL first.")
    if not settings.supabase_secret_key:
        sys.exit("PROOFSETTLE_SUPABASE_SECRET_KEY is missing; photos must go to Supabase Storage on Modal.")
    if not settings.supabase_url or not settings.supabase_anon_key:
        sys.exit(
            "The Supabase URL and publishable key are missing (root .env SUPABASE_URL / SUPABASE_PUBLISHABLE_KEY)."
        )
    origins = [f.rstrip("/") for f in frontends] + (LOCAL_FRONTEND if localhost else [])
    if not origins:
        sys.exit("Give the deployed frontend's address with --frontend, or keep localhost.")

    env = {
        "PROOFSETTLE_DATABASE_URL": settings.database_url,
        "PROOFSETTLE_SUPABASE_URL": settings.supabase_url,
        "PROOFSETTLE_SUPABASE_ANON_KEY": settings.supabase_anon_key,
        "PROOFSETTLE_SUPABASE_SECRET_KEY": settings.supabase_secret_key,
        "PROOFSETTLE_EVIDENCE_BUCKET": settings.evidence_bucket,
        "PROOFSETTLE_CORS_ORIGINS": json.dumps(origins),
        "PROOFSETTLE_GEMINI_API_KEY": settings.gemini_api_key,
        "PROOFSETTLE_GEMINI_MODEL": settings.gemini_model,
        "PROOFSETTLE_GEMINI_TIMEOUT_S": str(settings.gemini_timeout_s),
    }
    if settings.solana_enabled:
        env |= {
            "PROOFSETTLE_SOLANA_RPC_URL": settings.solana_rpc_url,
            "PROOFSETTLE_SOLANA_BUYER_KEYPAIR": keypair_value(settings.solana_buyer_keypair),
            "PROOFSETTLE_SOLANA_SUPPLIER_KEYPAIR": keypair_value(settings.solana_supplier_keypair),
            "PROOFSETTLE_SOLANA_AUTHORITY_KEYPAIR": keypair_value(settings.solana_authority_keypair),
            "PROOFSETTLE_SOLANA_REVIEWER_KEYPAIR": keypair_value(settings.solana_reviewer_keypair),
            "PROOFSETTLE_SOLANA_SHIPMENT_SALT": settings.solana_shipment_salt,
            "PROOFSETTLE_SOLANA_EXPLORER_CLUSTER": settings.solana_explorer_cluster,
        }
        if settings.solana_program_id:
            env["PROOFSETTLE_SOLANA_PROGRAM_ID"] = settings.solana_program_id
    return {k: v for k, v in env.items() if v}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--frontend", action="append", default=[], help="deployed frontend origin (repeatable)")
    parser.add_argument("--no-localhost", action="store_true", help="don't also allow http://localhost:8080")
    parser.add_argument("--dry-run", action="store_true", help="only list the keys that would be stored")
    args = parser.parse_args()

    env = build(Settings(), args.frontend, not args.no_localhost)
    print(f"Secret {SECRET_NAME!r} with {len(env)} keys:")
    for key in sorted(env):
        print(f"  {key}")
    print(f"CORS origins: {', '.join(json.loads(env['PROOFSETTLE_CORS_ORIGINS']))}")
    if args.dry_run:
        return

    fd, path = tempfile.mkstemp(suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(env, f)
        cmd = ["uvx", "modal", "secret", "create", SECRET_NAME, "--from-json", path, "--force"]
        result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    finally:
        Path(path).unlink(missing_ok=True)
    if result.returncode != 0:
        sys.exit(f"modal secret create failed:\n{result.stderr or result.stdout}")
    print(f"Saved. Deploy with: uvx modal deploy {Path(__file__).with_name('modal_app.py').name}")


if __name__ == "__main__":
    main()
