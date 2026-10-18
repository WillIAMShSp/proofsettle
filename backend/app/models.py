"""Database tables. FastAPI owns this schema and is the only writer of business state.

Money columns are MONEY_SQL (NUMERIC(12,2), Decimal). Timestamps are stored as UTC and
always come back timezone-aware, on SQLite as well as Postgres. Agreement terms and
findings keep the camelCase JSON the API uses, so a row can be hashed exactly as served.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.findings import Finding
from app.hashing import canonical_json
from app.money import MONEY_SQL
from app.terms import AgreementTerms
from app.workflow import Actor, Status

HASH = String(64)  # lowercase hex SHA-256


class UTCDateTime(TypeDecorator[datetime]):
    """Aware UTC datetimes in and out. SQLite would otherwise drop the timezone."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime; use an aware UTC datetime")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _enum(cls: type[StrEnum], name: str) -> Enum:
    # Stored as the value ("In Transit"), as VARCHAR + CHECK rather than a native PG enum.
    return Enum(
        cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        values_callable=lambda e: [m.value for m in e],
        length=20,
    )


class EvidenceKind(StrEnum):
    DISPATCH = "dispatch"
    RECEIPT = "receipt"


class ChainStatus(StrEnum):
    PENDING = "pending"  # queued for anchoring
    CONFIRMED = "confirmed"  # chainTxHash is set
    FAILED = "failed"
    SKIPPED = "skipped"  # not anchored (no chain configured)


class Shipment(Base):
    __tablename__ = "shipments"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # "PS-1042"
    # hashing.shipment_uuid(id); the 16-byte seed of the on-chain shipment PDA.
    chain_uuid: Mapped[uuid.UUID] = mapped_column(unique=True)
    title: Mapped[str] = mapped_column(String(200))
    buyer: Mapped[str] = mapped_column(String(200))
    supplier: Mapped[str] = mapped_column(String(200))
    status: Mapped[Status] = mapped_column(_enum(Status, "shipment_status"))
    dispute_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    # Who may see the shipment (app.access). Null on the demo seed, which everyone sees.
    created_by: Mapped[str | None] = mapped_column(String(64))  # Supabase user id
    recipient_email: Mapped[str | None] = mapped_column(String(320), index=True)  # lowercased

    agreement: Mapped["Agreement | None"] = relationship(back_populates="shipment", uselist=False)
    # Ids are sequential ("ev_09", "ev_10", ..., "ev_100"): shorter first, then by text.
    evidence: Mapped[list["Evidence"]] = relationship(
        back_populates="shipment", order_by=lambda: (func.length(Evidence.id), Evidence.id)
    )
    findings: Mapped[list["FindingRow"]] = relationship(
        back_populates="shipment", order_by=lambda: (func.length(FindingRow.id), FindingRow.id)
    )
    adjustment: Mapped["AdjustmentRow | None"] = relationship(back_populates="shipment", uselist=False)
    events: Mapped[list["AuditEvent"]] = relationship(back_populates="shipment", order_by="AuditEvent.seq")
    messages: Mapped[list["ChatMessage"]] = relationship(back_populates="shipment", order_by="ChatMessage.id")


class Agreement(Base):
    __tablename__ = "agreements"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    shipment_id: Mapped[str] = mapped_column(ForeignKey("shipments.id"), unique=True)
    # AgreementTerms as camelCase JSON; terms_hash = hash_json(terms).
    terms: Mapped[dict[str, Any]] = mapped_column(JSON)
    terms_hash: Mapped[str] = mapped_column(HASH)
    buyer_approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    supplier_approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    shipment: Mapped[Shipment] = relationship(back_populates="agreement")

    def parsed_terms(self) -> AgreementTerms:
        # Parsed as JSON, so money arrives the way the API receives it (not as Python floats).
        return AgreementTerms.model_validate_json(canonical_json(self.terms))


class Evidence(Base):
    __tablename__ = "evidence"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # "ev_01"
    shipment_id: Mapped[str] = mapped_column(ForeignKey("shipments.id"), index=True)
    kind: Mapped[EvidenceKind] = mapped_column(_enum(EvidenceKind, "evidence_kind"))
    # Relative to settings.evidence_dir.
    file_name: Mapped[str] = mapped_column(String(200))
    content_type: Mapped[str] = mapped_column(String(100))
    sha256: Mapped[str] = mapped_column(HASH)  # of the raw uploaded bytes
    uploaded_by: Mapped[Actor] = mapped_column(_enum(Actor, "actor"))
    uploaded_at: Mapped[datetime] = mapped_column(UTCDateTime())
    # Result of the last re-hash from storage; None = never checked.
    verified: Mapped[bool | None]

    shipment: Mapped[Shipment] = relationship(back_populates="evidence")


