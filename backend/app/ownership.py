"""Give shipments with no owner account to one: uv run python -m app.ownership <user-id>

Shipments belong to accounts (app.access). The demo seed and shipments created before
ownership existed have no `created_by`, so no account sees them. This assigns every such
shipment to the given Supabase user id (Supabase dashboard -> Authentication -> Users) and
leaves owned shipments alone. Without an id it only lists the ownerless shipments.
"""

import argparse
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Shipment


def ownerless(db: Session) -> list[Shipment]:
    return list(db.scalars(select(Shipment).where(Shipment.created_by.is_(None)).order_by(Shipment.id)))


def assign_ownerless(db: Session, user_id: str) -> list[str]:
    """Give every shipment without an owner to `user_id`; returns their ids. Commits."""
    UUID(user_id)  # ValueError for anything but a Supabase user id
    shipments = ownerless(db)
    for s in shipments:
        s.created_by = user_id
    db.commit()
    return [s.id for s in shipments]


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.ownership", description=__doc__.splitlines()[0])
    parser.add_argument("user_id", nargs="?", help="Supabase user id to own them; omit to only list")
    args = parser.parse_args()
    if args.user_id is not None:
        try:
            UUID(args.user_id)
        except ValueError:
            parser.error(f"{args.user_id!r} is not a Supabase user id (a UUID)")

    with SessionLocal() as db:
        shipments = ownerless(db)
        if not shipments:
            print("Every shipment has an owner.")
            return
        for s in shipments:
            print(f"{s.id}  {s.title}")
        if args.user_id is None:
            print(f"{len(shipments)} without an owner. Pass a user id to assign them.")
            return
        print(f"Assigned {len(assign_ownerless(db, args.user_id))} to {args.user_id}.")


if __name__ == "__main__":
    main()
