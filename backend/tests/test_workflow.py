import pytest

from app.workflow import (
    TERMINAL,
    TRANSITIONS,
    Actor,
    IllegalTransition,
    NotPermitted,
    ReasonRequired,
    Status,
    can_transition,
    next_statuses,
    transition,
)

# Copied from src/lib/store.tsx; the API must use these exact strings.
FRONTEND_STATUSES = ["Draft", "Agreed", "In Transit", "Inspection", "Proposed", "Accepted", "Disputed", "Resolved"]


def test_status_values_match_frontend():
    assert [s.value for s in Status] == FRONTEND_STATUSES


def test_happy_path():
    steps = [
        (Status.AGREED, Actor.SYSTEM),
        (Status.IN_TRANSIT, Actor.SUPPLIER),
        (Status.INSPECTION, Actor.BUYER),
        (Status.PROPOSED, Actor.SYSTEM),
        (Status.ACCEPTED, Actor.SUPPLIER),
    ]
    s = Status.DRAFT
    for target, actor in steps:
        s = transition(s, target, actor)
    assert s is Status.ACCEPTED


def test_dispute_path():
    s = transition(Status.PROPOSED, Status.DISPUTED, Actor.SUPPLIER, reason="Defects predate dispatch")
    assert transition(s, Status.RESOLVED, Actor.BUYER) is Status.RESOLVED


@pytest.mark.parametrize("reason", [None, "", "   "])
def test_dispute_requires_reason(reason):
    with pytest.raises(ReasonRequired):
        transition(Status.PROPOSED, Status.DISPUTED, Actor.SUPPLIER, reason=reason)


@pytest.mark.parametrize("target", [Status.ACCEPTED, Status.DISPUTED])
def test_buyer_cannot_decide(target):
    with pytest.raises(NotPermitted):
        transition(Status.PROPOSED, target, Actor.BUYER, reason="x")


def test_ai_cannot_propose():
    # The rules engine (System) proposes; AI only supplies findings.
    with pytest.raises(NotPermitted):
        transition(Status.INSPECTION, Status.PROPOSED, Actor.AI)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (Status.DRAFT, Status.PROPOSED),
        (Status.AGREED, Status.DRAFT),
        (Status.ACCEPTED, Status.DISPUTED),
        (Status.RESOLVED, Status.PROPOSED),
        (Status.PROPOSED, Status.RESOLVED),
        (Status.PROPOSED, Status.PROPOSED),
    ],
)
def test_illegal_transitions(current, target):
    with pytest.raises(IllegalTransition):
        transition(current, target, Actor.SYSTEM, reason="x")


def test_terminal_states_have_no_exits():
    for s in TERMINAL:
        assert next_statuses(s) == []
    assert {s for s in Status if not next_statuses(s)} == TERMINAL


def test_every_status_reachable_from_draft():
    seen, frontier = {Status.DRAFT}, [Status.DRAFT]
    while frontier:
        for nxt in next_statuses(frontier.pop()):
            if nxt not in seen:
                seen.add(nxt)
                frontier.append(nxt)
    assert seen == set(Status)


def test_can_transition_matches_table():
    for current in Status:
        for target in Status:
            for actor in Actor:
                assert can_transition(current, target, actor) == (actor in TRANSITIONS.get((current, target), ()))


def test_error_status_codes():
    assert IllegalTransition.status_code == 409
    assert NotPermitted.status_code == 403
    assert ReasonRequired.status_code == 400
