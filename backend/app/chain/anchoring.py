"""Mirror each shipment's audit trail onto the Solana program, and check it against the chain.

The database stays the source of truth (CHAIN_ALIGNMENT.md §5): a write commits first, then
anchor_shipment sends the program instructions that event implies and stores the signature
in the event's chain_tx_hash. If the RPC is unreachable the workflow carries on and the event
stays pending/failed; the next anchoring run picks it up.

Every program instruction bumps the shipment's on-chain audit_seq by exactly one, and each
event's instructions are derived only from the event's own (hash-chained) payload and the
immutable agreement. So the full list of instructions for a shipment is a pure function of
its history, and the on-chain audit_seq says how many of them have been applied. Anchoring
sends the rest, in order; that makes it safe to retry, to resume half-sent uploads, and to
recover a signature that was sent but never recorded.
"""

import hashlib
import logging
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from solders.pubkey import Pubkey
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.audit import ANCHORED_EVENT_TYPES, EventType
from app.chain import get_chain
from app.chain.program import CHAIN_STATUS, MAX_OPS_PER_TX, Chain, Op, Signer
from app.chain.rpc import RpcError, TransactionFailed
from app.hashing import hash_json, to_chain_bytes
from app.models import AuditEvent, ChainStatus, EvidenceKind, Shipment
from app.settlement import compute_adjustment
from app.terms import AgreementTerms
from app.workflow import Actor, Status

log = logging.getLogger(__name__)

_PARTY_SIGNER = {Actor.BUYER: Signer.BUYER, Actor.SUPPLIER: Signer.SUPPLIER}
_KIND = {EvidenceKind.DISPATCH.value: "Dispatch", EvidenceKind.RECEIPT.value: "Receipt"}


class UnmappedEvent(ValueError):
    """An event whose payload this module can't turn into program instructions."""


def cents(amount: Decimal | float | str) -> int:
    """Dollars (at most 2 dp) -> integer cents, exactly. JSON floats go through str()."""
    value = Decimal(str(amount)) * 100
    if value != value.to_integral_value():
        raise ValueError(f"{amount} has more than 2 decimal places")
    return int(value)


def sha256(text: str) -> bytes:
    return hashlib.sha256(text.encode("utf-8")).digest()


# --- the plan: events -> program instructions ----------------------------------------------


@dataclass(frozen=True)
class Step:
    """One audit event and the instructions it implies (none for unanchored types)."""

    event: AuditEvent
    ops: tuple[Op, ...]
    # Values the program must arrive at, read back after the last op (field -> value).
    expect: tuple[tuple[str, Any], ...] = ()


def plan(s: Shipment, chain: Chain) -> list[Step]:
    if s.agreement is None:
        raise UnmappedEvent(f"{s.id} has no agreement")
    terms = s.agreement.parsed_terms()
    findings_hash: str | None = None
    steps = []
    for e in s.events:
        ops, expect = _ops(e, s, terms, chain, findings_hash)
        if e.type == EventType.INSPECTION_COMPLETED:
            findings_hash = e.payload["findingsHash"]
        steps.append(Step(e, tuple(ops), tuple(expect)))
    return steps


