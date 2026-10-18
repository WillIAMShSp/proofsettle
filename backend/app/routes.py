"""HTTP endpoints for the frontend (API_CONTRACT.md).

Every /shipments and /findings route needs Authorization: Bearer <Supabase access token>.
The token is verified with Supabase Auth. The caller's account is that user id plus
public.profiles.role (Buyer, Supplier or Reviewer). The role decides the `actions` flags.
The user id decides which shipments they can see: a Buyer sees shipments they created,
a Supplier sees shipments addressed to their profile name, and a Reviewer sees disputes
on accounts' shipments. The shared demo seed has no account id and is hidden from a real
login. X-Demo-Role is ignored. GET /evidence/{id}/file does not require a token, because
an <img src> can't send headers.

Writes are thin: app.operations does the work through app.workflow / app.resolution, and
the route commits and returns the updated shipment detail. No request body carries an
amount or a status; bodies that exist reject unknown fields with 422, and routes without a
body ignore whatever is sent.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import AwareDatetime, StringConstraints
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app import operations as ops
from app.audit import ChainVerification, EventCheck, verify_chain
from app.auth import Account, current_actor
from app.config import settings
from app.db import get_db
from app.findings import Finding, ReviewOverride
from app.inspection import InspectionProvider, MockProvider
from app.models import AdjustmentRow, AuditEvent, ChainStatus, ChatMessage, Evidence, FindingRow, Shipment
from app.money import Money
from app.schemas import CamelModel
from app.seed_db import BUYER, reset_and_seed
from app.settlement import Adjustment, compute_adjustment
from app.terms import AgreementTerms
from app.workflow import Actor, AdjustmentAcceptance, Status, can_accept, can_dispute

router = APIRouter()


def evidence_dir() -> Path:
    return settings.evidence_dir


def inspection_provider() -> InspectionProvider:
    # The only provider for now; a vision-model provider plugs in here.
    return MockProvider()


Db = Annotated[Session, Depends(get_db)]
Role = Annotated[Account, Depends(current_actor)]
EvidenceRoot = Annotated[Path, Depends(evidence_dir)]
Provider = Annotated[InspectionProvider, Depends(inspection_provider)]

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


# --- Request bodies -----------------------------------------------------------------------


class NewShipment(CamelModel):
    title: Name
    supplier: Name
    terms: AgreementTerms


class DisputeIn(CamelModel):
    # Optional here so a missing reason is the contract's 400, not a 422.
    reason: Annotated[str, StringConstraints(strip_whitespace=True, max_length=400)] | None = None


class ReviewIn(CamelModel):
    decision: ReviewOverride


class MessageIn(CamelModel):
    body: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


# --- Response shapes ----------------------------------------------------------------------


class ShipmentSummary(CamelModel):
    id: str
    title: str
    buyer: str
    supplier: str
    amount: Money
    status: Status


class AgreementOut(CamelModel):
    terms: AgreementTerms
    buyer_approved: bool
    supplier_approved: bool
    terms_hash: str


class EvidenceOut(CamelModel):
    id: str
    kind: Literal["dispatch", "receipt"]
    url: str
    sha256: str
    uploaded_by: Actor
    at: AwareDatetime
    verified: bool | None


class InspectionOut(CamelModel):
    findings: tuple[Finding, ...]


class AdjustmentOut(Adjustment):
    """compute_adjustment's output plus the stored record's id, time and acceptances."""

    id: str
    computed_at: AwareDatetime
    buyer_accepted_at: AwareDatetime | None
    supplier_accepted_at: AwareDatetime | None


class Actions(CamelModel):
    can_accept: bool
    can_dispute: bool
    can_review: bool
    can_resolve: bool


class EventOut(CamelModel):
    id: str
    seq: int
    at: AwareDatetime
    actor: Actor
    type: str
    text: str
    hash: str
    payload_hash: str
    prev_hash: str | None
    tx_hash: str | None
    chain_status: ChainStatus


class ShipmentDetail(ShipmentSummary):
    dispute_reason: str | None
    agreement: AgreementOut | None
    evidence: tuple[EvidenceOut, ...]
    inspection: InspectionOut | None
    adjustment: AdjustmentOut | None
    actions: Actions
    events: tuple[EventOut, ...]


class AuditOut(CamelModel):
    shipment_id: str
    verified: bool
    checked: int
    events: tuple[EventOut, ...]
    checks: tuple[EventCheck, ...]


class MessageOut(CamelModel):
    id: str
    shipment_id: str
    at: AwareDatetime
    author_role: Actor
    author_name: str
    body: str
    # Written by the caller's account, so the UI can put it on the right-hand side.
    mine: bool


# --- Builders -----------------------------------------------------------------------------


def _summary_fields(s: Shipment) -> dict[str, object]:
    amount = s.agreement.parsed_terms().invoice_amount if s.agreement else None
    return {
        "id": s.id,
        "title": s.title,
        "buyer": s.buyer,
        "supplier": s.supplier,
        "amount": amount,
        "status": s.status,
    }


def _event(e: AuditEvent) -> EventOut:
    return EventOut(
        id=e.public_id,
        seq=e.seq,
        at=e.at,
        actor=e.actor,
        type=e.type,
        text=e.text,
        hash=e.event_hash,
        payload_hash=e.payload_hash,
        prev_hash=e.prev_event_hash,
        tx_hash=e.chain_tx_hash,
        chain_status=e.chain_status,
    )


def _evidence(ev: Evidence) -> EvidenceOut:
    return EvidenceOut(
        id=ev.id,
        kind=ev.kind.value,
        url=f"/evidence/{ev.id}/file",
        sha256=ev.sha256,
        uploaded_by=ev.uploaded_by,
        at=ev.uploaded_at,
        verified=ev.verified,
    )


def _adjustment(row: AdjustmentRow, adj: Adjustment) -> AdjustmentOut:
    return AdjustmentOut(
        **adj.model_dump(by_alias=False),
        id=row.id,
        computed_at=row.computed_at,
        buyer_accepted_at=row.buyer_accepted_at,
        supplier_accepted_at=row.supplier_accepted_at,
    )


def _actions(s: Shipment, role: Actor, live: Adjustment | None) -> Actions:
    row = s.adjustment
    acceptance = AdjustmentAcceptance(
        buyer_accepted_at=row.buyer_accepted_at if row else None,
        supplier_accepted_at=row.supplier_accepted_at if row else None,
    )
    has_adjustment = row is not None
    can_review = role is Actor.REVIEWER and s.status is Status.DISPUTED
    return Actions(
        can_accept=has_adjustment and can_accept(s.status, role, acceptance),
        can_dispute=has_adjustment and can_dispute(s.status, role, acceptance),
        can_review=can_review,
        can_resolve=can_review and live is not None and not live.needs_review,
    )


def _can_see(account: Account, shipment: Shipment) -> bool:
    """True when this account may read or change the shipment.

    No user id means the test double, which still sees every row. A real account does not
    see another account's shipments. Unowned demo rows match a profile name only.
    """
    if account.user_id is None:
        return True
    if shipment.buyer_user_id == account.user_id or shipment.supplier_user_id == account.user_id:
        return True
    owned = shipment.buyer_user_id is not None or shipment.supplier_user_id is not None
    if account.role is Actor.REVIEWER and owned and shipment.status in (Status.DISPUTED, Status.RESOLVED):
        return True
    buyer_name_match = (
        account.name
        and shipment.buyer_user_id is None
        and account.role is Actor.BUYER
        and shipment.buyer == account.name
    )
    if buyer_name_match:
        return True
    return bool(
        account.name
        and shipment.supplier_user_id is None
        and account.role is Actor.SUPPLIER
        and shipment.supplier == account.name
    )


def _visible(account: Account):
    if account.user_id is None:
        return None
    clauses = [
        Shipment.buyer_user_id == account.user_id,
        Shipment.supplier_user_id == account.user_id,
    ]
    if account.role is Actor.REVIEWER:
        clauses.append(
            (Shipment.buyer_user_id.is_not(None) | Shipment.supplier_user_id.is_not(None))
            & Shipment.status.in_((Status.DISPUTED, Status.RESOLVED))
        )
    if account.name and account.role is Actor.BUYER:
        clauses.append((Shipment.buyer_user_id.is_(None)) & (Shipment.buyer == account.name))
    if account.name and account.role is Actor.SUPPLIER:
        clauses.append((Shipment.supplier_user_id.is_(None)) & (Shipment.supplier == account.name))
    return or_(*clauses)


def _load(db: Session, shipment_id: str, account: Account, *, lock: bool = False) -> Shipment:
    """The shipment with everything the detail needs, freshly read from the database.

    `lock` takes a row lock for a write (Postgres; SQLite serialises writers anyway), so two
    writes to one shipment can't both append the same audit seq.
    """
    query = (
        select(Shipment)
        .where(Shipment.id == shipment_id)
        .options(
            selectinload(Shipment.agreement),
            selectinload(Shipment.evidence),
            selectinload(Shipment.findings),
            selectinload(Shipment.adjustment),
            selectinload(Shipment.events),
        )
        .execution_options(populate_existing=True)
    )
    s = db.scalars(query.with_for_update() if lock else query).one_or_none()
    if s is None or not _can_see(account, s):
        raise HTTPException(404, f"Unknown shipment {shipment_id}")
    return s


def _detail(s: Shipment, role: Actor) -> ShipmentDetail:
    findings = tuple(f.to_finding() for f in s.findings)
    live = compute_adjustment(s.agreement.parsed_terms(), findings) if s.adjustment and s.agreement else None
    return ShipmentDetail(
        **_summary_fields(s),
        dispute_reason=s.dispute_reason,
        agreement=AgreementOut(
            terms=s.agreement.parsed_terms(),
            buyer_approved=s.agreement.buyer_approved_at is not None,
            supplier_approved=s.agreement.supplier_approved_at is not None,
            terms_hash=s.agreement.terms_hash,
        )
        if s.agreement
        else None,
        evidence=tuple(_evidence(ev) for ev in s.evidence),
        inspection=InspectionOut(findings=findings) if findings else None,
        adjustment=_adjustment(s.adjustment, live) if s.adjustment and live else None,
        actions=_actions(s, role, live),
        events=tuple(_event(e) for e in s.events),
    )


def _message(m: ChatMessage, account: Account) -> MessageOut:
    # No user id means the test double or demo, where a role is the whole account.
    mine = m.author_user_id == account.user_id if account.user_id else m.author_role is account.role
    return MessageOut(
        id=m.public_id,
        shipment_id=m.shipment_id,
        at=m.at,
        author_role=m.author_role,
        author_name=m.author_name,
        body=m.body,
        mine=mine,
    )


def _visible_shipment(db: Session, shipment_id: str, account: Account) -> Shipment:
    """The bare shipment row, 404 when this account can't see it. Chat needs nothing else."""
    s = db.get(Shipment, shipment_id)
    if s is None or not _can_see(account, s):
        raise HTTPException(404, f"Unknown shipment {shipment_id}")
    return s


