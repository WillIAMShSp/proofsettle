"""Who sees a shipment created with a recipient (app.access), and the column migration."""

import pytest
from sqlalchemy import inspect, text

from app.db import create_tables, make_engine
from tests.test_writes import DISPATCH, NEW, RECEIPT, ok, photos

OWNER = {"X-Demo-Role": "Buyer", "X-Demo-User": "user-buyer-1", "X-Demo-Email": "buyer@northgate.example"}
RECIPIENT = {"X-Demo-Role": "Supplier", "X-Demo-User": "user-ferro", "X-Demo-Email": "Ops@Ferro.example"}
OTHER_SUPPLIER = {"X-Demo-Role": "Supplier", "X-Demo-User": "user-kestrel", "X-Demo-Email": "ops@kestrel.example"}
OTHER_BUYER = {"X-Demo-Role": "Buyer", "X-Demo-User": "user-buyer-2", "X-Demo-Email": "buyer2@northgate.example"}
REVIEWER = {"X-Demo-Role": "Reviewer", "X-Demo-User": "user-rev", "X-Demo-Email": "rev@proofsettle.example"}


def create_private(client) -> str:
    body = NEW | {"recipientEmail": "  OPS@ferro.example "}
    d = ok(client.post("/shipments", json=body, headers=OWNER), 201)
    assert d["recipientEmail"] == "ops@ferro.example"  # trimmed and lowercased
    return d["id"]


def listed(client, headers) -> set[str]:
    return {s["id"] for s in ok(client.get("/shipments", headers=headers))}


def test_private_shipment_shows_to_its_parties_and_reviewers(client):
    id = create_private(client)
    for who in (OWNER, RECIPIENT, REVIEWER):
        assert id in listed(client, who)
        assert ok(client.get(f"/shipments/{id}", headers=who))["id"] == id


def test_private_shipment_is_hidden_from_everyone_else(client):
    id = create_private(client)
    for who in (OTHER_SUPPLIER, OTHER_BUYER):
        assert id not in listed(client, who)
        assert client.get(f"/shipments/{id}", headers=who).status_code == 404
        assert client.get(f"/shipments/{id}/audit", headers=who).status_code == 404
        assert client.post(f"/shipments/{id}/agreement/approve", headers=who).status_code == 404
        assert client.post(f"/shipments/{id}/audit/verify", headers=who).status_code == 404


def test_shipments_without_an_owner_show_to_no_account(client):
    # The demo seed has no owner: no account sees it, Reviewers still do.
    for who in (OWNER, RECIPIENT, OTHER_SUPPLIER, OTHER_BUYER):
        assert listed(client, who).isdisjoint({"PS-1042", "PS-1038", "PS-1031"})
        assert client.get("/shipments/PS-1042", headers=who).status_code == 404
    assert {"PS-1042", "PS-1038", "PS-1031"} <= listed(client, REVIEWER)


def test_a_shipment_without_a_recipient_belongs_to_its_creator_only(client):
    d = ok(client.post("/shipments", json=NEW, headers=OWNER), 201)
    assert d["recipientEmail"] is None
    assert d["id"] in listed(client, OWNER)
    for who in (RECIPIENT, OTHER_SUPPLIER, OTHER_BUYER):
        assert d["id"] not in listed(client, who)


def test_the_creating_account_is_recorded_as_the_buyer(client):
    d = ok(client.post("/shipments", json=NEW, headers=OWNER), 201)
    assert d["buyer"] == "buyer@northgate.example"  # no profile name in tests: the email
    no_identity = ok(client.post("/shipments", json=NEW, headers={"X-Demo-Role": "Buyer"}), 201)
    assert no_identity["buyer"] == "Northgate Assembly Ltd"


def test_assign_ownerless_gives_the_seed_to_one_account(client, db):
    from app.ownership import assign_ownerless

    owned = ok(client.post("/shipments", json=NEW, headers=OTHER_BUYER), 201)["id"]
    user = "253aa058-8824-4e02-8f72-ff882fd44148"
    assert assign_ownerless(db, user) == ["PS-1031", "PS-1038", "PS-1042"]
    assert assign_ownerless(db, user) == []
    me = {"X-Demo-Role": "Buyer", "X-Demo-User": user, "X-Demo-Email": "me@example.com"}
    assert listed(client, me) == {"PS-1031", "PS-1038", "PS-1042"}  # not OTHER_BUYER's
    assert owned in listed(client, OTHER_BUYER)
    with pytest.raises(ValueError):
        assign_ownerless(db, "not-a-user-id")