class FindingRow(Base):
    """One app.findings.Finding."""

    __tablename__ = "findings"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # "fnd_01"
    shipment_id: Mapped[str] = mapped_column(ForeignKey("shipments.id"), index=True)
    unit_ref: Mapped[str] = mapped_column(String(100))
    defect_type: Mapped[str] = mapped_column(String(64))
    confidence: Mapped[float] = mapped_column(Float)  # a probability, not money
    evidence_ids: Mapped[list[str]] = mapped_column(JSON)
    description: Mapped[str] = mapped_column(String(500))
    present_in_dispatch: Mapped[bool]
    review_override: Mapped[str | None] = mapped_column(String(16))
    reviewed_by: Mapped[Actor | None] = mapped_column(_enum(Actor, "actor"))
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    shipment: Mapped[Shipment] = relationship(back_populates="findings")

    @classmethod
    def from_finding(cls, shipment_id: str, f: Finding) -> "FindingRow":
        return cls(shipment_id=shipment_id, **f.model_dump(by_alias=False))

    def to_finding(self) -> Finding:
        return Finding(
            id=self.id,
            unit_ref=self.unit_ref,
            defect_type=self.defect_type,
            confidence=self.confidence,
            evidence_ids=tuple(self.evidence_ids),
            description=self.description,
            present_in_dispatch=self.present_in_dispatch,
            review_override=self.review_override,
            reviewed_by=self.reviewed_by,
            reviewed_at=self.reviewed_at,
        )


class AdjustmentRow(Base):
    """The proposed (later resolved) adjustment and each party's acceptance of it.

    The amounts are a snapshot of compute_adjustment at computed_at. The API serves a fresh
    compute_adjustment over the stored terms and findings; the two only differ while a
    Reviewer is part-way through reviewing a dispute.
    """

    __tablename__ = "adjustments"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # "adj_01"
    shipment_id: Mapped[str] = mapped_column(ForeignKey("shipments.id"), unique=True)
    computed_at: Mapped[datetime] = mapped_column(UTCDateTime())
    confirmed_defects: Mapped[int] = mapped_column(Integer)
    credit: Mapped[Decimal] = mapped_column(MONEY_SQL)
    settlement_amount: Mapped[Decimal] = mapped_column(MONEY_SQL)
    buyer_accepted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    supplier_accepted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    shipment: Mapped[Shipment] = relationship(back_populates="adjustment")


class AuditEvent(Base):
    """One link of a shipment's hash chain; see app.audit for how the hashes are built."""

    __tablename__ = "audit_events"
    __table_args__ = (UniqueConstraint("shipment_id", "seq"),)

    id: Mapped[int] = mapped_column(primary_key=True)  # served as "evt_01"
    shipment_id: Mapped[str] = mapped_column(ForeignKey("shipments.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)  # 1, 2, ... per shipment
    at: Mapped[datetime] = mapped_column(UTCDateTime())
    actor: Mapped[Actor] = mapped_column(_enum(Actor, "actor"))
    type: Mapped[str] = mapped_column(String(64))
    text: Mapped[str] = mapped_column(String(500))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    payload_hash: Mapped[str] = mapped_column(HASH)
    prev_event_hash: Mapped[str | None] = mapped_column(HASH)
    event_hash: Mapped[str] = mapped_column(HASH)
    chain_tx_hash: Mapped[str | None] = mapped_column(String(128))  # Solana signature, base58
    chain_status: Mapped[ChainStatus] = mapped_column(_enum(ChainStatus, "chain_status"))

    shipment: Mapped[Shipment] = relationship(back_populates="events")

    @property
    def public_id(self) -> str:
        return f"evt_{self.id:02d}"


class ChatMessage(Base):
    """One message in a shipment's Buyer ↔ Supplier conversation.

    Chat is not settlement state: it never moves a status or an amount, and it is not part
    of the audit hash chain or anchored on Solana. It is scoped to the shipment, so whoever
    can see the shipment (app.access) can read it.
    """

    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True)  # served as "msg_01"
    shipment_id: Mapped[str] = mapped_column(ForeignKey("shipments.id"), index=True)
    author_role: Mapped[Actor] = mapped_column(_enum(Actor, "actor"))
    # The sender's Supabase user id; null for a dev login, which has no account.
    author_user_id: Mapped[str | None] = mapped_column(String(64))
    author_name: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(UTCDateTime())
    # An invoice message carries the invoice as issued (routes.InvoiceOut, camelCase JSON):
    # a snapshot, so later changes to the shipment never rewrite an invoice already sent.
    # none_as_null: a plain message stores SQL NULL, so "is an invoice" is `invoice IS NOT NULL`.
    invoice: Mapped[dict[str, Any] | None] = mapped_column(JSON(none_as_null=True))

    shipment: Mapped[Shipment] = relationship(back_populates="messages")

    @property
    def public_id(self) -> str:
        return f"msg_{self.id:02d}"
