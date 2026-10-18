"""app.chain without a network: the IDL codec, and the plan of program instructions."""

import base64
import hashlib

import pytest
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from app.audit import ANCHORED_EVENT_TYPES, EventType
from app.chain.anchoring import cents, expected_state, plan
from app.chain.codec import CodecError, load_idl
from app.chain.program import CHAIN_STATUS, Chain, Signer
from app.chain.rpc import SolanaRpc, TransactionFailed
from app.hashing import to_chain_bytes
from app.models import Shipment
from app.routes import _load
from app.workflow import Status

IDL = load_idl()


def make_chain(**kw: object) -> Chain:
    keys = {s: Keypair() for s in Signer}
    return Chain(SolanaRpc("http://127.0.0.1:1"), keys, **kw)  # type: ignore[arg-type]


# --- codec ---------------------------------------------------------------------------------


def test_discriminators_are_anchors_default():
    for name, ix in IDL.instructions.items():
        assert bytes(ix["discriminator"]) == hashlib.sha256(f"global:{name}".encode()).digest()[:8]
    for name, disc in IDL.accounts.items():
        assert disc == hashlib.sha256(f"account:{name}".encode()).digest()[:8]
    for disc, name in IDL.events.items():
        assert disc == hashlib.sha256(f"event:{name}".encode()).digest()[:8]


def test_shipment_layout_round_trips():
    fields = IDL.types["Shipment"]["fields"]
    sample = {}
    for i, f in enumerate(fields):
        ty = f["type"]
        if ty == "pubkey":
            sample[f["name"]] = Keypair().pubkey()
        elif ty == "bool":
            sample[f["name"]] = i % 2 == 0
        elif isinstance(ty, dict) and "array" in ty:
            sample[f["name"]] = bytes([i]) * ty["array"][1]
        elif isinstance(ty, dict) and "defined" in ty:
            sample[f["name"]] = "Proposed"
        else:
            sample[f["name"]] = i
    data = IDL.accounts["Shipment"] + IDL.encode({"defined": {"name": "Shipment"}}, sample)
    assert IDL.decode_account("Shipment", data) == sample
    with pytest.raises(CodecError):
        IDL.decode_account("Evidence", data)
    with pytest.raises(CodecError):
        IDL.decode_account("Shipment", data[:-1])


def test_instruction_follows_the_idl_account_order_and_flags():
    pid, shipment, party = Keypair().pubkey(), Keypair().pubkey(), Keypair().pubkey()
    ix = IDL.instruction(
        "dispute_adjustment", {"shipment": shipment, "party": party}, {"reason_hash": b"\x07" * 32}, pid
    )
    assert ix.program_id == pid
    assert [(m.pubkey, m.is_signer, m.is_writable) for m in ix.accounts] == [
        (shipment, False, True),
        (party, True, False),
    ]
    assert ix.data == bytes(IDL.instructions["dispute_adjustment"]["discriminator"]) + b"\x07" * 32

    ix = IDL.instruction(
        "record_evidence",
        {"shipment": shipment, "evidence": party, "uploader": pid},
        {"kind": "Receipt", "sha256": b"\x01" * 32},
        pid,
    )
    assert str(ix.accounts[-1].pubkey) == "11111111111111111111111111111111"  # system program, from the IDL
    assert ix.data[8] == 1  # EvidenceKind::Receipt


def test_instruction_rejects_wrong_accounts_and_args():
    pid, key = Keypair().pubkey(), Keypair().pubkey()
    with pytest.raises(CodecError, match="missing account party"):
        IDL.instruction("accept_adjustment", {"shipment": key}, {}, pid)
    with pytest.raises(CodecError, match="unknown accounts"):
        IDL.instruction("accept_adjustment", {"shipment": key, "party": key, "buyer": key}, {}, pid)
    with pytest.raises(CodecError, match="expected args"):
        IDL.instruction("accept_adjustment", {"shipment": key, "party": key}, {"x": 1}, pid)
    with pytest.raises(CodecError, match="32 bytes"):
        IDL.instruction("dispute_adjustment", {"shipment": key, "party": key}, {"reason_hash": b"short"}, pid)


def test_events_are_read_only_from_the_programs_own_frames():
    pid, other = IDL.address, Keypair().pubkey()
    payload = {"shipment": Keypair().pubkey(), "seq": 7, "timestamp": 1}
    data = base64.b64encode(
        bytes(next(e["discriminator"] for e in IDL.raw["events"] if e["name"] == "ShipmentDispatched"))
        + IDL.encode({"defined": {"name": "ShipmentDispatched"}}, payload)
    ).decode()
    logs = [
        f"Program {other} invoke [1]",
        f"Program data: {data}",  # another program's frame: ignored
        f"Program {other} success",
        f"Program {pid} invoke [1]",
        "Program 11111111111111111111111111111111 invoke [2]",
        f"Program data: {data}",  # the system program's frame: ignored
        "Program 11111111111111111111111111111111 success",
        f"Program data: {data}",
        "Program data: bm90IGFuIGV2ZW50",  # not an event
        f"Program {pid} success",
    ]
    assert IDL.events_in_logs(logs, pid) == [("ShipmentDispatched", payload)]


