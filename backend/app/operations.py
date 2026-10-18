"""Write operations behind the POST endpoints (API_CONTRACT.md).

Each function takes a Shipment loaded in a session, checks the move with app.workflow or
app.resolution, changes the rows and appends an audit event. Nothing is committed here: the
route commits once the whole operation has succeeded, so a refused move leaves no trace.
No function takes an amount or a status from the caller. Statuses come from
workflow.transition, and amounts from compute_adjustment over the stored terms and findings.

Errors are app.workflow's TransitionError subclasses (400/403/409) and
app.inspection.InspectionFailed (502).
"""

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pydantic import AwareDatetime
from sqlalchemy import select
from sqlalchemy.orm import Session, object_session

from app.audit import EventCheck, EventType, append_event, iso_utc, verify_chain
from app.findings import ReviewOverride
from app.hashing import hash_json, sha256_hex, shipment_uuid
from app.inspection import InspectionFailed, InspectionProvider, InspectionRequest, Photo, parse_report, to_finding
from app.models import AdjustmentRow, Agreement, Evidence, EvidenceKind, FindingRow, Shipment
from app.resolution import resolve, review_finding
from app.schemas import CamelModel
from app.settlement import Adjustment, compute_adjustment, usd
from app.terms import AgreementTerms
from app.workflow import (
    Actor,
    AdjustmentAcceptance,
    NotPermitted,
    PreconditionFailed,
    Status,
    accept,
    can_transition,
    transition,
)

PARTIES = (Actor.BUYER, Actor.SUPPLIER)

# Upload status -> (evidence kind, the move that meeting the minimum count makes).
UPLOAD_SLOTS = {
    Status.AGREED: (EvidenceKind.DISPATCH, Status.IN_TRANSIT),
    Status.IN_TRANSIT: (EvidenceKind.RECEIPT, Status.INSPECTION),
}

# Magic bytes -> (content type, file extension). The client's declared type is ignored.
IMAGE_TYPES = {
    b"\xff\xd8\xff": ("image/jpeg", "jpg"),
    b"\x89PNG\r\n\x1a\n": ("image/png", "png"),
}


@dataclass(frozen=True)
class Upload:
    data: bytes
    content_type: str
    ext: str


def sniff_image(data: bytes) -> Upload | None:
    for magic, (content_type, ext) in IMAGE_TYPES.items():
        if data.startswith(magic):
            return Upload(data, content_type, ext)
    return None


# --- helpers ------------------------------------------------------------------------------


def next_ids(
    db: Session, model: type[Evidence | FindingRow | AdjustmentRow | Agreement], prefix: str, n: int
) -> list[str]:
    """The next n sequential ids after the seed's style ("ev_21", "fnd_10", ...).

    Two concurrent requests can pick the same id; the second then fails on the primary key
    and nothing of it is stored. Fine for the demo; real ids would come from a sequence.
    """
    pattern = re.compile(rf"{prefix}_(\d+)")
    used = [int(m.group(1)) for i in db.scalars(select(model.id)) if (m := pattern.fullmatch(i))]
    start = max(used, default=0) + 1
    return [f"{prefix}_{k:02d}" for k in range(start, start + n)]


def next_shipment_id(db: Session) -> str:
    used = [int(m.group(1)) for i in db.scalars(select(Shipment.id)) if (m := re.fullmatch(r"PS-(\d+)", i))]
    return f"PS-{max(used, default=1000) + 1}"


def evidence_path(root: Path, ev: Evidence) -> Path | None:
    """The stored file for `ev`, or None if it is missing or would escape `root`."""
    base = root.resolve()
    path = (base / ev.file_name).resolve()
    return path if path.is_relative_to(base) and path.is_file() else None


def adjustment_payload(adjustment_id: str, adj: Adjustment) -> dict[str, object]:
    dumped = adj.model_dump(mode="json", by_alias=True)
    return {
        "adjustmentId": adjustment_id,
        "adjustmentHash": hash_json(adj),
        "confirmedDefects": adj.confirmed_defects,
        "credit": dumped["credit"],
        "settlementAmount": dumped["settlementAmount"],
    }


def _db(s: Shipment) -> Session:
    db = object_session(s)
    if db is None:
        raise ValueError("shipment must belong to a session")
    return db


def _move(s: Shipment, target: Status, actor: Actor, reason: str | None = None, **guards: object) -> dict[str, str]:
    before = s.status
    s.status = transition(before, target, actor, reason, **guards)  # type: ignore[arg-type]
    return {"from": before.value, "to": target.value}


