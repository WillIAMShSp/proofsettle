import hashlib
import itertools
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import update

from app.models import AdjustmentRow, AuditEvent, FindingRow, Shipment
from app.workflow import Status

ASSETS = Path(__file__).resolve().parents[2] / "src" / "assets"
BUYER, SUPPLIER, REVIEWER = ({"X-Demo-Role": r} for r in ("Buyer", "Supplier", "Reviewer"))

# Key sets from the JSON examples in API_CONTRACT.md.
SUMMARY_KEYS = {"id", "title", "buyer", "supplier", "amount", "status"}
DETAIL_KEYS = SUMMARY_KEYS | {
    "disputeReason",
    "agreement",
    "evidence",
    "inspection",
    "adjustment",
    "actions",
    "events",
}
AGREEMENT_KEYS = {"terms", "buyerApproved", "supplierApproved", "termsHash"}
EVIDENCE_KEYS = {"id", "kind", "url", "sha256", "uploadedBy", "at", "verified"}
FINDING_KEYS = {
    "id",
    "unitRef",
    "defectType",
    "confidence",
    "evidenceIds",
    "description",
    "presentInDispatch",
    "reviewOverride",
    "reviewedBy",
    "reviewedAt",
}
ADJUSTMENT_KEYS = {
    "id",
    "computedAt",
    "confirmedDefects",
    "credit",
    "settlementAmount",
    "appliedRule",
    "counted",
    "excluded",
    "needsReview",
    "amountIfReviewedConfirmed",
    "assumptions",
    "status",
    "buyerAcceptedAt",
    "supplierAcceptedAt",
}
ACTION_KEYS = {"canAccept", "canDispute", "canReview", "canResolve"}
EVENT_KEYS = {"id", "at", "actor", "text", "hash", "prevHash", "txHash", "seq", "type", "payloadHash", "chainStatus"}
NO_ACTIONS = dict.fromkeys(ACTION_KEYS, False)


def actions(client, role, id="PS-1042"):
    return client.get(f"/shipments/{id}", headers=role).json()["actions"]


# --- shapes -------------------------------------------------------------------------------


def test_list_matches_dashboard_shape(client):
    res = client.get("/shipments", headers=BUYER)
    assert res.status_code == 200
    assert res.json() == [
        {
            "id": "PS-1042",
            "title": "100 metal components",
            "buyer": "Northgate Assembly Ltd",
            "supplier": "Ferro Precision Works",
            "amount": 10000,
            "status": "Proposed",
        },
        {
            "id": "PS-1038",
            "title": "40 hydraulic valves",
            "buyer": "Northgate Assembly Ltd",
            "supplier": "Kestrel Fluid Systems",
            "amount": 6400,
            "status": "In Transit",
        },
        {
            "id": "PS-1031",
            "title": "250 steel brackets",
            "buyer": "Northgate Assembly Ltd",
            "supplier": "Ferro Precision Works",
            "amount": 3750,
            "status": "Resolved",
        },
    ]


def test_detail_shape(client):
    d = client.get("/shipments/PS-1042", headers=BUYER).json()
    assert set(d) == DETAIL_KEYS
    assert set(d["agreement"]) == AGREEMENT_KEYS
    assert d["agreement"]["buyerApproved"] and d["agreement"]["supplierApproved"]
    assert d["agreement"]["terms"]["compensation"] == {
        "type": "per_defective_unit",
        "amountPerUnit": 100,
        "maxCredit": 10000,
    }
    assert all(set(ev) == EVIDENCE_KEYS for ev in d["evidence"])
    assert [ev["kind"] for ev in d["evidence"]] == ["dispatch"] * 4 + ["receipt"] * 4
    assert set(d["inspection"]) == {"findings"}
    assert all(set(f) == FINDING_KEYS for f in d["inspection"]["findings"])
    assert set(d["actions"]) == ACTION_KEYS
    assert all(set(e) == EVENT_KEYS for e in d["events"])
    assert d["disputeReason"] is None