def test_program_error_name_from_logs():
    err = TransactionFailed("x", ("Program log: AnchorError occurred. Error Code: InvalidStatus. Error Number: 6001.",))
    assert err.program_error == "InvalidStatus"
    assert TransactionFailed("x").program_error is None


# --- addresses and keys --------------------------------------------------------------------


def test_chain_requires_four_distinct_keys():
    kp = Keypair()
    with pytest.raises(ValueError, match="distinct"):
        Chain(SolanaRpc("http://x"), {s: kp for s in Signer})
    with pytest.raises(ValueError, match="all required"):
        Chain(SolanaRpc("http://x"), {Signer.BUYER: kp})


def test_salt_changes_the_shipment_address_only_when_set(db):
    s = db.get(Shipment, "PS-1042")
    plain, salted = make_chain(), make_chain(shipment_salt="run-2")
    assert plain.seed(s.chain_uuid) == s.chain_uuid.bytes
    assert salted.seed(s.chain_uuid) != s.chain_uuid.bytes
    pda, bump_ok = Pubkey.find_program_address([b"shipment", s.chain_uuid.bytes], IDL.address)
    assert plain.shipment_pda(plain.seed(s.chain_uuid)) == pda and bump_ok


def test_cents_is_exact():
    assert cents(10000) == 1_000_000
    assert cents(99.99) == 9999
    assert cents("0.1") == 10
    with pytest.raises(ValueError):
        cents("1.005")


# --- the plan ------------------------------------------------------------------------------


def _ops(db, shipment_id):
    s = _load(db, shipment_id)
    steps = plan(s, make_chain())
    return s, steps, [op for st in steps for op in st.ops]


def test_seeded_histories_map_to_program_instructions(db):
    _, steps, ops = _ops(db, "PS-1042")
    assert [op.ix for op in ops] == [
        "create_shipment",
        "approve_agreement",
        "approve_agreement",
        *["record_evidence"] * 4,
        "mark_in_transit",
        *["record_evidence"] * 4,
        "propose_adjustment",
    ]
    assert [op.signer for op in ops[1:3]] == [Signer.BUYER, Signer.SUPPLIER]
    # Each anchored event type has instructions, and only those do.
    for st in steps:
        assert bool(st.ops) == (st.event.type in ANCHORED_EVENT_TYPES)

    _, _, ops = _ops(db, "PS-1031")
    assert [op.ix for op in ops][-2:] == ["dispute_adjustment", "resolve_dispute"]
    assert ops[-2].signer is Signer.SUPPLIER and ops[-1].signer is Signer.REVIEWER


def test_create_carries_the_agreed_rule(db):
    s, _, ops = _ops(db, "PS-1031")
    params = ops[0].args["params"]
    assert params["terms_hash"] == to_chain_bytes(s.agreement.terms_hash)
    assert (params["invoice_amount_cents"], params["quantity"]) == (375_000, 250)
    assert (params["credit_per_defect_cents"], params["max_adjustment_cents"]) == (1_500, 75_000)
    assert params["defect_tolerance_units"] == 1
    assert (params["min_dispatch_evidence"], params["min_receipt_evidence"]) == (4, 4)


@pytest.mark.parametrize("shipment_id", ["PS-1042", "PS-1038", "PS-1031"])
def test_the_on_chain_rule_reproduces_the_engine(db, shipment_id):
    """Replaying the plan with the program's rules lands where the database is."""
    s, _, ops = _ops(db, shipment_id)
    want = expected_state(ops, s.agreement.parsed_terms())
    assert CHAIN_STATUS[want.status] is s.status
    if s.adjustment:
        credit = cents(s.adjustment.credit)
        if s.status is Status.RESOLVED:
            assert want.final_adjustment_cents == credit
        else:
            assert want.proposed_adjustment_cents == credit
    evidence = [(e.kind.value.capitalize(), to_chain_bytes(e.sha256)) for e in s.evidence]
    assert want.evidence == evidence


def test_ps_1031_needs_the_tolerance(db):
    """3 findings, 1 rejected, tolerance 1: the engine credits (2 - 1) x $15."""
    s, _, ops = _ops(db, "PS-1031")
    assert ops[-1].args["confirmed_defects"] == 2
    assert expected_state(ops, s.agreement.parsed_terms()).final_adjustment_cents == 1_500


def test_unknown_event_shapes_are_refused(db):
    from app.chain.anchoring import UnmappedEvent

    s = _load(db, "PS-1038")
    event = next(e for e in s.events if e.type == EventType.STATUS_CHANGED)
    event.payload = {"status": {"from": "In Transit", "to": "Inspection"}}
    with pytest.raises(UnmappedEvent):
        plan(s, make_chain())
