"""HTTP endpoints for the frontend (API_CONTRACT.md).

Every /shipments and /findings route needs Authorization: Bearer <Supabase access token>.
The token is verified with Supabase Auth and the caller's role is public.profiles.role
(Buyer, Supplier or Reviewer), which decides the `actions` flags and is checked on every
write. X-Demo-Role is ignored. GET /evidence/{id}/file does not require a token, because
an <img src> can't send headers.

Writes are thin: app.operations does the work through app.workflow / app.resolution, and
the route commits and returns the updated shipment detail. No request body carries an
amount or a status; bodies that exist reject unknown fields with 422, and routes without a
body ignore whatever is sent.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import AwareDatetime, StringConstraints
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload, sessionmaker

from app import operations as ops
from app.audit import ChainVerification, EventCheck, verify_chain
from app.auth import current_actor
from app.chain import get_chain
from app.chain.anchoring import anchor_in_background, anchor_shipment, check_shipment, shipment_address
from app.config import settings
from app.db import get_db
from app.findings import Finding, ReviewOverride
from app.inspection import InspectionProvider, MockProvider
from app.models import AdjustmentRow, AuditEvent, ChainStatus, Evidence, FindingRow, Shipment
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
Role = Annotated[Actor, Depends(current_actor)]
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


class ChainOut(CamelModel):
    """Where this shipment lives on Solana; null in the detail when no chain is configured."""

    program_id: str
    address: str  # the shipment PDA
    # Explorer `cluster` query value, e.g. "devnet":
    # https://explorer.solana.com/tx/<txHash>?cluster=<explorerCluster>
    explorer_cluster: str


class ShipmentDetail(ShipmentSummary):
    dispute_reason: str | None
    agreement: AgreementOut | None
    evidence: tuple[EvidenceOut, ...]
    inspection: InspectionOut | None
    adjustment: AdjustmentOut | None
    actions: Actions
    events: tuple[EventOut, ...]
    chain: ChainOut | None


class AuditOut(CamelModel):
    shipment_id: str
    verified: bool
    checked: int
    events: tuple[EventOut, ...]
    checks: tuple[EventCheck, ...]


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


def _load(db: Session, shipment_id: str, *, lock: bool = False) -> Shipment:
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
    if s is None:
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
        chain=_chain_out(s),
    )


def _chain_out(s: Shipment) -> ChainOut | None:
    chain = get_chain()
    if chain is None:
        return None
    return ChainOut(
        program_id=str(chain.program_id),
        address=str(shipment_address(s, chain)),
        explorer_cluster=chain.explorer_cluster,
    )


def _committed(db: Session, shipment_id: str, role: Actor, tasks: BackgroundTasks) -> ShipmentDetail:
    """Commit the write, then (after the response) mirror it on-chain if a chain is configured."""
    db.commit()
    if get_chain() is not None:
        sessions = sessionmaker(bind=db.get_bind(), autoflush=False, expire_on_commit=False)
        tasks.add_task(anchor_in_background, sessions, shipment_id)
    return _detail(_load(db, shipment_id), role)


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
def list_shipments(db: Db, role: Role) -> list[ShipmentSummary]:
    shipments = db.scalars(select(Shipment).options(selectinload(Shipment.agreement)).order_by(Shipment.id.desc()))
    return [ShipmentSummary(**_summary_fields(s)) for s in shipments]


@router.get("/shipments/{shipment_id}")
def get_shipment(shipment_id: str, db: Db, role: Role) -> ShipmentDetail:
    return _detail(_load(db, shipment_id), role)


@router.get("/shipments/{shipment_id}/audit")
def get_audit(shipment_id: str, db: Db, role: Role) -> AuditOut:
    s = _load(db, shipment_id)
    result: ChainVerification = verify_chain(db, s)
    return AuditOut(
        shipment_id=s.id,
        verified=result.verified,
        checked=result.checked,
        events=tuple(_event(e) for e in s.events),
        checks=result.events,
    )


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
def create_shipment(body: NewShipment, db: Db, role: Role, tasks: BackgroundTasks) -> ShipmentDetail:
    s = ops.create_shipment(
        db, role, title=body.title, buyer=BUYER, supplier=body.supplier, terms=body.terms, now=_now()
    )
    return _committed(db, s.id, role, tasks)


@router.post("/shipments/{shipment_id}/agreement/approve")
def approve_agreement(shipment_id: str, db: Db, role: Role, tasks: BackgroundTasks) -> ShipmentDetail:
    ops.approve_agreement(_load(db, shipment_id, lock=True), role, _now())
    return _committed(db, shipment_id, role, tasks)


@router.post("/shipments/{shipment_id}/evidence")
def upload_evidence(
    shipment_id: str,
    db: Db,
    role: Role,
    root: EvidenceRoot,
    tasks: BackgroundTasks,
    files: Annotated[list[UploadFile], File()],
) -> ShipmentDetail:
    s = _load(db, shipment_id, lock=True)
    ops.upload_slot(s, role)  # 403/409 before looking at the files
    if len(files) > settings.max_evidence_files:
        raise HTTPException(413, f"At most {settings.max_evidence_files} files per upload")
    written = ops.add_evidence(s, role, [_read_image(f) for f in files], root, _now())
    try:
        return _committed(db, shipment_id, role, tasks)
    except Exception:
        for path in written:
            path.unlink(missing_ok=True)
        raise


@router.post("/shipments/{shipment_id}/inspect")
def inspect(
    shipment_id: str, db: Db, role: Role, root: EvidenceRoot, provider: Provider, tasks: BackgroundTasks
) -> ShipmentDetail:
    ops.run_inspection(_load(db, shipment_id, lock=True), role, provider, root, _now())
    return _committed(db, shipment_id, role, tasks)


@router.post("/shipments/{shipment_id}/accept")
def accept(shipment_id: str, db: Db, role: Role, tasks: BackgroundTasks) -> ShipmentDetail:
    ops.accept_adjustment(_load(db, shipment_id, lock=True), role, _now())
    return _committed(db, shipment_id, role, tasks)


@router.post("/shipments/{shipment_id}/dispute")
def dispute(
    shipment_id: str, db: Db, role: Role, tasks: BackgroundTasks, body: DisputeIn | None = None
) -> ShipmentDetail:
    ops.dispute_adjustment(_load(db, shipment_id, lock=True), role, body.reason if body else None, _now())
    return _committed(db, shipment_id, role, tasks)


@router.post("/findings/{finding_id}/review")
def review_finding(finding_id: str, body: ReviewIn, db: Db, role: Role, tasks: BackgroundTasks) -> ShipmentDetail:
    row = db.get(FindingRow, finding_id)
    if row is None:
        raise HTTPException(404, f"Unknown finding {finding_id}")
    s = _load(db, row.shipment_id, lock=True)
    ops.review(s, row, role, body.decision, _now())
    return _committed(db, s.id, role, tasks)


@router.post("/shipments/{shipment_id}/resolve")
def resolve(shipment_id: str, db: Db, role: Role, tasks: BackgroundTasks) -> ShipmentDetail:
    ops.resolve_dispute(_load(db, shipment_id, lock=True), role, _now())
    return _committed(db, shipment_id, role, tasks)


@router.post("/shipments/{shipment_id}/chain/anchor")
def anchor(shipment_id: str, db: Db, role: Role) -> ShipmentDetail:
    """Send whatever of this shipment's history isn't on-chain yet, now (retries failures)."""
    chain = get_chain()
    if chain is None:
        raise HTTPException(409, "Solana anchoring is not configured")
    _load(db, shipment_id)  # 404 for an unknown id
    anchor_shipment(db, shipment_id, chain)
    return _detail(_load(db, shipment_id), role)


@router.post("/shipments/{shipment_id}/audit/verify")
def verify_audit(shipment_id: str, db: Db, role: Role, root: EvidenceRoot) -> ops.Verification:
    # The chain is read first, without the row lock, so a slow RPC doesn't hold up writes.
    report = check_shipment(_load(db, shipment_id), get_chain())
    chain = ops.ChainCheck(available=report.available, anchored=report.anchored, mismatches=report.mismatches)
    result = ops.verify(_load(db, shipment_id, lock=True), root, _now(), chain=chain)
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
