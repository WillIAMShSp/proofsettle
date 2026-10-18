"""Copy this machine's data into Supabase: uv run python -m app.migrate

Source: the local SQLite database and evidence folder the backend used before (by default
sqlite:///./proofsettle.db and ./storage/evidence). Target: the configured database, which
must be Postgres (PROOFSETTLE_DATABASE_URL, Supabase), and the configured evidence store,
which must be Supabase Storage (PROOFSETTLE_SUPABASE_SECRET_KEY).

Everything is copied as is: same ids, same audit chains, same photo bytes. That keeps every
"Verify hashes" check and every Solana record matching. Steps:

1. Check, before writing anything: the target has no shipments yet, and every local photo
   is present and still matches the SHA-256 recorded for it.
2. Make the bucket (private) if needed and upload the photos. A photo already in the bucket
   with the same bytes is left alone, so a failed run can simply be run again.
3. Copy every table's rows in one transaction, then move Postgres's id counters past the
   copied ids so new audit events and messages don't collide with them.
4. Verify: row counts per table, every photo re-downloaded and re-hashed, every shipment's
   audit chain re-checked.

The local database and folder are only read, never changed.
"""

import argparse
import sys
from pathlib import Path

from sqlalchemy import Engine, Integer, func, select, text
from sqlalchemy.orm import Session

from app.audit import verify_chain
from app.config import settings
from app.db import POSTGRES_SCHEMA, Base, create_tables, make_engine
from app.hashing import sha256_hex
from app.models import Evidence, Shipment
from app.storage import EvidenceStore, LocalStore, StorageError, SupabaseStore, default_store


class MigrationError(Exception):
    """Refused or failed; the message says why."""


def _tables():
    import app.models  # noqa: F401  (registers the tables)

    return Base.metadata.sorted_tables  # parents before children (foreign keys)


def _counts(engine: Engine) -> dict[str, int]:
    with engine.connect() as conn:
        return {t.name: conn.scalar(select(func.count()).select_from(t)) or 0 for t in _tables()}


def check_photos(source_engine: Engine, source_photos: EvidenceStore) -> list[tuple[str, str, bytes]]:
    """(file name, content type, bytes) for every evidence row, each matching its SHA-256."""
    photos, problems = [], []
    with Session(source_engine) as db:
        for ev in db.scalars(select(Evidence).order_by(Evidence.id)):
            data = source_photos.get(ev.file_name)
            if data is None:
                problems.append(f"{ev.id}: {ev.file_name} is missing")
            elif sha256_hex(data) != ev.sha256:
                problems.append(f"{ev.id}: {ev.file_name} no longer matches its recorded SHA-256")
            else:
                photos.append((ev.file_name, ev.content_type, data))
    if problems:
        raise MigrationError("Local photos don't match the database:\n  " + "\n  ".join(problems))
    return photos


def upload_photos(photos: list[tuple[str, str, bytes]], target: EvidenceStore) -> int:
    """Upload each photo; one already there must have the same bytes. Returns how many uploaded."""
    uploaded = 0
    for name, content_type, data in photos:
        existing = target.get(name)
        if existing is None:
            target.put(name, data, content_type)
            uploaded += 1
        elif sha256_hex(existing) != sha256_hex(data):
            raise MigrationError(f"The bucket already has a different {name}; refusing to overwrite it")
    return uploaded


def copy_rows(source_engine: Engine, target_engine: Engine) -> dict[str, int]:
    """Copy every table in one target transaction. Returns rows copied per table."""
    copied: dict[str, int] = {}
    with source_engine.connect() as src, target_engine.begin() as dst:
        for table in _tables():
            rows = [dict(r) for r in src.execute(select(table)).mappings()]
            if rows:
                dst.execute(table.insert(), rows)
            copied[table.name] = len(rows)
        if dst.dialect.name == "postgresql":
            for table in _tables():
                pk = list(table.primary_key.columns)
                if len(pk) == 1 and isinstance(pk[0].type, Integer) and copied[table.name]:
                    # Serial ids: the next new row must come after the copied ones.
                    qualified = f"{POSTGRES_SCHEMA}.{table.name}"
                    dst.execute(
                        text(
                            f"SELECT setval(pg_get_serial_sequence(:t, :c), (SELECT max({pk[0].name}) FROM {qualified}))"
                        ),
                        {"t": qualified, "c": pk[0].name},
                    )
    return copied


def verify(source_counts: dict[str, int], target_engine: Engine, photos, target: EvidenceStore) -> list[str]:
    """Problems found in the copy (empty when it's exact)."""
    problems = []
    target_counts = _counts(target_engine)
    for name, n in source_counts.items():
        if target_counts.get(name) != n:
            problems.append(f"table {name}: {n} rows locally, {target_counts.get(name)} in Supabase")
    for name, _, data in photos:
        stored = target.get(name)
        if stored is None or sha256_hex(stored) != sha256_hex(data):
            problems.append(f"photo {name} is missing or different in the bucket")
    with Session(target_engine) as db:
        for s in db.scalars(select(Shipment).order_by(Shipment.id)):
            if not verify_chain(db, s).verified:
                problems.append(f"{s.id}: audit chain does not verify in Supabase")
    return problems


def migrate(source_engine: Engine, source_photos: EvidenceStore, target_engine: Engine, target: EvidenceStore) -> str:
    source_counts = _counts(source_engine)
    create_tables(target_engine)
    if _counts(target_engine)[Shipment.__tablename__]:
        raise MigrationError("Supabase already has shipments; refusing to copy over them")
    photos = check_photos(source_engine, source_photos)
    if isinstance(target, SupabaseStore):
        target.ensure_bucket()
    uploaded = upload_photos(photos, target)
    copied = copy_rows(source_engine, target_engine)
    problems = verify(source_counts, target_engine, photos, target)
    if problems:
        raise MigrationError("Copied, but the check found problems:\n  " + "\n  ".join(problems))
    rows = ", ".join(f"{n} {t}" for t, n in copied.items() if n)
    return (
        f"Copied {rows}; uploaded {uploaded} of {len(photos)} photos. Every count, photo hash and audit chain matches."
    )


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.migrate", description=__doc__.splitlines()[0])
    parser.add_argument("--source", default="sqlite:///./proofsettle.db", help="local database URL")
    parser.add_argument("--source-photos", type=Path, default=settings.evidence_dir, help="local photo folder")
    args = parser.parse_args()

    target_engine = make_engine(settings.database_url)
    target = default_store()
    if target_engine.dialect.name != "postgresql":
        sys.exit("PROOFSETTLE_DATABASE_URL must be the Supabase Postgres URL (it is still the local database).")
    if not isinstance(target, SupabaseStore):
        sys.exit("PROOFSETTLE_SUPABASE_SECRET_KEY must be set, so photos go to Supabase Storage.")
    source_engine = make_engine(args.source)
    if not Path(source_engine.url.database or "").is_file():
        sys.exit(f"No local database at {args.source}")

    print(f"From  {args.source} + {args.source_photos.resolve()}")
    print(f"To    {target_engine.url.render_as_string(hide_password=True)} + bucket {target.bucket!r}")
    try:
        print(migrate(source_engine, LocalStore(args.source_photos), target_engine, target))
    except (MigrationError, StorageError) as e:
        sys.exit(f"Stopped: {e}")


if __name__ == "__main__":
    main()
