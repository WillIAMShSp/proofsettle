"""Buyer ↔ Supplier chat on a shipment (ported from main's feat/chat, on this branch's accounts)."""

from tests.test_writes import NEW, ok

# No user or email: no identity, like a dev login, so these see every shipment.
BUYER, SUPPLIER, REVIEWER = ({"X-Demo-Role": r} for r in ("Buyer", "Supplier", "Reviewer"))

BUYER_A = {
    "X-Demo-Role": "Buyer",
    "X-Demo-User": "buyer-a",
    "X-Demo-Email": "a@northgate.example",
    "X-Demo-Name": "Alex Vance",
}
BUYER_B = {
    "X-Demo-Role": "Buyer",
    "X-Demo-User": "buyer-b",
    "X-Demo-Email": "b@northgate.example",
    "X-Demo-Name": "Blair Cole",
}
FERRO = {
    "X-Demo-Role": "Supplier",
    "X-Demo-User": "ferro",
    "X-Demo-Email": "ops@ferro.example",
    "X-Demo-Name": "Ferro Precision Works",
}
OTHER_SUPPLIER = {
    "X-Demo-Role": "Supplier",
    "X-Demo-User": "other",
    "X-Demo-Email": "ops@other.example",
    "X-Demo-Name": "Other Works",
}
REVIEWER_1 = {"X-Demo-Role": "Reviewer", "X-Demo-User": "rev-1", "X-Demo-Email": "rev@proofsettle.example"}


def send(client, id, role, body):
    return client.post(f"/shipments/{id}/messages", headers=role, json={"body": body})


def thread(client, id, role):
    return ok(client.get(f"/shipments/{id}/messages", headers=role))


def private_shipment(client):
    """Created by BUYER_A and sent to FERRO's account email."""
    return ok(client.post("/shipments", headers=BUYER_A, json=NEW | {"recipientEmail": "ops@ferro.example"}), 201)["id"]


def test_new_shipment_has_an_empty_thread(client):
    assert thread(client, "PS-1042", BUYER) == []


def test_buyer_and_supplier_talk_in_order(client):
    first = send(client, "PS-1042", BUYER, "  Unit #063 looks like a lighting issue to me.  ")
    msg = ok(first, 201)
    assert msg["body"] == "Unit #063 looks like a lighting issue to me."  # trimmed
    assert msg["authorRole"] == "Buyer"
    assert msg["shipmentId"] == "PS-1042"
    assert msg["mine"] is True
    assert msg["id"].startswith("msg_")
    assert msg["at"].endswith("Z")

    ok(send(client, "PS-1042", SUPPLIER, "Agreed, we can re-shoot it."), 201)

    as_buyer = thread(client, "PS-1042", BUYER)
    assert [m["body"] for m in as_buyer] == [
        "Unit #063 looks like a lighting issue to me.",
        "Agreed, we can re-shoot it.",
    ]
    assert [m["mine"] for m in as_buyer] == [True, False]
    assert [m["mine"] for m in thread(client, "PS-1042", SUPPLIER)] == [False, True]


def test_threads_are_per_shipment(client):
    send(client, "PS-1042", BUYER, "About 1042")
    assert thread(client, "PS-1038", BUYER) == []


def test_reviewer_reads_but_cannot_send(client):
    send(client, "PS-1031", SUPPLIER, "Bracket #101 is a weld seam.")
    assert [m["body"] for m in thread(client, "PS-1031", REVIEWER)] == ["Bracket #101 is a weld seam."]
    assert send(client, "PS-1031", REVIEWER, "Noted.").status_code == 403
    assert len(thread(client, "PS-1031", REVIEWER)) == 1