def _ops(
    e: AuditEvent, s: Shipment, terms: AgreementTerms, chain: Chain, findings_hash: str | None
) -> tuple[list[Op], list[tuple[str, Any]]]:
    p = e.payload
    to = (p.get("status") or {}).get("to")
    match e.type:
        case EventType.AGREEMENT_DRAFTED:
            assert s.agreement is not None
            reqs, rule = terms.evidence_requirements, terms.compensation
            params = {
                "supplier": chain.pubkey(Signer.SUPPLIER),
                "authority": chain.pubkey(Signer.AUTHORITY),
                "reviewer": chain.pubkey(Signer.REVIEWER),
                "terms_hash": to_chain_bytes(s.agreement.terms_hash),
                "invoice_amount_cents": cents(terms.invoice_amount),
                "quantity": terms.quantity,
                "credit_per_defect_cents": cents(rule.amount_per_unit),
                "max_adjustment_cents": cents(rule.max_credit),
                "defect_tolerance_units": terms.acceptance.defect_tolerance_units,
                "min_dispatch_evidence": reqs.min_dispatch_photos,
                "min_receipt_evidence": reqs.min_receipt_photos,
            }
            return [Op("create_shipment", Signer.BUYER, {"params": params})], []
        case EventType.AGREEMENT_APPROVED:
            terms_hash = {"terms_hash": to_chain_bytes(p["termsHash"])}
            if "approvedBy" in p:  # one party (app.operations.approve_agreement)
                signer = _party(Actor(p["approvedBy"]), e)
                return [Op("approve_agreement", signer, terms_hash)], []
            if "buyerApprovedAt" in p and "supplierApprovedAt" in p:  # both at once (the seed)
                return [
                    Op("approve_agreement", Signer.BUYER, terms_hash),
                    Op("approve_agreement", Signer.SUPPLIER, terms_hash),
                ], []
        case EventType.EVIDENCE_UPLOADED:
            kind = _KIND[p["kind"]]
            uploader = Signer.SUPPLIER if kind == "Dispatch" else Signer.BUYER
            ops = [
                Op("record_evidence", uploader, {"kind": kind, "sha256": to_chain_bytes(ev["sha256"])}, evidence=True)
                for ev in p["evidence"]
            ]
            if to == Status.IN_TRANSIT.value:
                ops.append(Op("mark_in_transit", Signer.SUPPLIER, {}))
            elif to not in (None, Status.INSPECTION.value):  # Inspection follows on-chain by itself
                raise UnmappedEvent(f"{e.public_id}: evidence upload moving to {to}")
            return ops, [("status", to)] if to else []
        case EventType.STATUS_CHANGED:
            if to == Status.IN_TRANSIT.value:
                return [Op("mark_in_transit", Signer.SUPPLIER, {})], []
        case EventType.ADJUSTMENT_PROPOSED:
            if findings_hash is None:
                raise UnmappedEvent(f"{e.public_id}: proposal without a preceding inspection")
            args = {
                "confirmed_defects": p["confirmedDefects"],
                "findings_hash": to_chain_bytes(findings_hash),
                "explanation_hash": to_chain_bytes(p["adjustmentHash"]),
            }
            return [Op("propose_adjustment", Signer.AUTHORITY, args)], [
                ("proposed_adjustment_cents", cents(p["credit"]))
            ]
        case EventType.ADJUSTMENT_ACCEPTED:
            return [Op("accept_adjustment", _party(e.actor, e), {})], [("status", to)] if to else []
        case EventType.ADJUSTMENT_DISPUTED:
            return [Op("dispute_adjustment", _party(e.actor, e), {"reason_hash": sha256(p["reason"])})], []
        case EventType.DISPUTE_RESOLVED:
            args = {"confirmed_defects": p["confirmedDefects"], "resolution_hash": to_chain_bytes(p["adjustmentHash"])}
            return [Op("resolve_dispute", Signer.REVIEWER, args)], [("final_adjustment_cents", cents(p["credit"]))]
        case EventType.INSPECTION_COMPLETED | EventType.FINDING_REVIEWED:
            return [], []
    raise UnmappedEvent(f"{e.public_id}: no on-chain mapping for {e.type} with payload keys {sorted(p)}")


def _party(actor: Actor, e: AuditEvent) -> Signer:
    if actor not in _PARTY_SIGNER:
        raise UnmappedEvent(f"{e.public_id}: {actor} is not a party")
    return _PARTY_SIGNER[actor]


# --- anchoring -----------------------------------------------------------------------------


@dataclass
class AnchorResult:
    shipment_id: str
    sent: int = 0  # transactions sent in this run
    confirmed: int = 0  # events confirmed in this run (sent or recovered)
    error: str | None = None