def _committed(db: Session, shipment_id: str, account: Account) -> ShipmentDetail:
    db.commit()
    return _detail(_load(db, shipment_id, account), account.role)


def _now() -> datetime:
    return datetime.now(UTC)


def _read_image(f: UploadFile) -> ops.Upload:
    data = f.file.read(settings.max_evidence_bytes + 1)
    if len(data) > settings.max_evidence_bytes:
        raise HTTPException(413, f"{f.filename} is larger than {settings.max_evidence_bytes} bytes")
    upload = ops.sniff_image(data)
    if upload is None:
        raise HTTPException(415, f"{f.filename} is not a JPEG or PNG image")
    return upload


# --- Reads --------------------------------------------------------------------------------


@router.get("/shipments")
def list_shipments(db: Db, account: Role) -> list[ShipmentSummary]:
    query = select(Shipment).options(selectinload(Shipment.agreement)).order_by(Shipment.id.desc())
    visible = _visible(account)
    if visible is not None:
        query = query.where(visible)
    shipments = db.scalars(query)
    return [ShipmentSummary(**_summary_fields(s)) for s in shipments]


@router.get("/shipments/{shipment_id}")
def get_shipment(shipment_id: str, db: Db, account: Role) -> ShipmentDetail:
    return _detail(_load(db, shipment_id, account), account.role)