def _terms(s: Shipment) -> AgreementTerms:
    if s.agreement is None:
        raise PreconditionFailed(f"{s.id} has no agreement")
    return s.agreement.parsed_terms()


def _acceptance(s: Shipment) -> AdjustmentAcceptance:
    row = s.adjustment
    return AdjustmentAcceptance(
        buyer_accepted_at=row.buyer_accepted_at if row else None,
        supplier_accepted_at=row.supplier_accepted_at if row else None,
    )


def _live_adjustment(s: Shipment) -> Adjustment:
    return compute_adjustment(_terms(s), tuple(f.to_finding() for f in s.findings))


# --- operations ---------------------------------------------------------------------------


def create_shipment(
    db: Session,
    actor: Actor,
    *,
    title: str,
    buyer: str,
    supplier: str,
    terms: AgreementTerms,
    now: datetime,
    buyer_user_id: str | None = None,
) -> Shipment:
    """A new Draft shipment with its agreement terms. Buyer only; nobody has approved yet."""
    if actor is not Actor.BUYER:
        raise NotPermitted(f"{actor} cannot create a shipment")
    id = next_shipment_id(db)
    s = Shipment(
        id=id,
        chain_uuid=shipment_uuid(id),
        title=title,
        buyer=buyer,
        supplier=supplier,
        buyer_user_id=buyer_user_id,
        status=Status.DRAFT,
        created_at=now,
    )
    s.agreement = Agreement(
        id=next_ids(db, Agreement, "agr", 1)[0], terms=terms.model_dump(mode="json"), terms_hash=hash_json(terms)
    )
    db.add(s)
    db.flush()
    append_event(
        s,
        EventType.AGREEMENT_DRAFTED,
        actor,
        {"agreementId": s.agreement.id, "termsHash": s.agreement.terms_hash},
        text=f"Agreement drafted: {terms.quantity} × {terms.item_description}, {usd(terms.invoice_amount)}",
        at=now,
    )
    return s


def approve_agreement(s: Shipment, actor: Actor, now: datetime) -> None:
    """Record one party's approval; the second approval moves Draft -> Agreed (by System).

    Approving twice is a no-op that keeps the first timestamp and logs nothing.
    """
    if s.status is not Status.DRAFT or s.agreement is None:
        raise PreconditionFailed(f"The agreement can only be approved while Draft, not {s.status}")
    if actor not in PARTIES:
        raise NotPermitted(f"{actor} cannot approve an agreement")
    agr = s.agreement
    field = "buyer_approved_at" if actor is Actor.BUYER else "supplier_approved_at"
    if getattr(agr, field) is not None:
        return
    setattr(agr, field, now)
    payload: dict[str, object] = {
        "agreementId": agr.id,
        "termsHash": agr.terms_hash,
        "approvedBy": actor.value,
        "approvedAt": iso_utc(now),
    }
    both = agr.buyer_approved_at is not None and agr.supplier_approved_at is not None
    if both:
        payload["status"] = _move(s, Status.AGREED, Actor.SYSTEM)
    text = "Agreement approved by both parties" if both else f"Agreement approved by {actor}"
    append_event(s, EventType.AGREEMENT_APPROVED, actor, payload, text=text, at=now)


def upload_slot(s: Shipment, actor: Actor) -> tuple[EvidenceKind, Status]:
    """Which evidence `actor` may upload now, and the move it leads to; raises if none."""
    slot = UPLOAD_SLOTS.get(s.status)
    if slot is None:
        raise PreconditionFailed(f"Evidence can't be uploaded while {s.status}")
    kind, target = slot
    if not can_transition(s.status, target, actor):
        raise NotPermitted(f"{actor} cannot upload {kind.value} evidence")
    return slot


