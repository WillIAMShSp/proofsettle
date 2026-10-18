"""Reset the database and load the demo shipments: uv run python -m app.seed_db

PS-1042 (Proposed), PS-1038 (In Transit) and PS-1031 (Resolved), as API_CONTRACT.md
describes. Each shipment is replayed through the workflow (transition, review_finding,
resolve) and every step is logged with append_event, so the stored statuses follow the
rules and every audit chain verifies. Evidence files are the frontend's demo photos
(src/assets/dispatch.jpg and receipt.jpg), copied into the evidence store with their
real SHA-256.
"""

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.audit import EventType, append_event, iso_utc
from app.db import create_tables, drop_tables, engine
from app.findings import Finding
from app.hashing import hash_json, sha256_hex, shipment_uuid
from app.models import AdjustmentRow, Agreement, Evidence, EvidenceKind, FindingRow, Shipment
from app.operations import adjustment_payload
from app.resolution import resolve, review_finding
from app.seed import PS_1031_FINDINGS, PS_1031_TERMS, PS_1038_TERMS, PS_1042_FINDINGS, PS_1042_TERMS
from app.settlement import Adjustment, compute_adjustment, usd
from app.storage import EvidenceStore, LocalStore, SupabaseStore, default_store
from app.terms import AgreementTerms
from app.workflow import Actor, Status, transition

ASSETS = Path(__file__).resolve().parents[2] / "src" / "assets"
PHOTOS = {EvidenceKind.DISPATCH: ASSETS / "dispatch.jpg", EvidenceKind.RECEIPT: ASSETS / "receipt.jpg"}
BUYER = "Northgate Assembly Ltd"


def at(month: int, day: int, hour: int, minute: int) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=UTC)


