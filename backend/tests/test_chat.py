from app.seed import PS_1042_TERMS

BUYER, SUPPLIER, REVIEWER = ({"X-Demo-Role": r} for r in ("Buyer", "Supplier", "Reviewer"))

BUYER_A = {"X-Demo-Role": "Buyer", "X-User-Id": "buyer-a", "X-User-Name": "Alex Vance"}
BUYER_B = {"X-Demo-Role": "Buyer", "X-User-Id": "buyer-b", "X-User-Name": "Blair Cole"}
FERRO = {"X-Demo-Role": "Supplier", "X-User-Id": "supplier-ferro", "X-User-Name": "Ferro Precision Works"}
OTHER_SUPPLIER = {"X-Demo-Role": "Supplier", "X-User-Id": "supplier-other", "X-User-Name": "Other Works"}


def send(client, id, role, body):
    return client.post(f"/shipments/{id}/messages", headers=role, json={"body": body})


def thread(client, id, role):
    res = client.get(f"/shipments/{id}/messages", headers=role)
    assert res.status_code == 200, res.text
    return res.json()


def private_shipment(client):
    res = client.post(
        "/shipments",
        headers=BUYER_A,
        json={
            "title": "Private lot",
            "supplier": "Ferro Precision Works",
            "terms": PS_1042_TERMS.model_dump(mode="json"),
        },
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


def test_new_shipment_has_an_empty_thread(client):
    assert thread(client, "PS-1042", BUYER) == []


def test_buyer_and_supplier_talk_in_order(client):
    first = send(client, "PS-1042", BUYER, "  Unit #063 looks like a lighting issue to me.  ")
    assert first.status_code == 201, first.text
    msg = first.json()
    assert msg["body"] == "Unit #063 looks like a lighting issue to me."  # trimmed
    assert msg["authorRole"] == "Buyer"
    assert msg["shipmentId"] == "PS-1042"
    assert msg["mine"] is True
    assert msg["id"].startswith("msg_")
    assert msg["at"].endswith("Z")

    assert send(client, "PS-1042", SUPPLIER, "Agreed, we can re-shoot it.").status_code == 201

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
    res = send(client, "PS-1031", REVIEWER, "Noted.")
    assert res.status_code == 403
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


def test_only_the_two_parties_see_a_private_thread(client):
    id = private_shipment(client)
    assert send(client, id, BUYER_A, "When does it ship?").status_code == 201
    reply = send(client, id, FERRO, "Friday.")
    assert reply.status_code == 201
    assert reply.json()["authorName"] == "Ferro Precision Works"

    as_buyer = thread(client, id, BUYER_A)
    assert [(m["authorName"], m["mine"]) for m in as_buyer] == [("Alex Vance", True), ("Ferro Precision Works", False)]

    # Another buyer, another supplier, and a reviewer (not disputed) can't read or write it.
    for outsider in (BUYER_B, OTHER_SUPPLIER, {"X-Demo-Role": "Reviewer", "X-User-Id": "reviewer-1"}):
        assert client.get(f"/shipments/{id}/messages", headers=outsider).status_code == 404
        assert send(client, id, outsider, "let me in").status_code == 404
    assert len(thread(client, id, BUYER_A)) == 2


def test_messages_do_not_touch_the_audit_chain(client):
    before = client.get("/shipments/PS-1042", headers=BUYER).json()
    send(client, "PS-1042", BUYER, "Chat is not evidence.")
    after = client.get("/shipments/PS-1042", headers=BUYER).json()
    assert after["events"] == before["events"]
    assert after["status"] == before["status"]
    assert client.get("/shipments/PS-1042/audit", headers=BUYER).json()["verified"] is True


def test_reset_clears_messages(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "dev_mode", True)
    send(client, "PS-1042", BUYER, "temporary")
    assert client.post("/dev/reset").status_code == 200
    assert thread(client, "PS-1042", BUYER) == []