@router.get("/shipments/{shipment_id}/audit")
def get_audit(shipment_id: str, db: Db, account: Role) -> AuditOut:
    s = _load(db, shipment_id, account)
    result: ChainVerification = verify_chain(db, s)
    return AuditOut(
        shipment_id=s.id,
        verified=result.verified,
        checked=result.checked,
        events=tuple(_event(e) for e in s.events),
        checks=result.events,
    )


@router.get("/shipments/{shipment_id}/messages")
def list_messages(shipment_id: str, db: Db, account: Role) -> list[MessageOut]:
    s = _visible_shipment(db, shipment_id, account)
    rows = db.scalars(select(ChatMessage).where(ChatMessage.shipment_id == s.id).order_by(ChatMessage.id))
    return [_message(m, account) for m in rows]


@router.get("/evidence/{evidence_id}/file")
def get_evidence_file(evidence_id: str, db: Db, root: EvidenceRoot) -> FileResponse:
    ev = db.get(Evidence, evidence_id)
    if ev is None:
        raise HTTPException(404, f"Unknown evidence {evidence_id}")
    path = ops.evidence_path(root, ev)
    if path is None:
        raise HTTPException(404, f"File for evidence {evidence_id} is missing")
    return FileResponse(path, media_type=ev.content_type)


# --- Writes -------------------------------------------------------------------------------


@router.post("/shipments", status_code=201)
def create_shipment(body: NewShipment, db: Db, account: Role) -> ShipmentDetail:
    s = ops.create_shipment(
        db,
        account.role,
        title=body.title,
        buyer=account.name or BUYER,
        supplier=body.supplier,
        terms=body.terms,
        now=_now(),
        buyer_user_id=account.user_id,
    )
    return _committed(db, s.id, account)