class _Builder:
    """Replays one shipment's history, logging each step to its audit chain."""

    def __init__(self, db: Session, store: EvidenceStore, shipment: Shipment) -> None:
        self.db, self.store, self.s = db, store, shipment
        db.add(shipment)
        db.flush()

    def move(self, target: Status, actor: Actor, reason: str | None = None, **guards: object) -> dict[str, str]:
        before = self.s.status
        self.s.status = transition(before, target, actor, reason, **guards)
        return {"from": before.value, "to": target.value}

    def draft(self, agreement_id: str, terms: AgreementTerms, when: datetime, text: str) -> None:
        self.agreement = Agreement(
            id=agreement_id, shipment_id=self.s.id, terms=terms.model_dump(mode="json"), terms_hash=hash_json(terms)
        )
        self.terms = terms
        self.db.add(self.agreement)
        append_event(
            self.s,
            EventType.AGREEMENT_DRAFTED,
            Actor.BUYER,
            {"agreementId": agreement_id, "termsHash": self.agreement.terms_hash},
            text=text,
            at=when,
        )

    def approve(self, buyer_at: datetime, supplier_at: datetime) -> None:
        self.agreement.buyer_approved_at = buyer_at
        self.agreement.supplier_approved_at = supplier_at
        payload = {
            "termsHash": self.agreement.terms_hash,
            "buyerApprovedAt": iso_utc(buyer_at),
            "supplierApprovedAt": iso_utc(supplier_at),
            "status": self.move(Status.AGREED, Actor.SYSTEM),
        }
        append_event(
            self.s,
            EventType.AGREEMENT_APPROVED,
            Actor.SUPPLIER,
            payload,
            text="Agreement approved by both parties",
            at=supplier_at,
        )

    def photos(self, kind: EvidenceKind, ids: list[str], when: datetime, *, status: Status | None = None) -> None:
        actor = Actor.SUPPLIER if kind is EvidenceKind.DISPATCH else Actor.BUYER
        data = PHOTOS[kind].read_bytes()
        records = []
        for ev_id in ids:
            file_name = f"{ev_id}.jpg"
            self.store.put(file_name, data, "image/jpeg")
            ev = Evidence(
                id=ev_id,
                shipment_id=self.s.id,
                kind=kind,
                file_name=file_name,
                content_type="image/jpeg",
                sha256=sha256_hex(data),
                uploaded_by=actor,
                uploaded_at=when,
                verified=None,
            )
            self.db.add(ev)
            records.append({"id": ev_id, "sha256": ev.sha256})
        payload: dict[str, object] = {"kind": kind.value, "evidence": records}
        if status is not None:
            payload["status"] = self.move(status, actor)
        label = "Dispatch" if kind is EvidenceKind.DISPATCH else "Receipt"
        append_event(
            self.s, EventType.EVIDENCE_UPLOADED, actor, payload, text=f"{label} photos uploaded ({len(ids)})", at=when
        )

    def in_transit(self, when: datetime) -> None:
        append_event(
            self.s,
            EventType.STATUS_CHANGED,
            Actor.SUPPLIER,
            {"status": self.move(Status.IN_TRANSIT, Actor.SUPPLIER)},
            text="Shipment marked In Transit",
            at=when,
        )

    def inspect(self, findings: tuple[Finding, ...], when: datetime, text: str) -> None:
        for f in findings:
            self.db.add(FindingRow.from_finding(self.s.id, f))
        self.findings = list(findings)
        append_event(
            self.s,
            EventType.INSPECTION_COMPLETED,
            Actor.AI,
            {"findingIds": [f.id for f in findings], "findingsHash": hash_json(findings)},
            text=text,
            at=when,
        )

    def propose(self, adjustment_id: str, when: datetime) -> Adjustment:
        adj = compute_adjustment(self.terms, self.findings)
        self.adjustment = AdjustmentRow(
            id=adjustment_id,
            shipment_id=self.s.id,
            computed_at=when,
            confirmed_defects=adj.confirmed_defects,
            credit=adj.credit,
            settlement_amount=adj.settlement_amount,
        )
        self.db.add(self.adjustment)
        payload = adjustment_payload(adjustment_id, adj) | {"status": self.move(Status.PROPOSED, Actor.SYSTEM)}
        append_event(
            self.s,
            EventType.ADJUSTMENT_PROPOSED,
            Actor.SYSTEM,
            payload,
            text=f"Adjustment proposed from agreement rule: {usd(adj.credit)}",
            at=when,
        )
        return adj

    def dispute(self, actor: Actor, reason: str, when: datetime) -> None:
        self.s.dispute_reason = reason
        payload = {"reason": reason, "status": self.move(Status.DISPUTED, actor, reason)}
        append_event(
            self.s, EventType.ADJUSTMENT_DISPUTED, actor, payload, text=f"Adjustment disputed: {reason}", at=when
        )

    def review(self, finding_id: str, decision: str, when: datetime) -> None:
        i = next(i for i, f in enumerate(self.findings) if f.id == finding_id)
        reviewed = review_finding(self.s.status, self.findings[i], decision, Actor.REVIEWER, when)  # type: ignore[arg-type]
        self.findings[i] = reviewed
        row = self.db.get(FindingRow, finding_id)
        assert row is not None
        row.review_override, row.reviewed_by, row.reviewed_at = decision, Actor.REVIEWER, when
        append_event(
            self.s,
            EventType.FINDING_REVIEWED,
            Actor.REVIEWER,
            {"findingId": finding_id, "decision": decision, "finding": reviewed},
            text=f"Reviewer {decision} {finding_id} ({reviewed.unit_ref})",
            at=when,
        )

    def resolve(self, when: datetime) -> Adjustment:
        before = self.s.status
        self.s.status, adj = resolve(before, self.terms, self.findings, Actor.REVIEWER)
        self.adjustment.computed_at = when
        self.adjustment.confirmed_defects = adj.confirmed_defects
        self.adjustment.credit = adj.credit
        self.adjustment.settlement_amount = adj.settlement_amount
        payload = adjustment_payload(self.adjustment.id, adj) | {
            "status": {"from": before.value, "to": self.s.status.value}
        }
        append_event(
            self.s,
            EventType.DISPUTE_RESOLVED,
            Actor.REVIEWER,
            payload,
            text=f"Dispute resolved: {usd(adj.credit)} credit",
            at=when,
        )
        return adj