def test_blank_or_long_messages_are_rejected(client):
    assert send(client, "PS-1042", BUYER, "   ").status_code == 422
    assert send(client, "PS-1042", BUYER, "x" * 2001).status_code == 422
    assert client.post("/shipments/PS-1042/messages", headers=BUYER, json={}).status_code == 422
    extra = client.post("/shipments/PS-1042/messages", headers=BUYER, json={"body": "hi", "authorRole": "Reviewer"})
    assert extra.status_code == 422
    assert thread(client, "PS-1042", BUYER) == []


def test_unknown_shipment_is_404(client):
    assert client.get("/shipments/PS-9999/messages", headers=BUYER).status_code == 404
    assert send(client, "PS-9999", BUYER, "hello").status_code == 404


def test_only_the_two_parties_talk_in_a_private_thread(client):
    id = private_shipment(client)
    ok(send(client, id, BUYER_A, "When does it ship?"), 201)
    reply = ok(send(client, id, FERRO, "Friday."), 201)
    assert reply["authorName"] == "Ferro Precision Works"

    as_buyer = thread(client, id, BUYER_A)
    assert [(m["authorName"], m["mine"]) for m in as_buyer] == [("Alex Vance", True), ("Ferro Precision Works", False)]
    assert [m["mine"] for m in thread(client, id, FERRO)] == [False, True]

    # Another buyer or supplier can neither read nor write it: to them it doesn't exist.
    for outsider in (BUYER_B, OTHER_SUPPLIER):
        assert client.get(f"/shipments/{id}/messages", headers=outsider).status_code == 404
        assert send(client, id, outsider, "let me in").status_code == 404
    # A Reviewer sees every shipment (app.access), so reads the thread but can't post in it.
    assert len(thread(client, id, REVIEWER_1)) == 2
    assert send(client, id, REVIEWER_1, "Noted.").status_code == 403
    assert len(thread(client, id, BUYER_A)) == 2


def test_the_author_name_falls_back_to_the_email(client):
    id = private_shipment(client)
    nameless = {"X-Demo-Role": "Supplier", "X-Demo-User": "ferro", "X-Demo-Email": "ops@ferro.example"}
    assert ok(send(client, id, nameless, "Hi"), 201)["authorName"] == "ops@ferro.example"


def test_messages_do_not_touch_the_audit_chain(client):
    before = ok(client.get("/shipments/PS-1042", headers=BUYER))
    send(client, "PS-1042", BUYER, "Chat is not evidence.")
    after = ok(client.get("/shipments/PS-1042", headers=BUYER))
    assert after["events"] == before["events"]
    assert after["status"] == before["status"]
    assert ok(client.get("/shipments/PS-1042/audit", headers=BUYER))["verified"] is True


def test_reset_clears_messages(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "dev_mode", True)
    send(client, "PS-1042", BUYER, "temporary")
    assert client.post("/dev/reset").status_code == 200
    assert thread(client, "PS-1042", BUYER) == []


# --- Invoices -----------------------------------------------------------------------------


def invoice(client, id, role, **body):
    return client.post(f"/shipments/{id}/messages/invoice", headers=role, json=body or None)


def test_the_manufacturer_sends_an_invoice_before_settlement(client):
    d = ok(invoice(client, "PS-1038", SUPPLIER), 201)  # In Transit: terms agreed, not settled
    inv = d["invoice"]
    assert inv["number"] == "INV-PS-1038-01"
    assert (inv["quantity"], inv["unitPrice"], inv["subtotal"]) == (40, 160, 6400)
    assert inv["final"] is False and inv["credit"] is None and inv["amountDue"] == 6400
    assert inv["seller"] == "Kestrel Fluid Systems" and inv["buyer"] == "Northgate Assembly Ltd"
    assert inv["status"] == "In Transit"
    terms_hash = ok(client.get("/shipments/PS-1038", headers=BUYER))["agreement"]["termsHash"]
    assert inv["termsHash"] == terms_hash
    assert d["body"] == "Invoice INV-PS-1038-01: $6,400 due"
    assert d["authorRole"] == "Supplier"

    # The buyer sees it in the thread; the next one gets the next number.
    assert [m["invoice"]["number"] for m in thread(client, "PS-1038", BUYER)] == ["INV-PS-1038-01"]
    assert ok(invoice(client, "PS-1038", SUPPLIER, note="Revised copy"), 201)["body"] == "Revised copy"
    numbers = [m["invoice"]["number"] for m in thread(client, "PS-1038", BUYER) if m["invoice"]]
    assert numbers == ["INV-PS-1038-01", "INV-PS-1038-02"]