def add_evidence(s: Shipment, actor: Actor, uploads: list[Upload], root: Path, now: datetime) -> list[Path]:
    """Store dispatch (Agreed, Supplier) or receipt (In Transit, Buyer) photos.

    Each file's SHA-256 is taken from the exact uploaded bytes before they're written.
    Reaching the agreement's minimum photo count moves the shipment on (Agreed -> In
    Transit, In Transit -> Inspection). Returns the files written, so the caller can delete
    them if the commit fails.
    """
    kind, target = upload_slot(s, actor)
    if not uploads:
        raise PreconditionFailed("No files uploaded")
    reqs = _terms(s).evidence_requirements
    minimum = reqs.min_dispatch_photos if kind is EvidenceKind.DISPATCH else reqs.min_receipt_photos

    new: list[tuple[Evidence, bytes]] = []
    for ev_id, up in zip(next_ids(_db(s), Evidence, "ev", len(uploads)), uploads, strict=True):
        ev = Evidence(
            id=ev_id,
            kind=kind,
            file_name=f"{ev_id}.{up.ext}",
            content_type=up.content_type,
            sha256=sha256_hex(up.data),
            uploaded_by=actor,
            uploaded_at=now,
            verified=None,
        )
        s.evidence.append(ev)
        new.append((ev, up.data))

    count = sum(1 for ev in s.evidence if ev.kind is kind)
    payload: dict[str, object] = {
        "kind": kind.value,
        "evidence": [{"id": ev.id, "sha256": ev.sha256} for ev, _ in new],
        "count": count,
        "required": minimum,
    }
    label = "Dispatch" if kind is EvidenceKind.DISPATCH else "Receipt"
    text = f"{label} photos uploaded ({len(new)})"
    if count >= minimum:
        payload["status"] = _move(s, target, actor)
        text += f"; shipment moved to {target}"
    append_event(s, EventType.EVIDENCE_UPLOADED, actor, payload, text=text, at=now)

    root.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    try:
        for ev, data in new:
            path = root / ev.file_name
            with path.open("xb") as f:
                f.write(data)
            written.append(path)
    except OSError:
        for path in written:
            path.unlink(missing_ok=True)
        raise
    return written


def run_inspection(s: Shipment, actor: Actor, provider: InspectionProvider, root: Path, now: datetime) -> None:
    """Inspect the photos, store the validated findings, then System moves Inspection -> Proposed.

    The photos are re-hashed first and the inspection is refused if any file changed. The
    proposed adjustment is compute_adjustment's output; the provider has no say in it.
    """
    if s.status is not Status.INSPECTION:
        raise PreconditionFailed(f"Inspection can only run while Inspection, not {s.status}")
    if actor not in PARTIES:
        raise NotPermitted(f"{actor} cannot run an inspection")
    terms = _terms(s)

    photos: dict[EvidenceKind, list[Photo]] = {EvidenceKind.DISPATCH: [], EvidenceKind.RECEIPT: []}
    for ev in s.evidence:
        path = evidence_path(root, ev)
        data = path.read_bytes() if path else None
        if data is None or sha256_hex(data) != ev.sha256:
            raise PreconditionFailed(f"Evidence {ev.id} is missing or no longer matches its SHA-256")
        photos[ev.kind].append(Photo(ev.id, ev.kind.value, ev.content_type, ev.sha256, data))
    request = InspectionRequest(
        shipment_id=s.id,
        terms=terms,
        dispatch=tuple(photos[EvidenceKind.DISPATCH]),
        receipt=tuple(photos[EvidenceKind.RECEIPT]),
    )

    try:
        raw = provider.inspect(request)
    except InspectionFailed:
        raise
    except Exception as e:
        raise InspectionFailed(f"Inspection provider {provider.name} failed") from e
    report = parse_report(raw, request)

    db = _db(s)
    ids = next_ids(db, FindingRow, "fnd", len(report.findings))
    findings = tuple(to_finding(fid, f) for fid, f in zip(ids, report.findings, strict=True))
    s.findings.extend(FindingRow.from_finding(s.id, f) for f in findings)
    append_event(
        s,
        EventType.INSPECTION_COMPLETED,
        Actor.AI,
        {
            "provider": provider.name,
            "requestedBy": actor.value,
            "findingIds": [f.id for f in findings],
            "findingsHash": hash_json(findings),
        },
        text=f"Inspection complete: {len(findings)} finding{'s' if len(findings) != 1 else ''} flagged",
        at=now,
    )

    adj = compute_adjustment(terms, findings)
    row = AdjustmentRow(
        id=next_ids(db, AdjustmentRow, "adj", 1)[0],
        computed_at=now,
        confirmed_defects=adj.confirmed_defects,
        credit=adj.credit,
        settlement_amount=adj.settlement_amount,
    )
    s.adjustment = row
    payload = adjustment_payload(row.id, adj) | {"status": _move(s, Status.PROPOSED, Actor.SYSTEM)}
    append_event(
        s,
        EventType.ADJUSTMENT_PROPOSED,
        Actor.SYSTEM,
        payload,
        text=f"Adjustment proposed from agreement rule: {usd(adj.credit)}",
        at=now,
    )