def test_detail_adjustment_is_the_engine_output(client):
    adj = client.get("/shipments/PS-1042", headers=BUYER).json()["adjustment"]
    assert set(adj) == ADJUSTMENT_KEYS
    assert adj["id"] == "adj_01"
    assert adj["computedAt"] == "2026-10-15T16:32:00Z"
    assert (adj["confirmedDefects"], adj["credit"], adj["settlementAmount"]) == (3, 300, 9700)
    assert adj["appliedRule"] == {"credit": "3 × $100 = $300", "settlement": "$10,000 − $300 = $9,700"}
    assert [o["findingId"] for o in adj["counted"]] == ["fnd_01", "fnd_02", "fnd_03"]
    assert [o["findingId"] for o in adj["needsReview"]] == ["fnd_04"]
    assert adj["amountIfReviewedConfirmed"] == 400
    assert adj["status"] == "needs_review"
    assert adj["buyerAcceptedAt"] is None and adj["supplierAcceptedAt"] is None


def test_events_match_the_frontend_seed(client):
    events = client.get("/shipments/PS-1042", headers=BUYER).json()["events"]
    assert [(e["at"], e["actor"], e["text"]) for e in events] == [
        ("2026-10-09T10:12:00Z", "Buyer", "Agreement drafted: 100 components, $10,000"),
        ("2026-10-09T14:40:00Z", "Supplier", "Agreement approved by both parties"),
        ("2026-10-11T08:05:00Z", "Supplier", "Dispatch photos uploaded (4)"),
        ("2026-10-11T09:30:00Z", "Supplier", "Shipment marked In Transit"),
        ("2026-10-15T16:22:00Z", "Buyer", "Receipt photos uploaded (4)"),
        ("2026-10-15T16:31:00Z", "AI", "Inspection complete: 3 defects flagged"),
        ("2026-10-15T16:32:00Z", "System", "Adjustment proposed from agreement rule: $300"),
    ]
    assert events[0]["id"] == "evt_01" and events[0]["prevHash"] is None
    assert all(e["prevHash"] == p["hash"] for p, e in itertools.pairwise(events))
    assert all(e["txHash"] is None and e["chainStatus"] == "skipped" for e in events)


def test_in_transit_shipment_has_no_inspection_or_adjustment(client):
    d = client.get("/shipments/PS-1038", headers=BUYER).json()
    assert d["status"] == "In Transit"
    assert d["inspection"] is None and d["adjustment"] is None
    assert [ev["kind"] for ev in d["evidence"]] == ["dispatch"] * 4
    assert d["actions"] == NO_ACTIONS


def test_resolved_shipment_shows_the_reviewed_outcome(client):
    d = client.get("/shipments/PS-1031", headers=REVIEWER).json()
    assert d["status"] == "Resolved"
    assert d["disputeReason"] == "Bracket #101 shows a weld seam, not a crack"
    adj = d["adjustment"]
    assert (adj["credit"], adj["settlementAmount"]) == (15, 3735)
    assert adj["appliedRule"]["credit"] == "(2 − 1 tolerated) × $15 = $15"
    assert {o["findingId"]: o["reason"] for o in adj["excluded"]} == {
        "fnd_07": "review_rejected",
        "fnd_08": "review_rejected",
        "fnd_09": "present_in_dispatch",
    }
    assert adj["needsReview"] == []
    assert d["actions"] == NO_ACTIONS


# --- actions per role ---------------------------------------------------------------------


def test_actions_when_proposed(client):
    assert actions(client, BUYER) == {"canAccept": True, "canDispute": True, "canReview": False, "canResolve": False}
    assert actions(client, SUPPLIER) == {"canAccept": True, "canDispute": True, "canReview": False, "canResolve": False}
    assert actions(client, REVIEWER) == NO_ACTIONS


