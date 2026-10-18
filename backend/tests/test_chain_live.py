"""Anchoring against a real validator running the ProofSettle program.

Skipped unless PROOFSETTLE_TEST_SOLANA_RPC points at one, e.g. a local Surfpool started
from the repo root after `anchor build` (it deploys target/deploy/proofsettle.so):

    surfpool start --no-tui --yes --offline
    PROOFSETTLE_TEST_SOLANA_RPC=http://127.0.0.1:8899 uv run pytest tests/test_chain_live.py

Each test uses fresh keys and a fresh shipment salt, so runs never collide on-chain.
"""

import os
import time
import uuid
from collections.abc import Iterator

import pytest
from solders.keypair import Keypair
from sqlalchemy.orm import Session

from app.chain import set_chain
from app.chain.anchoring import anchor_all, anchor_shipment, check_shipment, load_shipment, shipment_address
from app.chain.program import CHAIN_STATUS, Chain, Signer
from app.chain.rpc import SolanaRpc
from app.hashing import sha256_hex
from app.models import AuditEvent, ChainStatus, Evidence
from app.routes import evidence_store
from app.storage import LocalStore
from app.workflow import Status

RPC_URL = os.environ.get("PROOFSETTLE_TEST_SOLANA_RPC", "")
pytestmark = pytest.mark.skipif(not RPC_URL, reason="PROOFSETTLE_TEST_SOLANA_RPC is not set")

BUYER = {"X-Demo-Role": "Buyer"}
SUPPLIER = {"X-Demo-Role": "Supplier"}
REVIEWER = {"X-Demo-Role": "Reviewer"}


def _airdrop(rpc: SolanaRpc, kp: Keypair) -> None:
    sig = rpc.call("requestAirdrop", [str(kp.pubkey()), 2_000_000_000, {"commitment": "confirmed"}])
    for _ in range(60):
        status = rpc.call("getSignatureStatuses", [[sig]])["value"][0]
        if status and status.get("confirmationStatus") in ("confirmed", "finalized"):
            return
        time.sleep(0.25)
    raise RuntimeError("airdrop not confirmed")


@pytest.fixture
def chain() -> Iterator[Chain]:
    rpc = SolanaRpc(RPC_URL)
    keys = {s: Keypair() for s in Signer}
    for kp in keys.values():
        _airdrop(rpc, kp)
    c = Chain(rpc, keys, shipment_salt=uuid.uuid4().hex, explorer_cluster="custom")
    set_chain(c)
    yield c
    set_chain(None)


def _events(db: Session, shipment_id: str) -> list[AuditEvent]:
    s = load_shipment(db, shipment_id)
    assert s is not None
    return list(s.events)


def _assert_fully_anchored(db: Session, shipment_id: str, chain: Chain) -> dict:
    s = load_shipment(db, shipment_id)
    assert s is not None
    for e in s.events:
        if e.chain_status is ChainStatus.SKIPPED:
            assert e.type in ("inspection.completed", "finding.reviewed")
        else:
            assert e.chain_status is ChainStatus.CONFIRMED, (e.public_id, e.type, e.chain_status)
            assert e.chain_tx_hash and len(e.chain_tx_hash) >= 64
    report = check_shipment(s, chain)
    assert report.available and report.mismatches == (), report.mismatches
    state = chain.fetch_shipment(shipment_address(s, chain))
    assert state is not None and CHAIN_STATUS[state["status"]] is s.status
    return state


def test_seeded_history_is_anchored_and_matches(db, chain):
    results = anchor_all(db, chain)
    assert sorted(r.shipment_id for r in results) == ["PS-1031", "PS-1038", "PS-1042"]
    assert all(r.error is None for r in results), [r.error for r in results]

    state = _assert_fully_anchored(db, "PS-1042", chain)
    assert state["proposed_adjustment_cents"] == 30_000
    assert state["evidence_count"] == 8

    _assert_fully_anchored(db, "PS-1038", chain)

    state = _assert_fully_anchored(db, "PS-1031", chain)
    assert state["defect_tolerance_units"] == 1
    assert state["final_adjustment_cents"] == 1_500  # (2 - 1 tolerated) x $15

    # Anchoring again is a no-op.
    assert [(r.sent, r.confirmed) for r in anchor_all(db, chain)] == []