def accept_adjustment(s: Shipment, actor: Actor, now: datetime) -> None:
    """One party accepts; the second acceptance moves Proposed -> Accepted. Repeats are no-ops."""
    before = _acceptance(s)
    status, after = accept(s.status, actor, before, now)
    if after == before:
        return
    row = s.adjustment
    assert row is not None  # accept() only succeeds while Proposed, which has an adjustment
    row.buyer_accepted_at, row.supplier_accepted_at = after.buyer_accepted_at, after.supplier_accepted_at
    adj = _live_adjustment(s)
    payload = adjustment_payload(row.id, adj) | {"acceptedAt": iso_utc(now)}
    if status is not s.status:
        payload["status"] = {"from": s.status.value, "to": status.value}
        s.status = status
    append_event(
        s, EventType.ADJUSTMENT_ACCEPTED, actor, payload, text=f"{actor} accepted {usd(adj.credit)} adjustment", at=now
    )


def dispute_adjustment(s: Shipment, actor: Actor, reason: str | None, now: datetime) -> None:
    reason = (reason or "").strip()
    payload = {"reason": reason, "status": _move(s, Status.DISPUTED, actor, reason, acceptance=_acceptance(s))}
    s.dispute_reason = reason
    append_event(s, EventType.ADJUSTMENT_DISPUTED, actor, payload, text=f"Adjustment disputed: {reason}", at=now)


def review(s: Shipment, row: FindingRow, actor: Actor, decision: ReviewOverride, now: datetime) -> None:
    """A Reviewer confirms or rejects one finding while Disputed. Deciding again replaces it."""
    reviewed = review_finding(s.status, row.to_finding(), decision, actor, now)
    row.review_override, row.reviewed_by, row.reviewed_at = reviewed.review_override, actor, now
    append_event(
        s,
        EventType.FINDING_REVIEWED,
        actor,
        {"findingId": row.id, "decision": decision, "finding": reviewed},
        text=f"Reviewer {decision} {row.id} ({reviewed.unit_ref})",
        at=now,
    )


def resolve_dispute(s: Shipment, actor: Actor, now: datetime) -> None:
    """Disputed -> Resolved with the engine's adjustment over the reviewed findings."""
    before = s.status
    s.status, adj = resolve(before, _terms(s), tuple(f.to_finding() for f in s.findings), actor)
    row = s.adjustment
    assert row is not None  # resolve() only succeeds while Disputed, which has an adjustment
    row.computed_at = now
    row.confirmed_defects, row.credit, row.settlement_amount = adj.confirmed_defects, adj.credit, adj.settlement_amount
    payload = adjustment_payload(row.id, adj) | {"status": {"from": before.value, "to": s.status.value}}
    append_event(
        s, EventType.DISPUTE_RESOLVED, actor, payload, text=f"Dispute resolved: {usd(adj.credit)} credit", at=now
    )


# --- verification -------------------------------------------------------------------------


class HashCheck(CamelModel):
    id: str
    stored_hash: str
    recomputed_hash: str | None  # None when the evidence file is missing
    ok: bool


class ChainCheck(CamelModel):
    available: bool
    anchored: int
    mismatches: tuple[str, ...]


class Verification(CamelModel):
    shipment_id: str
    verified: bool
    checked: int
    agreement: HashCheck | None
    events: tuple[EventCheck, ...]
    evidence: tuple[HashCheck, ...]
    chain: ChainCheck
    verified_at: AwareDatetime


def verify(s: Shipment, root: Path, now: datetime) -> Verification:
    """Re-hash the agreement terms and every evidence file, and walk the event chain.

    Sets each evidence item's `verified` to its result.
    """
    agreement = None
    if s.agreement:
        recomputed = hash_json(s.agreement.terms)
        agreement = HashCheck(
            id=s.agreement.id,
            stored_hash=s.agreement.terms_hash,
            recomputed_hash=recomputed,
            ok=recomputed == s.agreement.terms_hash,
        )

    evidence = []
    for ev in s.evidence:
        path = evidence_path(root, ev)
        recomputed = None
        if path:
            with path.open("rb") as f:
                recomputed = hashlib.file_digest(f, "sha256").hexdigest()
        ev.verified = recomputed == ev.sha256
        evidence.append(HashCheck(id=ev.id, stored_hash=ev.sha256, recomputed_hash=recomputed, ok=ev.verified))

    chain = verify_chain(_db(s), s)
    items = [*evidence, *([agreement] if agreement else [])]
    return Verification(
        shipment_id=s.id,
        verified=chain.verified and all(c.ok for c in items),
        checked=chain.checked + len(items),
        agreement=agreement,
        events=chain.events,
        evidence=tuple(evidence),
        chain=ChainCheck(available=False, anchored=0, mismatches=()),  # no chain anchoring yet
        verified_at=now,
    )
