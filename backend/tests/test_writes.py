import hashlib
from pathlib import Path

import pytest

from app.config import settings
from app.inspection import InspectionRequest
from app.main import app
from app.routes import inspection_provider
from app.seed import PS_1042_TERMS

ASSETS = Path(__file__).resolve().parents[2] / "src" / "assets"
DISPATCH, RECEIPT = (ASSETS / "dispatch.jpg").read_bytes(), (ASSETS / "receipt.jpg").read_bytes()
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
BUYER, SUPPLIER, REVIEWER = ({"X-Demo-Role": r} for r in ("Buyer", "Supplier", "Reviewer"))
NEW = {
    "title": "100 metal components",
    "supplier": "Ferro Precision Works",
    "terms": PS_1042_TERMS.model_dump(mode="json"),
}


def photos(data, n, ext="jpg"):
    return [("files", (f"photo{i}.{ext}", data, "image/jpeg")) for i in range(n)]


def post(client, path, role, **kw):
    return client.post(path, headers=role, **kw)


def ok(res, code=200):
    assert res.status_code == code, res.text
    return res.json()


def verified_chain(client, id):
    return client.get(f"/shipments/{id}/audit", headers=BUYER).json()["verified"]


def create(client):
    return ok(post(client, "/shipments", BUYER, json=NEW), 201)


def to_status(client, target):
    """A new shipment driven through the API up to `target`."""
    id = create(client)["id"]
    steps = [
        ("Agreed", lambda: [post(client, f"/shipments/{id}/agreement/approve", r) for r in (BUYER, SUPPLIER)]),
        ("In Transit", lambda: post(client, f"/shipments/{id}/evidence", SUPPLIER, files=photos(DISPATCH, 4))),
        ("Inspection", lambda: post(client, f"/shipments/{id}/evidence", BUYER, files=photos(RECEIPT, 4))),
        ("Proposed", lambda: post(client, f"/shipments/{id}/inspect", BUYER)),
    ]
    for status, step in steps:
        if client.get(f"/shipments/{id}", headers=BUYER).json()["status"] == target:
            break
        step()
        assert client.get(f"/shipments/{id}", headers=BUYER).json()["status"] == status
    return id


def dispute_1042(client):
    return ok(post(client, "/shipments/PS-1042/dispute", BUYER, json={"reason": "Component #063 is discoloured"}))


# --- Case A: a new shipment, end to end ---------------------------------------------------


def test_case_a_full_workflow(client, seeded):
    files = seeded[1]
    d = create(client)
    id = d["id"]
    assert (id, d["status"], d["amount"], d["buyer"]) == ("PS-1043", "Draft", 10000, "Northgate Assembly Ltd")
    assert d["agreement"]["buyerApproved"] is False and d["agreement"]["supplierApproved"] is False
    assert [e["text"] for e in d["events"]] == ["Agreement drafted: 100 × Machined metal component, $10,000"]

    d = ok(post(client, f"/shipments/{id}/agreement/approve", BUYER))
    assert d["status"] == "Draft" and d["agreement"]["buyerApproved"] and not d["agreement"]["supplierApproved"]
    d = ok(post(client, f"/shipments/{id}/agreement/approve", SUPPLIER))
    assert d["status"] == "Agreed"
    assert d["events"][-1]["text"] == "Agreement approved by both parties"

    # Two dispatch photos aren't enough (the agreement asks for 4); two more are.
    d = ok(post(client, f"/shipments/{id}/evidence", SUPPLIER, files=photos(DISPATCH, 2)))
    assert d["status"] == "Agreed"
    d = ok(post(client, f"/shipments/{id}/evidence", SUPPLIER, files=photos(DISPATCH, 2)))
    assert d["status"] == "In Transit"
    assert d["events"][-1]["text"] == "Dispatch photos uploaded (2); shipment moved to In Transit"

    d = ok(post(client, f"/shipments/{id}/evidence", BUYER, files=photos(RECEIPT, 4)))
    assert d["status"] == "Inspection"
    assert [ev["kind"] for ev in d["evidence"]] == ["dispatch"] * 4 + ["receipt"] * 4
    assert [ev["id"] for ev in d["evidence"]] == [f"ev_{n}" for n in range(21, 29)]
    for ev in d["evidence"]:
        expected = DISPATCH if ev["kind"] == "dispatch" else RECEIPT
        assert ev["sha256"] == hashlib.sha256(expected).hexdigest()
        assert (files / f"{ev['id']}.jpg").read_bytes() == expected
        assert client.get(ev["url"]).content == expected

    d = ok(post(client, f"/shipments/{id}/inspect", BUYER))
    assert d["status"] == "Proposed"
    receipt_ids = [ev["id"] for ev in d["evidence"] if ev["kind"] == "receipt"]
    findings = d["inspection"]["findings"]
    assert [f["id"] for f in findings] == ["fnd_10", "fnd_11", "fnd_12", "fnd_13"]
    assert [f["evidenceIds"] for f in findings] == [[e] for e in receipt_ids]
    adj = d["adjustment"]
    assert (adj["id"], adj["credit"], adj["settlementAmount"]) == ("adj_03", 300, 9700)
    assert [e["actor"] for e in d["events"][-2:]] == ["AI", "System"]

    d = ok(post(client, f"/shipments/{id}/accept", BUYER))
    assert d["status"] == "Proposed" and d["adjustment"]["buyerAcceptedAt"] is not None
    assert d["actions"]["canAccept"] is False
    d = ok(post(client, f"/shipments/{id}/accept", SUPPLIER))
    assert d["status"] == "Accepted"
    assert [e["text"] for e in d["events"][-2:]] == [
        "Buyer accepted $300 adjustment",
        "Supplier accepted $300 adjustment",
    ]

    assert verified_chain(client, id)
    v = ok(post(client, f"/shipments/{id}/audit/verify", BUYER))
    assert v["verified"] is True
    assert v["checked"] == len(d["events"]) + 8 + 1