def test_a_settled_invoice_charges_the_settlement_amount(client):
    adj = ok(client.get("/shipments/PS-1031", headers=BUYER))["adjustment"]  # Resolved
    inv = ok(invoice(client, "PS-1031", SUPPLIER), 201)["invoice"]
    assert inv["final"] is True
    assert inv["credit"] == adj["credit"]
    assert inv["amountDue"] == adj["settlementAmount"]
    assert inv["amountDue"] == inv["subtotal"] - inv["credit"]


def test_a_sent_invoice_is_a_snapshot(client):
    before = ok(invoice(client, "PS-1042", SUPPLIER), 201)["invoice"]  # Proposed: not final
    ok(client.post("/shipments/PS-1042/accept", headers=BUYER))
    ok(client.post("/shipments/PS-1042/accept", headers=SUPPLIER))  # now Accepted
    (first,) = (m["invoice"] for m in thread(client, "PS-1042", BUYER) if m["invoice"])
    assert first == before and first["final"] is False and first["amountDue"] == 10000
    settled = ok(invoice(client, "PS-1042", SUPPLIER), 201)["invoice"]
    assert settled["final"] is True and settled["amountDue"] < 10000
    assert settled["number"] == "INV-PS-1042-02"


def test_only_the_manufacturer_invoices(client):
    assert invoice(client, "PS-1038", BUYER).status_code == 403
    assert invoice(client, "PS-1038", REVIEWER).status_code == 403
    assert [m for m in thread(client, "PS-1038", BUYER) if m["invoice"]] == []


def test_no_invoice_before_both_parties_approve(client):
    id = private_shipment(client)  # Draft
    res = invoice(client, id, FERRO)
    assert res.status_code == 409
    assert "approve" in res.json()["detail"]


def test_an_invoice_takes_no_amount_from_the_caller(client):
    for extra in ({"amountDue": 1}, {"credit": 9999}, {"note": "hi", "subtotal": 1}):
        assert invoice(client, "PS-1038", SUPPLIER, **extra).status_code == 422
    assert invoice(client, "PS-1038", SUPPLIER, note=" ").status_code == 422
    assert thread(client, "PS-1038", BUYER) == []


def test_a_private_invoice_reaches_only_the_connected_accounts(client):
    id = private_shipment(client)
    ok(client.post(f"/shipments/{id}/agreement/approve", headers=BUYER_A))
    ok(client.post(f"/shipments/{id}/agreement/approve", headers=FERRO))
    sent = ok(invoice(client, id, FERRO), 201)
    assert sent["authorName"] == "Ferro Precision Works" and sent["mine"] is True
    received = thread(client, id, BUYER_A)
    assert [(m["invoice"]["number"], m["mine"]) for m in received] == [(f"INV-{id}-01", False)]
    for outsider in (BUYER_B, OTHER_SUPPLIER):
        assert client.get(f"/shipments/{id}/messages", headers=outsider).status_code == 404
        assert invoice(client, id, outsider).status_code == 404


def test_an_invoice_does_not_touch_the_audit_chain(client):
    before = ok(client.get("/shipments/PS-1038", headers=BUYER))
    ok(invoice(client, "PS-1038", SUPPLIER), 201)
    after = ok(client.get("/shipments/PS-1038", headers=BUYER))
    assert after["events"] == before["events"] and after["status"] == before["status"]
    assert ok(client.get("/shipments/PS-1038/audit", headers=BUYER))["verified"] is True