def test_api_writes_are_anchored_and_both_parties_must_accept(client, db, chain):
    d = client.post("/shipments/PS-1042/accept", headers=BUYER).json()
    assert d["chain"]["address"] == str(shipment_address(load_shipment(db, "PS-1042"), chain))
    state = _assert_fully_anchored(db, "PS-1042", chain)
    assert state["buyer_accepted"] and not state["supplier_accepted"]
    assert CHAIN_STATUS[state["status"]] is Status.PROPOSED

    client.post("/shipments/PS-1042/accept", headers=SUPPLIER)
    state = _assert_fully_anchored(db, "PS-1042", chain)
    assert CHAIN_STATUS[state["status"]] is Status.ACCEPTED
    assert state["final_adjustment_cents"] == 30_000

    v = client.post("/shipments/PS-1042/audit/verify", headers=BUYER).json()
    assert v["verified"] is True
    assert v["chain"]["available"] is True and v["chain"]["mismatches"] == []
    assert v["chain"]["anchored"] == sum(1 for e in _events(db, "PS-1042") if e.chain_status is ChainStatus.CONFIRMED)

    detail = client.get("/shipments/PS-1042", headers=BUYER).json()
    accepted = [e for e in detail["events"] if e["type"] == "adjustment.accepted"]
    assert len(accepted) == 2 and all(e["chainStatus"] == "confirmed" and e["txHash"] for e in accepted)


def test_buyer_dispute_and_reviewer_resolution_are_anchored(client, db, chain):
    assert (
        client.post("/shipments/PS-1042/dispute", headers=BUYER, json={"reason": "Two units arrived bent"}).status_code
        == 200
    )
    detail = client.get("/shipments/PS-1042", headers=REVIEWER).json()
    for f in detail["adjustment"]["needsReview"]:
        client.post(f"/findings/{f['findingId']}/review", headers=REVIEWER, json={"decision": "confirmed"})
    assert client.post("/shipments/PS-1042/resolve", headers=REVIEWER).status_code == 200

    state = _assert_fully_anchored(db, "PS-1042", chain)
    credit = client.get("/shipments/PS-1042", headers=BUYER).json()["adjustment"]["credit"]
    assert CHAIN_STATUS[state["status"]] is Status.RESOLVED
    assert state["final_adjustment_cents"] == round(credit * 100)
    assert state["reviewer"] == chain.pubkey(Signer.REVIEWER)


def test_lost_signatures_are_recovered_without_resending(db, chain):
    anchor_shipment(db, "PS-1038", chain)
    before = {e.id: e.chain_tx_hash for e in _events(db, "PS-1038")}
    for e in _events(db, "PS-1038"):
        if e.chain_status is ChainStatus.CONFIRMED:
            e.chain_status, e.chain_tx_hash = ChainStatus.PENDING, None
    db.commit()

    result = anchor_shipment(db, "PS-1038", chain)
    assert result.error is None and result.sent == 0 and result.confirmed > 0
    assert {e.id: e.chain_tx_hash for e in _events(db, "PS-1038")} == before


def test_an_unreachable_rpc_fails_softly_and_is_retried(db, chain):
    down = Chain(SolanaRpc("http://127.0.0.1:1", timeout=1), chain.keys, shipment_salt=chain.shipment_salt)
    result = anchor_shipment(db, "PS-1038", down)
    assert result.error is not None and result.sent == 0
    s = load_shipment(db, "PS-1038")
    assert check_shipment(s, down).available is False

    result = anchor_shipment(db, "PS-1038", chain)
    assert result.error is None
    _assert_fully_anchored(db, "PS-1038", chain)


def test_a_swapped_photo_is_caught_by_the_chain(client, db, chain, seeded):
    """Swap a file and its stored hash together: local re-hashing still passes, the chain doesn't."""
    anchor_shipment(db, "PS-1038", chain)
    ev = db.get(Evidence, "ev_09")
    files = seeded[1]
    forged = b"\xff\xd8\xff" + b"a different photo"
    (files / ev.file_name).write_bytes(forged)
    ev.sha256 = sha256_hex(forged)
    db.commit()
    client.app.dependency_overrides[evidence_store] = lambda: LocalStore(files)

    v = client.post("/shipments/PS-1038/audit/verify", headers=BUYER).json()
    assert all(item["ok"] for item in v["evidence"])  # the local check alone is fooled
    assert v["chain"]["available"] is True
    assert any("ev_09" in m for m in v["chain"]["mismatches"])
    assert v["verified"] is False


def test_another_deployments_record_is_reported_as_diverged(db, chain):
    anchor_shipment(db, "PS-1038", chain)
    impostor_keys = {s: Keypair() for s in Signer}
    other = Chain(chain.rpc, impostor_keys, shipment_salt=chain.shipment_salt)
    result = anchor_shipment(db, "PS-1038", other)
    assert result.error and "diverged" in result.error
    report = check_shipment(load_shipment(db, "PS-1038"), other)
    assert any("buyer differs" in m for m in report.mismatches)