def test_actions_after_buyer_accepts(client, db):
    db.execute(update(AdjustmentRow).values(buyer_accepted_at=datetime(2026, 10, 16, 9, 0, tzinfo=UTC)))
    db.commit()
    assert actions(client, BUYER) == NO_ACTIONS
    assert actions(client, SUPPLIER) == {"canAccept": True, "canDispute": True, "canReview": False, "canResolve": False}
    assert client.get("/shipments/PS-1042", headers=BUYER).json()["adjustment"]["buyerAcceptedAt"] == (
        "2026-10-16T09:00:00Z"
    )


def test_actions_when_disputed(client, db):
    db.execute(update(Shipment).where(Shipment.id == "PS-1042").values(status=Status.DISPUTED))
    db.commit()
    assert actions(client, BUYER) == NO_ACTIONS
    assert actions(client, SUPPLIER) == NO_ACTIONS
    # fnd_04 is still in needsReview, so the Reviewer may review but not resolve yet.
    assert actions(client, REVIEWER) == {
        "canAccept": False,
        "canDispute": False,
        "canReview": True,
        "canResolve": False,
    }

    db.execute(
        update(FindingRow)
        .where(FindingRow.id == "fnd_04")
        .values(review_override="confirmed", reviewed_by="Reviewer", reviewed_at=datetime(2026, 10, 16, tzinfo=UTC))
    )
    db.commit()
    assert actions(client, REVIEWER) == {"canAccept": False, "canDispute": False, "canReview": True, "canResolve": True}
    assert client.get("/shipments/PS-1042", headers=REVIEWER).json()["adjustment"]["credit"] == 400


# --- audit, files, errors -----------------------------------------------------------------


def test_audit_endpoint_verifies_the_seeded_chain(client):
    a = client.get("/shipments/PS-1042/audit", headers=BUYER).json()
    assert set(a) == {"shipmentId", "verified", "checked", "events", "checks"}
    assert (a["shipmentId"], a["verified"], a["checked"]) == ("PS-1042", True, 7)
    assert all(set(e) == EVENT_KEYS for e in a["events"])
    assert all(
        set(c) == {"id", "seq", "storedHash", "recomputedHash", "payloadOk", "linkOk", "ok"} and c["ok"]
        for c in a["checks"]
    )


def test_audit_endpoint_reports_a_tampered_event(client, db):
    db.execute(
        update(AuditEvent).where(AuditEvent.shipment_id == "PS-1042", AuditEvent.seq == 7).values(text="Adjustment: $3")
    )
    db.commit()
    a = client.get("/shipments/PS-1042/audit", headers=BUYER).json()
    assert a["verified"] is False
    assert [c["ok"] for c in a["checks"]] == [True] * 6 + [False]


@pytest.mark.parametrize(("ev_id", "asset"), [("ev_01", "dispatch.jpg"), ("ev_08", "receipt.jpg")])
def test_evidence_file_matches_its_hash(client, ev_id, asset):
    d = client.get("/shipments/PS-1042", headers=BUYER).json()
    ev = next(e for e in d["evidence"] if e["id"] == ev_id)
    res = client.get(ev["url"])
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/jpeg"
    assert hashlib.sha256(res.content).hexdigest() == ev["sha256"]
    assert res.content == (ASSETS / asset).read_bytes()


@pytest.mark.parametrize(
    ("path", "headers", "code"),
    [
        ("/shipments", {}, 400),
        ("/shipments", {"X-Demo-Role": "Admin"}, 400),
        ("/shipments/PS-1042", {"X-Demo-Role": "System"}, 400),
        ("/shipments/PS-0000", BUYER, 404),
        ("/shipments/PS-0000/audit", BUYER, 404),
        ("/evidence/ev_99/file", {}, 404),
    ],
)
def test_errors(client, path, headers, code):
    assert client.get(path, headers=headers).status_code == code