_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock(shipment_id: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(shipment_id, threading.Lock())


def load_shipment(db: Session, shipment_id: str) -> Shipment | None:
    return db.scalars(
        select(Shipment)
        .where(Shipment.id == shipment_id)
        .options(
            selectinload(Shipment.agreement),
            selectinload(Shipment.evidence),
            selectinload(Shipment.findings),
            selectinload(Shipment.events),
            selectinload(Shipment.adjustment),
        )
        .execution_options(populate_existing=True)
    ).one_or_none()


def anchor_shipment(db: Session, shipment_id: str, chain: Chain) -> AnchorResult:
    """Send whatever part of the shipment's history isn't on-chain yet, oldest first.

    Commits after each event, so progress survives a failure later in the run. Stops at the
    first event that fails; it and everything after stay retryable.
    """
    with _lock(shipment_id):
        s = load_shipment(db, shipment_id)
        if s is None:
            return AnchorResult(shipment_id, error="unknown shipment")
        result = AnchorResult(shipment_id)
        try:
            _anchor(db, s, chain, result)
        except (RpcError, UnmappedEvent, ValueError) as e:
            result.error = str(e)
            log.warning("Anchoring %s stopped: %s", shipment_id, e)
        db.commit()
        return result


def _anchor(db: Session, s: Shipment, chain: Chain, result: AnchorResult) -> None:
    try:
        steps = plan(s, chain)
    except UnmappedEvent:
        _fail_open(s)
        raise
    seed = chain.seed(s.chain_uuid)
    pda = chain.shipment_pda(seed)
    state = chain.fetch_shipment(pda)
    applied = int(state["audit_seq"]) if state else 0
    total = sum(len(st.ops) for st in steps)

    problems = _identity_problems(state, s, chain, seed) if state else []
    if applied > total:
        problems.append(f"on-chain audit_seq {applied} is ahead of the {total} instructions this history implies")
    if problems:
        _fail_open(s)
        raise ValueError(f"{s.id} diverged from {pda}: {'; '.join(problems)}")

    recovered: dict[int, str] | None = None
    done = 0  # instructions before the current step
    for st in steps:
        e = st.event
        if not st.ops:
            if e.chain_status is not ChainStatus.SKIPPED:
                e.chain_status, e.chain_tx_hash = ChainStatus.SKIPPED, None
            continue
        start, end = done, done + len(st.ops)
        done = end
        if e.chain_status is ChainStatus.CONFIRMED and e.chain_tx_hash and end <= applied:
            continue

        if end <= applied:  # already on-chain, but we never stored the signature
            if recovered is None:
                recovered = chain.signatures_by_seq(pda)
            if end not in recovered:
                raise RpcError(f"{e.public_id} is on-chain (seq {end}) but its transaction wasn't found")
            e.chain_status, e.chain_tx_hash = ChainStatus.CONFIRMED, recovered[end]
            result.confirmed += 1
            db.commit()
            continue

        remaining = st.ops[max(0, applied - start) :]
        signature = None
        try:
            for chunk in _chunks(remaining):
                evidence_count = int(state["evidence_count"]) if state else 0
                signature = chain.send(chunk, pda, seed, evidence_count)
                result.sent += 1
                state = chain.fetch_shipment(pda)
                if state is None or int(state["audit_seq"]) != applied + len(chunk):
                    raise RpcError(f"{e.public_id}: audit_seq did not advance by {len(chunk)} after {signature}")
                applied += len(chunk)
            assert state is not None and signature is not None
            for name, want in st.expect:
                got = CHAIN_STATUS[state[name]].value if name == "status" else state[name]
                if got != want:
                    raise ValueError(f"{e.public_id}: on-chain {name} is {got}, expected {want}")
        except (RpcError, ValueError) as err:
            e.chain_status = ChainStatus.FAILED
            if isinstance(err, TransactionFailed) and err.program_error:
                raise RpcError(f"{e.public_id}: program rejected it ({err.program_error})") from err
            raise
        e.chain_status, e.chain_tx_hash = ChainStatus.CONFIRMED, signature
        result.confirmed += 1
        db.commit()


def _chunks(ops: tuple[Op, ...]) -> Iterator[tuple[Op, ...]]:
    for i in range(0, len(ops), MAX_OPS_PER_TX):
        yield ops[i : i + MAX_OPS_PER_TX]


def _fail_open(s: Shipment) -> None:
    for e in s.events:
        if e.chain_status is ChainStatus.PENDING:
            e.chain_status = ChainStatus.FAILED


def _identity_problems(state: dict[str, Any], s: Shipment, chain: Chain, seed: bytes) -> list[str]:
    """Differences in what create_shipment fixed: the id, the parties and the agreed rule."""
    assert s.agreement is not None
    terms = s.agreement.parsed_terms()
    want: dict[str, Any] = {
        "shipment_id": seed,
        "buyer": chain.pubkey(Signer.BUYER),
        "supplier": chain.pubkey(Signer.SUPPLIER),
        "authority": chain.pubkey(Signer.AUTHORITY),
        "reviewer": chain.pubkey(Signer.REVIEWER),
        "terms_hash": to_chain_bytes(s.agreement.terms_hash),
        "invoice_amount_cents": cents(terms.invoice_amount),
        "quantity": terms.quantity,
        "credit_per_defect_cents": cents(terms.compensation.amount_per_unit),
        "max_adjustment_cents": cents(terms.compensation.max_credit),
        "defect_tolerance_units": terms.acceptance.defect_tolerance_units,
        "min_dispatch_evidence": terms.evidence_requirements.min_dispatch_photos,
        "min_receipt_evidence": terms.evidence_requirements.min_receipt_photos,
    }
    return [f"{k} differs" for k, v in want.items() if state[k] != v]


# --- verification against the chain --------------------------------------------------------


@dataclass
class Expected:
    """The program's state after a prefix of the plan, computed the way the program does."""

    status: str = "Draft"
    buyer_approved: bool = False
    supplier_approved: bool = False
    evidence: list[tuple[str, bytes]] = field(default_factory=list)  # (kind, sha256) by index
    confirmed_defects: int = 0
    findings_hash: bytes = bytes(32)
    explanation_hash: bytes = bytes(32)
    proposed_adjustment_cents: int = 0
    buyer_accepted: bool = False
    supplier_accepted: bool = False
    dispute_reason_hash: bytes = bytes(32)
    resolution_hash: bytes = bytes(32)
    final_adjustment_cents: int = 0


def expected_state(ops: list[Op], terms: AgreementTerms) -> Expected:
    """Replay `ops` with the program's rules (programs/proofsettle/src/lib.rs)."""
    x = Expected()
    tol = terms.acceptance.defect_tolerance_units
    per, cap = cents(terms.compensation.amount_per_unit), cents(terms.compensation.max_credit)
    min_receipt = terms.evidence_requirements.min_receipt_photos

    def rule(defects: int) -> int:
        return min(max(0, defects - tol) * per, cap)

    for op in ops:
        a = op.args
        match op.ix:
            case "approve_agreement":
                setattr(x, f"{op.signer.value}_approved", True)
                if x.buyer_approved and x.supplier_approved:
                    x.status = "Agreed"
            case "record_evidence":
                x.evidence.append((a["kind"], a["sha256"]))
                receipts = sum(1 for k, _ in x.evidence if k == "Receipt")
                if a["kind"] == "Receipt" and x.status == "InTransit" and receipts >= min_receipt:
                    x.status = "Inspection"
            case "mark_in_transit":
                x.status = "InTransit"
            case "propose_adjustment":
                x.confirmed_defects = a["confirmed_defects"]
                x.findings_hash, x.explanation_hash = a["findings_hash"], a["explanation_hash"]
                x.proposed_adjustment_cents = rule(a["confirmed_defects"])
                x.buyer_accepted = x.supplier_accepted = False
                x.status = "Proposed"
            case "accept_adjustment":
                setattr(x, f"{op.signer.value}_accepted", True)
                if x.buyer_accepted and x.supplier_accepted:
                    x.final_adjustment_cents = x.proposed_adjustment_cents
                    x.status = "Accepted"
            case "dispute_adjustment":
                x.dispute_reason_hash = a["reason_hash"]
                x.status = "Disputed"
            case "resolve_dispute":
                x.confirmed_defects = a["confirmed_defects"]
                x.final_adjustment_cents = rule(a["confirmed_defects"])
                x.resolution_hash = a["resolution_hash"]
                x.status = "Resolved"
    return x


@dataclass(frozen=True)
class ChainReport:
    available: bool
    anchored: int
    mismatches: tuple[str, ...]


def check_shipment(s: Shipment, chain: Chain | None) -> ChainReport:
    """Compare the shipment's on-chain record with the database.

    `available` is False when there is no chain configured or the RPC is unreachable.
    Mismatches name what differs; an empty tuple with anchored > 0 means everything that
    has been anchored agrees.
    """
    anchored = sum(1 for e in s.events if e.chain_status is ChainStatus.CONFIRMED)
    if chain is None:
        return ChainReport(False, anchored, ())
    try:
        steps = plan(s, chain)
    except UnmappedEvent as e:
        return ChainReport(True, anchored, (str(e),))
    seed = chain.seed(s.chain_uuid)
    pda = chain.shipment_pda(seed)
    try:
        state = chain.fetch_shipment(pda)
        evidence = chain.fetch_evidence(pda, int(state["evidence_count"])) if state else []
    except RpcError:
        return ChainReport(False, anchored, ())

    if state is None:
        return ChainReport(True, anchored, (f"no on-chain record at {pda}",) if anchored else ())

    mismatches = _identity_problems(state, s, chain, seed)
    ops = [op for st in steps for op in st.ops]
    applied = int(state["audit_seq"])
    if applied > len(ops):
        mismatches.append(f"on-chain audit_seq {applied} is ahead of the {len(ops)} instructions this history implies")
        return ChainReport(True, anchored, tuple(mismatches))

    assert s.agreement is not None
    want = expected_state(ops[:applied], s.agreement.parsed_terms())
    for name in (
        "buyer_approved",
        "supplier_approved",
        "confirmed_defects",
        "findings_hash",
        "explanation_hash",
        "proposed_adjustment_cents",
        "buyer_accepted",
        "supplier_accepted",
        "dispute_reason_hash",
        "resolution_hash",
        "final_adjustment_cents",
    ):
        if state[name] != getattr(want, name):
            mismatches.append(f"{name} differs")
    if state["status"] != want.status:
        mismatches.append(f"status is {CHAIN_STATUS[state['status']]} on-chain, expected {CHAIN_STATUS[want.status]}")
    if applied == len(ops) and CHAIN_STATUS[state["status"]] is not s.status:
        mismatches.append(f"status is {CHAIN_STATUS[state['status']]} on-chain but {s.status} in the database")

    # Each anchored evidence record against the stored file hash, in upload order.
    ids = [
        ev["id"] for st in steps if st.event.type == EventType.EVIDENCE_UPLOADED for ev in st.event.payload["evidence"]
    ]
    rows = {ev.id: ev for ev in s.evidence}
    for i, (record, (kind, sha)) in enumerate(zip(evidence, want.evidence, strict=False)):
        ev_id = ids[i] if i < len(ids) else f"#{i}"
        row = rows.get(ev_id)
        if record is None:
            mismatches.append(f"evidence {ev_id} has no on-chain record")
        elif record["kind"] != kind or record["sha256"] != sha:
            mismatches.append(f"evidence {ev_id} differs from its on-chain record")
        elif row is None or to_chain_bytes(row.sha256) != record["sha256"]:
            mismatches.append(f"evidence {ev_id}'s stored SHA-256 no longer matches the chain")
    if len(evidence) != len(want.evidence):
        mismatches.append(f"{len(evidence)} evidence records on-chain, expected {len(want.evidence)}")

    # The resolved adjustment must still be what the engine computes from the stored findings.
    if state["status"] == "Resolved":
        live = compute_adjustment(s.agreement.parsed_terms(), tuple(f.to_finding() for f in s.findings))
        if to_chain_bytes(hash_json(live)) != state["resolution_hash"]:
            mismatches.append("resolution_hash doesn't match the adjustment recomputed from stored findings")

    return ChainReport(True, anchored, tuple(mismatches))


# --- entry points --------------------------------------------------------------------------


def shipment_address(s: Shipment, chain: Chain) -> Pubkey:
    return chain.shipment_pda(chain.seed(s.chain_uuid))


def anchor_in_background(sessions: Callable[[], Session], shipment_id: str) -> None:
    """FastAPI background task: anchor one shipment in a fresh session; never raises.

    `sessions` makes sessions on the same database as the request that scheduled it.
    """
    chain = get_chain()
    if chain is None:
        return
    try:
        with sessions() as db:
            result = anchor_shipment(db, shipment_id, chain)
        if result.error is None:
            log.info("Anchored %s: %d tx sent, %d events confirmed", shipment_id, result.sent, result.confirmed)
    except Exception:
        log.exception("Anchoring %s crashed", shipment_id)


def anchor_all(db: Session, chain: Chain) -> list[AnchorResult]:
    """Anchor every shipment with an anchorable event that isn't confirmed yet.

    That includes events stored as "skipped" before the chain was configured.
    """
    ids = db.scalars(
        select(AuditEvent.shipment_id)
        .where(
            AuditEvent.type.in_([t.value for t in ANCHORED_EVENT_TYPES]),
            AuditEvent.chain_status != ChainStatus.CONFIRMED,
        )
        .distinct()
        .order_by(AuditEvent.shipment_id)
    ).all()
    return [anchor_shipment(db, shipment_id, chain) for shipment_id in ids]
