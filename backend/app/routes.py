"""Read endpoints for the frontend (API_CONTRACT.md). No writes yet.

Every /shipments route needs X-Demo-Role: Buyer | Supplier | Reviewer (400 otherwise),
which decides the `actions` flags. GET /evidence/{id}/file does not, because an <img src>
can't send headers.
"""

from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import AwareDatetime
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.audit import ChainVerification, EventCheck, verify_chain
from app.config import settings
from app.db import get_db
from app.findings import Finding
from app.models import AdjustmentRow, AuditEvent, ChainStatus, Evidence, Shipment
from app.money import Money
from app.schemas import CamelModel
from app.settlement import Adjustment, compute_adjustment
from app.terms import AgreementTerms
from app.workflow import Actor, AdjustmentAcceptance, Status, can_accept, can_dispute

router = APIRouter()

DEMO_ROLES = (Actor.BUYER, Actor.SUPPLIER, Actor.REVIEWER)


def demo_role(x_demo_role: Annotated[str | None, Header()] = None) -> Actor:
    if x_demo_role not in {r.value for r in DEMO_ROLES}:
        raise HTTPException(400, "X-Demo-Role header must be Buyer, Supplier or Reviewer")
    return Actor(x_demo_role)


def evidence_dir() -> Path:
    return settings.evidence_dir


Db = Annotated[Session, Depends(get_db)]
Role = Annotated[Actor, Depends(demo_role)]


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


def _load(db: Session, shipment_id: str) -> Shipment:
    s = db.scalars(
        select(Shipment)
        .where(Shipment.id == shipment_id)
        .options(
            selectinload(Shipment.agreement),
            selectinload(Shipment.evidence),
            selectinload(Shipment.findings),
            selectinload(Shipment.adjustment),
            selectinload(Shipment.events),
        )
    ).one_or_none()
    if s is None:
        raise HTTPException(404, f"Unknown shipment {shipment_id}")
    return s


# --- Routes -------------------------------------------------------------------------------


@router.get("/shipments")
def list_shipments(db: Db, role: Role) -> list[ShipmentSummary]:
    shipments = db.scalars(select(Shipment).options(selectinload(Shipment.agreement)).order_by(Shipment.id.desc()))
    return [ShipmentSummary(**_summary_fields(s)) for s in shipments]


@router.get("/shipments/{shipment_id}")
def get_shipment(shipment_id: str, db: Db, role: Role) -> ShipmentDetail:
    s = _load(db, shipment_id)
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
def get_evidence_file(evidence_id: str, db: Db, root: Annotated[Path, Depends(evidence_dir)]) -> FileResponse:
    ev = db.get(Evidence, evidence_id)
    if ev is None:
        raise HTTPException(404, f"Unknown evidence {evidence_id}")
    base = root.resolve()
    path = (base / ev.file_name).resolve()
    if not path.is_relative_to(base) or not path.is_file():
        raise HTTPException(404, f"File for evidence {evidence_id} is missing")
    return FileResponse(path, media_type=ev.content_type)