def test_a_login_without_identity_sees_everything(client):
    id = create_private(client)
    assert id in listed(client, {"X-Demo-Role": "Supplier"})


def test_the_recipient_runs_the_manufacturer_steps(client):
    id = create_private(client)
    ok(client.post(f"/shipments/{id}/agreement/approve", headers=OWNER))
    ok(client.post(f"/shipments/{id}/agreement/approve", headers=RECIPIENT))
    ok(client.post(f"/shipments/{id}/evidence", headers=RECIPIENT, files=photos(DISPATCH, 4)))
    ok(client.post(f"/shipments/{id}/evidence", headers=OWNER, files=photos(RECEIPT, 4)))
    ok(client.post(f"/shipments/{id}/inspect", headers=OWNER), 202)
    d = ok(client.get(f"/shipments/{id}", headers=OWNER))
    finding = d["inspection"]["findings"][0]["id"]
    body = {"decision": "confirmed"}
    assert client.post(f"/findings/{finding}/review", json=body, headers=OTHER_BUYER).status_code == 404


def test_recipient_email_must_look_like_an_email(client):
    for bad in ("ferro", "ops@ferro", "a b@ferro.example", "x" * 320 + "@ferro.example"):
        res = client.post("/shipments", json=NEW | {"recipientEmail": bad}, headers=OWNER)
        assert res.status_code == 422, bad


def test_create_tables_adds_new_columns_to_an_existing_database(tmp_path):
    engine = make_engine(f"sqlite:///{(tmp_path / 'old.db').as_posix()}")
    with engine.begin() as conn:  # a shipments table from before created_by / recipient_email
        conn.execute(
            text(
                "CREATE TABLE shipments (id VARCHAR(32) PRIMARY KEY, chain_uuid CHAR(32) UNIQUE, "
                "title VARCHAR(200), buyer VARCHAR(200), supplier VARCHAR(200), status VARCHAR(10), "
                "dispute_reason TEXT, created_at DATETIME)"
            )
        )
        conn.execute(text("INSERT INTO shipments (id, title) VALUES ('PS-1', 'kept')"))
    create_tables(engine)
    create_tables(engine)  # and again: nothing left to add
    columns = {c["name"] for c in inspect(engine).get_columns("shipments")}
    assert {"created_by", "recipient_email"} <= columns
    with engine.connect() as conn:
        assert conn.execute(text("SELECT title, recipient_email FROM shipments")).one() == ("kept", None)
    engine.dispose()


def test_the_recipient_is_matched_by_their_supabase_email(client, monkeypatch):
    from app.auth import current_caller
    from app.main import app
    from tests.test_auth import USER_ID, _fake_supabase

    id = create_private(client)
    app.dependency_overrides.pop(current_caller)
    routes = {
        "/auth/v1/user": {"id": USER_ID, "email": "OPS@ferro.example"},
        "/rest/v1/profiles": [{"role": "Supplier"}],
    }
    _fake_supabase(monkeypatch, routes)
    session = {"Authorization": "Bearer session-token"}
    assert ok(client.get(f"/shipments/{id}", headers=session))["recipientEmail"] == "ops@ferro.example"

    routes["/auth/v1/user"] = {"id": USER_ID, "email": "someone@else.example"}
    assert client.get(f"/shipments/{id}", headers=session).status_code == 404


def test_a_supabase_buyer_creates_under_their_own_account_and_name(client, monkeypatch):
    from app.auth import current_caller
    from app.main import app
    from tests.test_auth import USER_ID, _fake_supabase

    app.dependency_overrides.pop(current_caller)
    routes = {
        "/auth/v1/user": {"id": USER_ID, "email": "Mike@Example.com"},
        "/rest/v1/profiles": [{"role": "Buyer", "name": "  Mike Hall "}],
    }
    _fake_supabase(monkeypatch, routes)
    session = {"Authorization": "Bearer session-token"}
    d = ok(client.post("/shipments", json=NEW | {"recipientEmail": "ops@ferro.example"}, headers=session), 201)
    assert d["buyer"] == "Mike Hall"
    assert [s["id"] for s in ok(client.get("/shipments", headers=session))] == [d["id"]]  # not the seed

    routes["/auth/v1/user"] = {"id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", "email": "other@example.com"}
    assert ok(client.get("/shipments", headers=session)) == []