def test_approving_twice_is_a_no_op(client):
    id = create(client)["id"]
    first = ok(post(client, f"/shipments/{id}/agreement/approve", BUYER))
    again = ok(post(client, f"/shipments/{id}/agreement/approve", BUYER))
    assert again["events"] == first["events"] and again["status"] == "Draft"


def test_accepting_twice_is_a_no_op(client):
    first = ok(post(client, "/shipments/PS-1042/accept", BUYER))
    again = ok(post(client, "/shipments/PS-1042/accept", BUYER))
    assert again["events"] == first["events"]
    assert again["adjustment"]["buyerAcceptedAt"] == first["adjustment"]["buyerAcceptedAt"]


def test_png_is_accepted(client):
    id = to_status(client, "Agreed")
    d = ok(post(client, f"/shipments/{id}/evidence", SUPPLIER, files=photos(PNG, 1, "png")))
    ev = d["evidence"][0]
    assert ev["sha256"] == hashlib.sha256(PNG).hexdigest()
    assert client.get(ev["url"]).headers["content-type"] == "image/png"


# --- Case B: PS-1042 disputed and resolved ------------------------------------------------


def test_case_b_dispute_review_resolve(client):
    d = dispute_1042(client)
    assert d["status"] == "Disputed" and d["disputeReason"] == "Component #063 is discoloured"
    assert d["actions"] == {"canAccept": False, "canDispute": False, "canReview": False, "canResolve": False}

    # fnd_04 (#063) still needs review, so resolving is refused.
    assert post(client, "/shipments/PS-1042/resolve", REVIEWER).status_code == 409

    d = ok(post(client, "/findings/fnd_04/review", REVIEWER, json={"decision": "confirmed"}))
    assert d["status"] == "Disputed"
    f = next(f for f in d["inspection"]["findings"] if f["id"] == "fnd_04")
    assert (f["reviewOverride"], f["reviewedBy"]) == ("confirmed", "Reviewer")
    assert d["adjustment"]["credit"] == 400
    assert d["actions"]["canResolve"] is True

    d = ok(post(client, "/shipments/PS-1042/resolve", REVIEWER))
    assert d["status"] == "Resolved"
    adj = d["adjustment"]
    assert (adj["credit"], adj["settlementAmount"]) == (400, 9600)
    assert adj["appliedRule"] == {"credit": "4 × $100 = $400", "settlement": "$10,000 − $400 = $9,600"}
    assert [(e["actor"], e["text"]) for e in d["events"][-3:]] == [
        ("Buyer", "Adjustment disputed: Component #063 is discoloured"),
        ("Reviewer", "Reviewer confirmed fnd_04 (Component #063)"),
        ("Reviewer", "Dispute resolved: $400 credit"),
    ]
    assert verified_chain(client, "PS-1042")


