"""Shipment workflow state machine (PRD section 9).

Status values are the exact strings the frontend uses in src/lib/store.tsx.

Two transitions carry a guard on top of the role check:

- Proposed -> Accepted needs both parties' acceptance. Each party calls accept(); the
  status changes only once buyerAcceptedAt and supplierAcceptedAt are both set.
- Disputed -> Resolved needs the recomputed adjustment to have nothing left in
  needsReview. app.resolution owns that step; the resolved amount is the engine's output.
"""

from enum import StrEnum

from pydantic import AwareDatetime

from app.schemas import CamelModel


class Status(StrEnum):
    DRAFT = "Draft"
    AGREED = "Agreed"
    IN_TRANSIT = "In Transit"
    INSPECTION = "Inspection"
    PROPOSED = "Proposed"
    ACCEPTED = "Accepted"
    DISPUTED = "Disputed"
    RESOLVED = "Resolved"


class Actor(StrEnum):
    BUYER = "Buyer"
    SUPPLIER = "Supplier"
    REVIEWER = "Reviewer"
    SYSTEM = "System"
    AI = "AI"


# (from, to) -> actors allowed to trigger it. There is deliberately no
# Disputed -> Proposed path: a dispute ends only in Resolved.
TRANSITIONS: dict[tuple[Status, Status], frozenset[Actor]] = {
    (Status.DRAFT, Status.AGREED): frozenset({Actor.SYSTEM}),
    (Status.AGREED, Status.IN_TRANSIT): frozenset({Actor.SUPPLIER}),
    (Status.IN_TRANSIT, Status.INSPECTION): frozenset({Actor.BUYER}),
    (Status.INSPECTION, Status.PROPOSED): frozenset({Actor.SYSTEM}),
    # Each party may accept, but the move happens only once both have (see accept()).
    (Status.PROPOSED, Status.ACCEPTED): frozenset({Actor.BUYER, Actor.SUPPLIER}),
    (Status.PROPOSED, Status.DISPUTED): frozenset({Actor.BUYER, Actor.SUPPLIER}),
    # Neither party may resolve its own dispute.
    (Status.DISPUTED, Status.RESOLVED): frozenset({Actor.REVIEWER}),
}

REASON_REQUIRED: frozenset[Status] = frozenset({Status.DISPUTED})
TERMINAL: frozenset[Status] = frozenset({Status.ACCEPTED, Status.RESOLVED})


class TransitionError(Exception):
    """Base class; `status_code` is the HTTP code the API should map it to."""

    status_code = 400


class IllegalTransition(TransitionError):
    status_code = 409


class NotPermitted(TransitionError):
    status_code = 403


class ReasonRequired(TransitionError):
    status_code = 400


class PreconditionFailed(TransitionError):
    """The role may make this move, but the shipment isn't ready for it yet."""

    status_code = 409


class AdjustmentAcceptance(CamelModel):
    """Per-party acceptance of the proposed adjustment."""

    buyer_accepted_at: AwareDatetime | None = None
    supplier_accepted_at: AwareDatetime | None = None

    def accepted_by(self, actor: Actor) -> bool:
        field = _ACCEPTED_AT.get(actor)
        return field is not None and getattr(self, field) is not None

    @property
    def complete(self) -> bool:
        return self.buyer_accepted_at is not None and self.supplier_accepted_at is not None


_ACCEPTED_AT = {Actor.BUYER: "buyer_accepted_at", Actor.SUPPLIER: "supplier_accepted_at"}


def next_statuses(current: Status) -> list[Status]:
    return [to for (frm, to) in TRANSITIONS if frm == current]


def can_transition(current: Status, target: Status, actor: Actor) -> bool:
    return actor in TRANSITIONS.get((current, target), frozenset())


def can_accept(current: Status, actor: Actor, acceptance: AdjustmentAcceptance) -> bool:
    return can_transition(current, Status.ACCEPTED, actor) and not acceptance.accepted_by(actor)


def can_dispute(current: Status, actor: Actor, acceptance: AdjustmentAcceptance) -> bool:
    return can_transition(current, Status.DISPUTED, actor) and not acceptance.accepted_by(actor)


def transition(
    current: Status,
    target: Status,
    actor: Actor,
    reason: str | None = None,
    *,
    acceptance: AdjustmentAcceptance | None = None,
    pending_review: int | None = None,
) -> Status:
    """Validate a move from `current` to `target` by `actor` and return the new status.

    `acceptance` is the adjustment's per-party acceptance; Accepted needs it complete, and
    a party that has accepted can no longer dispute. `pending_review` is the number of
    findings in the recomputed adjustment's needsReview; Resolved needs it to be 0. Leaving
    either out means "unknown", which fails the guard that needs it.
    """
    allowed = TRANSITIONS.get((current, target))
    if allowed is None:
        raise IllegalTransition(f"Cannot move from {current} to {target}")
    if actor not in allowed:
        raise NotPermitted(f"{actor} cannot move a shipment from {current} to {target}")
    if target in REASON_REQUIRED and not (reason and reason.strip()):
        raise ReasonRequired(f"A reason is required to move to {target}")
    if target is Status.ACCEPTED and not (acceptance and acceptance.complete):
        raise PreconditionFailed("Both Buyer and Supplier must accept the adjustment")
    if target is Status.DISPUTED and acceptance and acceptance.accepted_by(actor):
        raise PreconditionFailed(f"{actor} has already accepted the adjustment")
    if target is Status.RESOLVED and pending_review != 0:
        raise PreconditionFailed("Every finding in needsReview must be confirmed or rejected first")
    return target


def accept(
    current: Status, actor: Actor, acceptance: AdjustmentAcceptance, at: AwareDatetime
) -> tuple[Status, AdjustmentAcceptance]:
    """Record `actor`'s acceptance at `at`; the status becomes Accepted once both have accepted.

    Accepting twice is a no-op that keeps the first timestamp.
    """
    allowed = TRANSITIONS.get((current, Status.ACCEPTED))
    if allowed is None:
        raise IllegalTransition(f"Cannot accept an adjustment while {current}")
    if actor not in allowed:
        raise NotPermitted(f"{actor} cannot accept an adjustment")
    if not acceptance.accepted_by(actor):
        acceptance = acceptance.model_copy(update={_ACCEPTED_AT[actor]: at})
    if acceptance.complete:
        return transition(current, Status.ACCEPTED, actor, acceptance=acceptance), acceptance
    return current, acceptance
