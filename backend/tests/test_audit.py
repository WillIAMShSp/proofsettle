import itertools
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.audit import EventType, append_event, event_hash, verify_chain
from app.hashing import hash_json
from app.models import AuditEvent, Shipment
from app.workflow import Actor

SEEDED = {"PS-1042": 7, "PS-1038": 4, "PS-1031": 11}


def shipment(db: Session, id: str = "PS-1042") -> Shipment:
    s = db.get(Shipment, id)
    assert s is not None
    return s


def event(db: Session, seq: int, id: str = "PS-1042") -> AuditEvent:
    return db.scalars(select(AuditEvent).where(AuditEvent.shipment_id == id, AuditEvent.seq == seq)).one()


@pytest.mark.parametrize(("id", "count"), SEEDED.items())
def test_seeded_chain_verifies(db, id, count):
    result = verify_chain(db, shipment(db, id))
    assert result.verified
    assert result.checked == count
    assert [c.seq for c in result.events] == list(range(1, count + 1))


def test_events_link_to_the_previous_hash(db):
    events = shipment(db).events
    assert events[0].prev_event_hash is None
    for prev, e in itertools.pairwise(events):
        assert e.prev_event_hash == prev.event_hash
    assert all(e.payload_hash == hash_json(e.payload) for e in events)


def failing(db: Session, id: str = "PS-1042") -> list[int]:
    db.expire_all()
    result = verify_chain(db, shipment(db, id))
    assert not result.verified
    return [c.seq for c in result.events if not c.ok]


def test_editing_event_text_breaks_that_event(db):
    db.execute(update(AuditEvent).where(AuditEvent.id == event(db, 7).id).values(text="Adjustment proposed: $30"))
    assert failing(db) == [7]


def test_editing_a_payload_is_caught_by_its_payload_hash(db):
    e = event(db, 3)
    tampered = e.payload | {"evidence": e.payload["evidence"][:1]}
    db.execute(update(AuditEvent).where(AuditEvent.id == e.id).values(payload=tampered))
    assert failing(db) == [3]
    db.expire_all()
    check = verify_chain(db, shipment(db)).events[2]
    assert not check.payload_ok and check.link_ok


def test_rewriting_an_event_and_its_hash_breaks_the_next_link(db):
    # A forger who also recomputes the edited event's own hash still breaks the link after it.
    e = event(db, 4)
    forged = event_hash(
        shipment_id=e.shipment_id,
        seq=e.seq,
        at=e.at,
        actor=e.actor,
        type=e.type,
        text="Shipment marked In Transit (late)",
        payload_hash=e.payload_hash,
        prev_event_hash=e.prev_event_hash,
    )
    db.execute(
        update(AuditEvent)
        .where(AuditEvent.id == e.id)
        .values(text="Shipment marked In Transit (late)", event_hash=forged)
    )
    assert failing(db) == [5]


def test_deleting_an_event_breaks_the_chain(db):
    db.execute(delete(AuditEvent).where(AuditEvent.id == event(db, 2).id))
    assert failing(db) == [3]


def test_edit_in_another_shipment_does_not_affect_this_one(db):
    db.execute(update(AuditEvent).where(AuditEvent.id == event(db, 2, "PS-1038").id).values(actor=Actor.BUYER.value))
    assert failing(db, "PS-1038") == [2]
    assert verify_chain(db, shipment(db, "PS-1042")).verified


def test_append_event_extends_the_chain(db):
    s = shipment(db)
    last = s.events[-1]
    at = datetime(2026, 10, 16, 9, 0, tzinfo=UTC)
    e = append_event(
        s, EventType.ADJUSTMENT_ACCEPTED, Actor.BUYER, {"adjustmentId": "adj_01"}, text="Buyer accepted", at=at
    )
    assert (e.seq, e.prev_event_hash) == (last.seq + 1, last.event_hash)
    assert verify_chain(db, s).verified


def test_append_event_rejects_unhashable_payload(db):
    with pytest.raises(TypeError):
        append_event(shipment(db), EventType.ADJUSTMENT_ACCEPTED, Actor.BUYER, {"at": datetime.now(UTC)}, text="x")