def test_rejecting_063_keeps_300(client):
    dispute_1042(client)
    ok(post(client, "/findings/fnd_04/review", REVIEWER, json={"decision": "rejected"}))
    adj = ok(post(client, "/shipments/PS-1042/resolve", REVIEWER))["adjustment"]
    assert (adj["credit"], adj["settlementAmount"]) == (300, 9700)


@pytest.mark.parametrize("body", [None, {}, {"reason": ""}, {"reason": "   "}])
def test_dispute_needs_a_reason(client, body):
    res = post(client, "/shipments/PS-1042/dispute", BUYER, json=body)
    assert res.status_code == 400
    assert client.get("/shipments/PS-1042", headers=BUYER).json()["status"] == "Proposed"


def test_a_party_that_accepted_cannot_dispute(client):
    ok(post(client, "/shipments/PS-1042/accept", BUYER))
    assert dispute_1042_status(client, BUYER) == 409
    assert dispute_1042_status(client, SUPPLIER) == 200


def dispute_1042_status(client, role):
    return post(client, "/shipments/PS-1042/dispute", role, json={"reason": "No"}).status_code


# --- the client can't set an amount or a status -------------------------------------------

SNEAKY = {"amount": 1, "credit": 1, "settlementAmount": 1, "status": "Accepted"}


def test_amount_and_status_in_a_body_change_nothing(client):
    # Routes without a body ignore it: these act as usual, with the engine's numbers.
    d = ok(post(client, "/shipments/PS-1042/accept", BUYER, json=SNEAKY))
    assert (d["status"], d["adjustment"]["credit"], d["amount"]) == ("Proposed", 300, 10000)

    # Routes with a body reject unknown fields, and nothing is written.
    before = client.get("/shipments/PS-1042", headers=SUPPLIER).json()
    assert post(client, "/shipments/PS-1042/dispute", SUPPLIER, json={"reason": "x"} | SNEAKY).status_code == 422
    assert client.get("/shipments/PS-1042", headers=SUPPLIER).json() == before

    assert post(client, "/shipments", BUYER, json=NEW | {"status": "Accepted"}).status_code == 422
    assert [s["id"] for s in client.get("/shipments", headers=BUYER).json()] == ["PS-1042", "PS-1038", "PS-1031"]

    dispute = ok(post(client, "/shipments/PS-1042/dispute", SUPPLIER, json={"reason": "x"}))
    assert dispute["status"] == "Disputed"
    body = {"decision": "confirmed"} | SNEAKY
    assert post(client, "/findings/fnd_04/review", REVIEWER, json=body).status_code == 422
    ok(post(client, "/findings/fnd_04/review", REVIEWER, json={"decision": "confirmed"}))
    d = ok(post(client, "/shipments/PS-1042/resolve", REVIEWER, json=SNEAKY))
    assert (d["status"], d["adjustment"]["credit"], d["adjustment"]["settlementAmount"]) == ("Resolved", 400, 9600)


def test_inspection_output_with_an_amount_is_refused(client):
    id = to_status(client, "Inspection")

    class Sneaky:
        name = "sneaky"

        def inspect(self, request: InspectionRequest) -> str:
            ev = request.receipt[0].id
            return (
                '{"findings": [{"unitRef": "#1", "defectType": "bend", "confidence": 0.99, "evidenceIds": ["'
                + ev
                + '"], "description": "x", "presentInDispatch": false, "amount": 5000}]}'
            )

    app.dependency_overrides[inspection_provider] = Sneaky
    res = post(client, f"/shipments/{id}/inspect", BUYER)
    assert res.status_code == 502
    d = client.get(f"/shipments/{id}", headers=BUYER).json()
    assert (d["status"], d["inspection"], d["adjustment"]) == ("Inspection", None, None)