def test_cors_allows_the_frontend_dev_server(client):
    res = client.options(
        "/shipments",
        headers={
            "Origin": "http://localhost:8080",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization",
        },
    )
    assert res.status_code == 200
    assert res.headers["access-control-allow-origin"] == "http://localhost:8080"
    assert (
        client.get("/shipments", headers=BUYER | {"Origin": "http://evil.example"}).headers.get(
            "access-control-allow-origin"
        )
        is None
    )


@pytest.mark.parametrize(
    ("path", "headers", "code"),
    [
        ("/health", {}, 200),
        ("/shipments", BUYER, 200),
        ("/shipments/PS-1042", BUYER, 200),
        ("/shipments/PS-1042/audit", BUYER, 200),
        ("/shipments", {}, 400),  # HTTPException
        ("/shipments/PS-0000", BUYER, 404),
        ("/no-such-route", {}, 404),  # FastAPI's own not-found
        ("/evidence/ev_99/file", {}, 404),
    ],
)
def test_json_responses_declare_utf8(client, path, headers, code):
    # Windows PowerShell 5.1 decodes a bare application/json as Latin-1 and garbles ×, −, ≥.
    res = client.get(path, headers=headers)
    assert res.status_code == code
    assert res.headers["content-type"] == "application/json; charset=utf-8"


def test_utf8_json_body_round_trips(client):
    res = client.get("/shipments/PS-1042", headers=BUYER)
    assert "3 × $100 = $300" in res.content.decode("utf-8")
    assert res.json()["adjustment"]["assumptions"][0].startswith("Only findings at ≥ 85%")


def test_non_json_responses_keep_their_content_type(client):
    assert client.get("/evidence/ev_01/file").headers["content-type"] == "image/jpeg"


def test_one_account_cannot_see_another_accounts_shipment(client):
    from app.seed import PS_1042_TERMS

    buyer_a = {"X-Demo-Role": "Buyer", "X-User-Id": "buyer-a", "X-User-Name": "Alex Vance"}
    buyer_b = {"X-Demo-Role": "Buyer", "X-User-Id": "buyer-b", "X-User-Name": "Blair Cole"}
    supplier = {
        "X-Demo-Role": "Supplier",
        "X-User-Id": "supplier-ferro",
        "X-User-Name": "Ferro Precision Works",
    }
    other_supplier = {
        "X-Demo-Role": "Supplier",
        "X-User-Id": "supplier-other",
        "X-User-Name": "Other Works",
    }
    created = client.post(
        "/shipments",
        headers=buyer_a,
        json={
            "title": "Private lot",
            "supplier": "Ferro Precision Works",
            "terms": PS_1042_TERMS.model_dump(mode="json"),
        },
    )
    assert created.status_code == 201, created.text
    shipment_id = created.json()["id"]
    assert created.json()["buyer"] == "Alex Vance"

    assert client.get(f"/shipments/{shipment_id}", headers=buyer_a).status_code == 200
    assert shipment_id in {row["id"] for row in client.get("/shipments", headers=buyer_a).json()}
    # The shared demo seed is not this account's data.
    assert "PS-1042" not in {row["id"] for row in client.get("/shipments", headers=buyer_a).json()}

    assert client.get(f"/shipments/{shipment_id}", headers=buyer_b).status_code == 404
    assert shipment_id not in {row["id"] for row in client.get("/shipments", headers=buyer_b).json()}
    hidden = client.post(f"/shipments/{shipment_id}/agreement/approve", headers=buyer_b)
    assert hidden.status_code == 404

    assert client.get(f"/shipments/{shipment_id}", headers=supplier).status_code == 200
    assert client.get(f"/shipments/{shipment_id}", headers=other_supplier).status_code == 404
    reviewer = {"X-Demo-Role": "Reviewer", "X-User-Id": "reviewer-1", "X-User-Name": "Riley"}
    assert client.get(f"/shipments/{shipment_id}", headers=reviewer).status_code == 404
