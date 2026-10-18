"""app.migrate: copying the local data into another database and store, exactly, or not at all."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import make_engine
from app.migrate import MigrationError, migrate
from app.models import ChatMessage, Evidence, Shipment
from app.storage import LocalStore
from tests.test_chat import BUYER as CHAT_BUYER
from tests.test_chat import SUPPLIER as CHAT_SUPPLIER
from tests.test_chat import invoice, send


@pytest.fixture
def target(tmp_path):
    engine = make_engine(f"sqlite:///{(tmp_path / 'target.db').as_posix()}")
    yield engine, LocalStore(tmp_path / "bucket")
    engine.dispose()


def count(engine, model):
    with Session(engine) as db:
        return db.scalar(select(func.count()).select_from(model))


def test_everything_is_copied_exactly(client, seeded, target):
    engine, files = seeded
    send(client, "PS-1042", CHAT_BUYER, "Is #063 glare?")
    invoice(client, "PS-1038", CHAT_SUPPLIER)
    target_engine, bucket = target

    summary = migrate(engine, LocalStore(files), target_engine, bucket)

    assert "Every count, photo hash and audit chain matches" in summary
    assert count(target_engine, Shipment) == 3
    assert count(target_engine, ChatMessage) == 2
    with Session(engine) as src, Session(target_engine) as dst:
        for ev in src.scalars(select(Evidence)):
            assert bucket.get(ev.file_name) == (files / ev.file_name).read_bytes()
        a = src.get(Shipment, "PS-1031")
        b = dst.get(Shipment, "PS-1031")
        assert (a.status, a.created_by, [e.event_hash for e in a.events]) == (
            b.status,
            b.created_by,
            [e.event_hash for e in b.events],
        )
        invoice_row = dst.scalars(select(ChatMessage).where(ChatMessage.invoice.is_not(None))).one()
        assert invoice_row.invoice["amountDue"] == 6400


def test_it_refuses_a_target_that_already_has_shipments(seeded, target):
    engine, files = seeded
    target_engine, bucket = target
    migrate(engine, LocalStore(files), target_engine, bucket)
    with pytest.raises(MigrationError, match="already has shipments"):
        migrate(engine, LocalStore(files), target_engine, bucket)
    assert count(target_engine, Shipment) == 3  # untouched


def test_a_changed_local_photo_stops_it_before_anything_is_written(seeded, target):
    engine, files = seeded
    (files / "ev_02.jpg").write_bytes(b"\xff\xd8\xff edited")
    target_engine, bucket = target
    with pytest.raises(MigrationError, match="ev_02.jpg no longer matches"):
        migrate(engine, LocalStore(files), target_engine, bucket)
    assert count(target_engine, Shipment) == 0
    assert bucket.get("ev_01.jpg") is None


def test_a_different_photo_already_in_the_bucket_is_never_overwritten(seeded, target):
    engine, files = seeded
    target_engine, bucket = target
    bucket.put("ev_01.jpg", b"\xff\xd8\xff someone else's", "image/jpeg")
    with pytest.raises(MigrationError, match="different ev_01.jpg"):
        migrate(engine, LocalStore(files), target_engine, bucket)
    assert count(target_engine, Shipment) == 0


def test_photos_left_by_a_failed_run_are_reused(seeded, target):
    engine, files = seeded
    target_engine, bucket = target
    bucket.put("ev_01.jpg", (files / "ev_01.jpg").read_bytes(), "image/jpeg")  # same bytes
    assert "uploaded 19 of 20 photos" in migrate(engine, LocalStore(files), target_engine, bucket)