def test_inspection_output_citing_unknown_evidence_is_refused(client):
    id = to_status(client, "Inspection")

    class Unknown:
        name = "unknown"

        def inspect(self, request: InspectionRequest) -> str:
            return (
                '{"findings": [{"unitRef": "#1", "defectType": "bend", "confidence": 0.99, "evidenceIds": ["ev_01"],'
                ' "description": "x", "presentInDispatch": false}]}'
            )

    app.dependency_overrides[inspection_provider] = Unknown
    assert post(client, f"/shipments/{id}/inspect", BUYER).status_code == 502
    assert client.get(f"/shipments/{id}", headers=BUYER).json()["status"] == "Inspection"


# --- verify -------------------------------------------------------------------------------


def test_verify_seeded_shipment(client):
    v = ok(post(client, "/shipments/PS-1042/audit/verify", BUYER))
    assert set(v) == {"shipmentId", "verified", "checked", "agreement", "events", "evidence", "chain", "verifiedAt"}
    assert v["verified"] is True
    assert v["checked"] == 7 + 8 + 1
    assert v["agreement"]["ok"] and v["agreement"]["id"] == "agr_01"
    assert v["chain"] == {"available": False, "anchored": 0, "mismatches": []}
    d = client.get("/shipments/PS-1042", headers=BUYER).json()
    assert all(ev["verified"] is True for ev in d["evidence"])


def test_tampered_evidence_fails_only_that_item(client, seeded):
    (seeded[1] / "ev_06.jpg").write_bytes(RECEIPT + b"edited")
    v = ok(post(client, "/shipments/PS-1042/audit/verify", BUYER))
    assert v["verified"] is False
    assert {e["id"]: e["ok"] for e in v["evidence"]} == {f"ev_{n:02d}": n != 6 for n in range(1, 9)}
    bad = next(e for e in v["evidence"] if e["id"] == "ev_06")
    assert bad["recomputedHash"] == hashlib.sha256(RECEIPT + b"edited").hexdigest() != bad["storedHash"]
    assert all(e["ok"] for e in v["events"]) and v["agreement"]["ok"]

    d = client.get("/shipments/PS-1042", headers=BUYER).json()
    assert {ev["id"]: ev["verified"] for ev in d["evidence"]} == {f"ev_{n:02d}": n != 6 for n in range(1, 9)}


def test_missing_evidence_file_fails_verify(client, seeded):
    (seeded[1] / "ev_02.jpg").unlink()
    v = ok(post(client, "/shipments/PS-1042/audit/verify", BUYER))
    bad = next(e for e in v["evidence"] if e["id"] == "ev_02")
    assert (bad["ok"], bad["recomputedHash"], v["verified"]) == (False, None, False)


def test_tampered_terms_fail_verify(client, db):
    from app.models import Agreement

    agr = db.get(Agreement, "agr_01")
    agr.terms = agr.terms | {"quantity": 99}
    db.commit()
    v = ok(post(client, "/shipments/PS-1042/audit/verify", BUYER))
    assert v["agreement"]["ok"] is False and v["verified"] is False
    assert all(e["ok"] for e in v["evidence"])


def test_inspection_refuses_tampered_photos(client, seeded):
    id = to_status(client, "Inspection")
    receipt = [ev for ev in client.get(f"/shipments/{id}", headers=BUYER).json()["evidence"] if ev["kind"] == "receipt"]
    (seeded[1] / f"{receipt[0]['id']}.jpg").write_bytes(b"\xff\xd8\xff other")
    assert post(client, f"/shipments/{id}/inspect", BUYER).status_code == 409


# --- roles, states, uploads ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "path", "role", "kw"),
    [
        (None, "/shipments", SUPPLIER, {"json": NEW}),
        (None, "/shipments", REVIEWER, {"json": NEW}),
        ("Draft", "/agreement/approve", REVIEWER, {}),
        ("Agreed", "/evidence", BUYER, {"files": photos(DISPATCH, 1)}),
        ("Agreed", "/evidence", REVIEWER, {"files": photos(DISPATCH, 1)}),
        ("In Transit", "/evidence", SUPPLIER, {"files": photos(RECEIPT, 1)}),
        ("Inspection", "/inspect", REVIEWER, {}),
        ("Proposed", "/accept", REVIEWER, {}),
        ("Proposed", "/dispute", REVIEWER, {"json": {"reason": "x"}}),
    ],
)
def test_wrong_role_gets_403(client, status, path, role, kw):
    if status is None:
        res = post(client, path, role, **kw)
    else:
        id = to_status(client, status)
        before = client.get(f"/shipments/{id}", headers=BUYER).json()
        res = post(client, f"/shipments/{id}{path}", role, **kw)
        assert client.get(f"/shipments/{id}", headers=BUYER).json() == before
    assert res.status_code == 403, res.text