@router.post("/shipments/{shipment_id}/agreement/approve")
def approve_agreement(shipment_id: str, db: Db, account: Role) -> ShipmentDetail:
    ops.approve_agreement(_load(db, shipment_id, account, lock=True), account.role, _now())
    return _committed(db, shipment_id, account)


@router.post("/shipments/{shipment_id}/evidence")
def upload_evidence(
    shipment_id: str, db: Db, account: Role, root: EvidenceRoot, files: Annotated[list[UploadFile], File()]
) -> ShipmentDetail:
    s = _load(db, shipment_id, account, lock=True)
    ops.upload_slot(s, account.role)  # 403/409 before looking at the files
    if len(files) > settings.max_evidence_files:
        raise HTTPException(413, f"At most {settings.max_evidence_files} files per upload")
    written = ops.add_evidence(s, account.role, [_read_image(f) for f in files], root, _now())
    try:
        return _committed(db, shipment_id, account)
    except Exception:
        for path in written:
            path.unlink(missing_ok=True)
        raise


@router.post("/shipments/{shipment_id}/inspect")
def inspect(shipment_id: str, db: Db, account: Role, root: EvidenceRoot, provider: Provider) -> ShipmentDetail:
    ops.run_inspection(_load(db, shipment_id, account, lock=True), account.role, provider, root, _now())
    return _committed(db, shipment_id, account)


@router.post("/shipments/{shipment_id}/accept")
def accept(shipment_id: str, db: Db, account: Role) -> ShipmentDetail:
    ops.accept_adjustment(_load(db, shipment_id, account, lock=True), account.role, _now())
    return _committed(db, shipment_id, account)


@router.post("/shipments/{shipment_id}/dispute")
def dispute(shipment_id: str, db: Db, account: Role, body: DisputeIn | None = None) -> ShipmentDetail:
    ops.dispute_adjustment(_load(db, shipment_id, account, lock=True), account.role, body.reason if body else None, _now())
    return _committed(db, shipment_id, account)


@router.post("/findings/{finding_id}/review")
def review_finding(finding_id: str, body: ReviewIn, db: Db, account: Role) -> ShipmentDetail:
    row = db.get(FindingRow, finding_id)
    if row is None:
        raise HTTPException(404, f"Unknown finding {finding_id}")
    shipment = db.get(Shipment, row.shipment_id)
    if shipment is None or not _can_see(account, shipment):
        raise HTTPException(404, f"Unknown finding {finding_id}")
    s = _load(db, row.shipment_id, account, lock=True)
    ops.review(s, row, account.role, body.decision, _now())
    return _committed(db, s.id, account)


@router.post("/shipments/{shipment_id}/resolve")
def resolve(shipment_id: str, db: Db, account: Role) -> ShipmentDetail:
    ops.resolve_dispute(_load(db, shipment_id, account, lock=True), account.role, _now())
    return _committed(db, shipment_id, account)


@router.post("/shipments/{shipment_id}/messages", status_code=201)
def send_message(shipment_id: str, body: MessageIn, db: Db, account: Role) -> MessageOut:
    """Buyer and Supplier talk; a Reviewer reads the thread for context but stays neutral."""
    s = _visible_shipment(db, shipment_id, account)
    if account.role not in (Actor.BUYER, Actor.SUPPLIER):
        raise HTTPException(403, "Only the Buyer and Supplier can send messages")
    m = ChatMessage(
        shipment_id=s.id,
        author_role=account.role,
        author_user_id=account.user_id,
        author_name=account.name or account.role.value,
        body=body.body,
        at=_now(),
    )
    db.add(m)
    db.commit()
    return _message(m, account)


@router.post("/shipments/{shipment_id}/audit/verify")
def verify_audit(shipment_id: str, db: Db, account: Role, root: EvidenceRoot) -> ops.Verification:
    result = ops.verify(_load(db, shipment_id, account, lock=True), root, _now())
    db.commit()  # each evidence item's `verified`
    return result


class ResetOut(CamelModel):
    shipments: tuple[str, ...]


@router.post("/dev/reset")
def dev_reset(db: Db, root: EvidenceRoot) -> ResetOut:
    """Drop every table and reload the demo seed. 404 unless PROOFSETTLE_DEV_MODE=true."""
    if not settings.dev_mode:
        raise HTTPException(404, "Not Found")
    bind = db.get_bind()
    db.close()
    reset_and_seed(bind, root)  # type: ignore[arg-type]
    return ResetOut(shipments=tuple(db.scalars(select(Shipment.id).order_by(Shipment.id.desc()))))