def _new(db: Session, store: EvidenceStore, id: str, title: str, supplier: str, created: datetime) -> _Builder:
    shipment = Shipment(
        id=id,
        chain_uuid=shipment_uuid(id),
        title=title,
        buyer=BUYER,
        supplier=supplier,
        status=Status.DRAFT,
        created_at=created,
    )
    return _Builder(db, store, shipment)


def seed(db: Session, store: EvidenceStore) -> None:
    """Load the three demo shipments into an empty database."""

    # PS-1042: the shipment the detail page shows. Event texts are store.tsx's, verbatim.
    b = _new(db, store, "PS-1042", "100 metal components", "Ferro Precision Works", at(10, 9, 10, 12))
    b.draft("agr_01", PS_1042_TERMS, at(10, 9, 10, 12), "Agreement drafted: 100 components, $10,000")
    b.approve(buyer_at=at(10, 9, 10, 12), supplier_at=at(10, 9, 14, 40))
    b.photos(EvidenceKind.DISPATCH, ["ev_01", "ev_02", "ev_03", "ev_04"], at(10, 11, 8, 5))
    b.in_transit(at(10, 11, 9, 30))
    b.photos(EvidenceKind.RECEIPT, ["ev_05", "ev_06", "ev_07", "ev_08"], at(10, 15, 16, 22), status=Status.INSPECTION)
    b.inspect(PS_1042_FINDINGS, at(10, 15, 16, 31), "Inspection complete: 3 defects flagged")
    b.propose("adj_01", at(10, 15, 16, 32))

    # PS-1038: dispatched, not yet received.
    b = _new(db, store, "PS-1038", "40 hydraulic valves", "Kestrel Fluid Systems", at(10, 12, 9, 0))
    b.draft("agr_02", PS_1038_TERMS, at(10, 12, 9, 0), "Agreement drafted: 40 valves, $6,400")
    b.approve(buyer_at=at(10, 12, 9, 0), supplier_at=at(10, 12, 15, 20))
    b.photos(EvidenceKind.DISPATCH, ["ev_09", "ev_10", "ev_11", "ev_12"], at(10, 14, 7, 45))
    b.in_transit(at(10, 14, 8, 10))

    # PS-1031: proposed, disputed by the Supplier, resolved by the Reviewer.
    b = _new(db, store, "PS-1031", "250 steel brackets", "Ferro Precision Works", at(9, 14, 11, 0))
    b.draft("agr_03", PS_1031_TERMS, at(9, 14, 11, 0), "Agreement drafted: 250 brackets, $3,750")
    b.approve(buyer_at=at(9, 14, 11, 0), supplier_at=at(9, 15, 9, 30))
    b.photos(EvidenceKind.DISPATCH, ["ev_13", "ev_14", "ev_15", "ev_16"], at(9, 18, 7, 30))
    b.in_transit(at(9, 18, 8, 0))
    b.photos(EvidenceKind.RECEIPT, ["ev_17", "ev_18", "ev_19", "ev_20"], at(9, 22, 10, 5), status=Status.INSPECTION)
    b.inspect(PS_1031_FINDINGS, at(9, 22, 10, 20), "Inspection complete: 3 defects flagged")
    b.propose("adj_02", at(9, 22, 10, 21))
    b.dispute(Actor.SUPPLIER, "Bracket #101 shows a weld seam, not a crack", at(9, 23, 14, 0))
    b.review("fnd_07", "rejected", at(9, 25, 10, 0))
    b.review("fnd_08", "rejected", at(9, 25, 10, 5))
    b.resolve(at(9, 25, 10, 10))

    db.flush()


def reset_and_seed(bind: Engine, store: EvidenceStore) -> None:
    drop_tables(bind)
    create_tables(bind)
    store.clear()
    with Session(bind) as db:
        seed(db, store)
        db.commit()


def main() -> None:
    url = engine.url.render_as_string(hide_password=True)
    print(f"Resetting {url} and loading PS-1042, PS-1038, PS-1031")
    store = default_store()
    reset_and_seed(engine, store)
    where = f"bucket {store.bucket!r}" if isinstance(store, SupabaseStore) else "?"
    if isinstance(store, LocalStore):
        where = str(store.root.resolve())
    print(f"Done. Evidence files in {where}")


if __name__ == "__main__":
    main()
