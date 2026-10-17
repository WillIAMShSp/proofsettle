"""Shipment workflow state machine (PRD section 9).

Status values are the exact strings the frontend uses in src/lib/store.tsx.
"""

from enum import StrEnum


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
    SYSTEM = "System"
    AI = "AI"


# (from, to) -> actors allowed to trigger it.
TRANSITIONS: dict[tuple[Status, Status], frozenset[Actor]] = {
    (Status.DRAFT, Status.AGREED): frozenset({Actor.SYSTEM}),
    (Status.AGREED, Status.IN_TRANSIT): frozenset({Actor.SUPPLIER}),
    (Status.IN_TRANSIT, Status.INSPECTION): frozenset({Actor.BUYER}),
    (Status.INSPECTION, Status.PROPOSED): frozenset({Actor.SYSTEM}),
    (Status.PROPOSED, Status.ACCEPTED): frozenset({Actor.SUPPLIER}),
    (Status.PROPOSED, Status.DISPUTED): frozenset({Actor.SUPPLIER}),
    (Status.DISPUTED, Status.RESOLVED): frozenset({Actor.BUYER, Actor.SUPPLIER}),
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


def next_statuses(current: Status) -> list[Status]:
    return [to for (frm, to) in TRANSITIONS if frm == current]


def can_transition(current: Status, target: Status, actor: Actor) -> bool:
    return actor in TRANSITIONS.get((current, target), frozenset())


def transition(current: Status, target: Status, actor: Actor, reason: str | None = None) -> Status:
    """Validate a move from `current` to `target` by `actor` and return the new status."""
    allowed = TRANSITIONS.get((current, target))
    if allowed is None:
        raise IllegalTransition(f"Cannot move from {current} to {target}")
    if actor not in allowed:
        raise NotPermitted(f"{actor} cannot move a shipment from {current} to {target}")
    if target in REASON_REQUIRED and not (reason and reason.strip()):
        raise ReasonRequired(f"A reason is required to move to {target}")
    return target
