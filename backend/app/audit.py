"""Per-shipment audit trail as a hash chain.

    payloadHash = sha256(canonical_json(payload))
    eventHash   = sha256(canonical_json({
        "shipmentId", "seq", "at", "actor", "type", "text", "payloadHash", "prevEventHash"
    }))

`at` is ISO 8601 UTC with a "Z" suffix, and prevEventHash is the previous event's eventHash
(null for seq 1). Editing any stored field, or deleting, inserting or reordering events,
changes a recomputed hash or breaks a link, which verify_chain reports per event.
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, object_session

from app.hashing import canonical_json, hash_json, jsonable
from app.models import AuditEvent, ChainStatus, Shipment
from app.schemas import CamelModel
from app.workflow import Actor


class EventType(StrEnum):
    AGREEMENT_DRAFTED = "agreement.drafted"
    AGREEMENT_APPROVED = "agreement.approved"
    EVIDENCE_UPLOADED = "evidence.uploaded"
    STATUS_CHANGED = "shipment.status_changed"
    INSPECTION_COMPLETED = "inspection.completed"
    ADJUSTMENT_PROPOSED = "adjustment.proposed"
    ADJUSTMENT_ACCEPTED = "adjustment.accepted"
    ADJUSTMENT_DISPUTED = "adjustment.disputed"
    FINDING_REVIEWED = "finding.reviewed"
    DISPUTE_RESOLVED = "dispute.resolved"


def iso_utc(at: datetime) -> str:
    """2026-10-09T10:12:00Z (microseconds only when non-zero)."""
    return at.astimezone(UTC).isoformat().replace("+00:00", "Z")


def event_hash(
    *,
    shipment_id: str,
    seq: int,
    at: datetime,
    actor: Actor,
    type: str,
    text: str,
    payload_hash: str,
    prev_event_hash: str | None,
) -> str:
    return hash_json(
        {
            "shipmentId": shipment_id,
            "seq": seq,
            "at": iso_utc(at),
            "actor": actor.value,
            "type": type,
            "text": text,
            "payloadHash": payload_hash,
            "prevEventHash": prev_event_hash,
        }
    )


def append_event(
    shipment: Shipment,
    type: EventType,
    actor: Actor,
    payload: dict[str, Any],
    *,
    text: str,
    at: datetime | None = None,
) -> AuditEvent:
    """Add the next event to `shipment`'s chain, in the shipment's session, and flush it.

    `payload` must be JSON-safe once models are dumped (money as numbers, times as ISO
    strings); it is stored as given and hashed with canonical_json.
    """
    db = object_session(shipment)
    if db is None:
        raise ValueError("shipment must belong to a session")
    at = at or datetime.now(UTC)
    payload = jsonable(payload)
    canonical_json(payload)  # fail now on anything that can't be hashed

    last = _last_event(db, shipment.id)
    seq = last.seq + 1 if last else 1
    prev = last.event_hash if last else None
    payload_hash = hash_json(payload)

    event = AuditEvent(
        shipment_id=shipment.id,
        seq=seq,
        at=at,
        actor=actor,
        type=type.value,
        text=text,
        payload=payload,
        payload_hash=payload_hash,
        prev_event_hash=prev,
        event_hash=event_hash(
            shipment_id=shipment.id,
            seq=seq,
            at=at,
            actor=actor,
            type=type.value,
            text=text,
            payload_hash=payload_hash,
            prev_event_hash=prev,
        ),
        chain_status=ChainStatus.SKIPPED,  # no chain anchoring yet
    )
    db.add(event)
    db.flush()
    return event


def _last_event(db: Session, shipment_id: str) -> AuditEvent | None:
    return db.scalars(
        select(AuditEvent).where(AuditEvent.shipment_id == shipment_id).order_by(AuditEvent.seq.desc()).limit(1)
    ).first()


class EventCheck(CamelModel):
    id: str
    seq: int
    stored_hash: str
    recomputed_hash: str
    payload_ok: bool  # payloadHash matches the stored payload
    link_ok: bool  # seq follows on and prevEventHash is the previous event's stored eventHash
    ok: bool


class ChainVerification(CamelModel):
    shipment_id: str
    verified: bool
    checked: int
    events: tuple[EventCheck, ...]


def verify_chain(db: Session, shipment: Shipment) -> ChainVerification:
    """Recompute every event's hashes from its stored fields and check the links."""
    events = db.scalars(select(AuditEvent).where(AuditEvent.shipment_id == shipment.id).order_by(AuditEvent.seq)).all()
    checks: list[EventCheck] = []
    prev: AuditEvent | None = None
    for e in events:
        recomputed_payload = hash_json(e.payload)
        recomputed = event_hash(
            shipment_id=shipment.id,
            seq=e.seq,
            at=e.at,
            actor=e.actor,
            type=e.type,
            text=e.text,
            payload_hash=recomputed_payload,
            prev_event_hash=e.prev_event_hash,
        )
        payload_ok = recomputed_payload == e.payload_hash
        link_ok = e.seq == (prev.seq + 1 if prev else 1) and e.prev_event_hash == (prev.event_hash if prev else None)
        checks.append(
            EventCheck(
                id=e.public_id,
                seq=e.seq,
                stored_hash=e.event_hash,
                recomputed_hash=recomputed,
                payload_ok=payload_ok,
                link_ok=link_ok,
                ok=payload_ok and link_ok and recomputed == e.event_hash,
            )
        )
        prev = e
    return ChainVerification(
        shipment_id=shipment.id,
        verified=all(c.ok for c in checks),
        checked=len(checks),
        events=tuple(checks),
    )