@pytest.mark.parametrize("role", [BUYER, SUPPLIER])
def test_parties_cannot_review_or_resolve(client, role):
    dispute_1042(client)
    assert post(client, "/findings/fnd_04/review", role, json={"decision": "confirmed"}).status_code == 403
    assert post(client, "/shipments/PS-1042/resolve", role).status_code == 403
    assert client.get("/shipments/PS-1042", headers=role).json()["status"] == "Disputed"


@pytest.mark.parametrize(
    ("id", "path", "role", "kw"),
    [
        ("PS-1042", "/agreement/approve", BUYER, {}),  # not Draft
        ("PS-1042", "/evidence", BUYER, {"files": photos(RECEIPT, 1)}),  # Proposed
        ("PS-1038", "/inspect", BUYER, {}),  # In Transit
        ("PS-1038", "/accept", BUYER, {}),
        ("PS-1031", "/dispute", BUYER, {"json": {"reason": "x"}}),  # Resolved
        ("PS-1042", "/resolve", REVIEWER, {}),  # not Disputed
    ],
)
def test_wrong_state_gets_409(client, id, path, role, kw):
    assert post(client, f"/shipments/{id}{path}", role, **kw).status_code == 409


def test_review_outside_dispute_gets_409(client):
    assert post(client, "/findings/fnd_04/review", REVIEWER, json={"decision": "confirmed"}).status_code == 409


@pytest.mark.parametrize(
    ("path", "kw", "code"),
    [
        ("/shipments", {"json": NEW}, 400),
        ("/shipments/PS-1042/accept", {}, 400),
        ("/shipments/PS-0000/accept", {"headers": BUYER}, 404),
        ("/findings/fnd_99/review", {"headers": REVIEWER, "json": {"decision": "confirmed"}}, 404),
        ("/findings/fnd_04/review", {"headers": REVIEWER, "json": {"decision": "maybe"}}, 422),
    ],
)
def test_write_errors(client, path, kw, code):
    res = client.post(path, **kw)
    assert res.status_code == code
    assert res.headers["content-type"] == "application/json; charset=utf-8"


def test_upload_rejects_non_images(client):
    id = to_status(client, "Agreed")
    files = [("files", ("notes.jpg", b"GIF89a not really", "image/jpeg"))]
    assert post(client, f"/shipments/{id}/evidence", SUPPLIER, files=files).status_code == 415
    assert client.get(f"/shipments/{id}", headers=BUYER).json()["evidence"] == []


def test_upload_size_limit(client, monkeypatch, seeded):
    id = to_status(client, "Agreed")
    monkeypatch.setattr(settings, "max_evidence_bytes", len(DISPATCH) - 1)
    assert post(client, f"/shipments/{id}/evidence", SUPPLIER, files=photos(DISPATCH, 1)).status_code == 413
    monkeypatch.setattr(settings, "max_evidence_files", 2)
    monkeypatch.setattr(settings, "max_evidence_bytes", 10**7)
    assert post(client, f"/shipments/{id}/evidence", SUPPLIER, files=photos(DISPATCH, 3)).status_code == 413
    assert client.get(f"/shipments/{id}", headers=BUYER).json()["evidence"] == []
    assert sorted(p.name for p in seeded[1].iterdir()) == [f"ev_{n:02d}.jpg" for n in range(1, 21)]


# --- dev reset ----------------------------------------------------------------------------


def test_dev_reset_is_off_by_default(client):
    assert client.post("/dev/reset").status_code == 404


def test_dev_reset_reloads_the_seed(client, monkeypatch, seeded):
    monkeypatch.setattr(settings, "dev_mode", True)
    create(client)
    dispute_1042(client)
    to_status(client, "In Transit")

    assert ok(client.post("/dev/reset")) == {"shipments": ["PS-1042", "PS-1038", "PS-1031"]}
    assert client.get("/shipments/PS-1042", headers=BUYER).json()["status"] == "Proposed"
    assert sorted(p.name for p in seeded[1].iterdir()) == [f"ev_{n:02d}.jpg" for n in range(1, 21)]
