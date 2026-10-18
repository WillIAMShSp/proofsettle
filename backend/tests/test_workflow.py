from datetime import UTC, datetime

import pytest

from app.workflow import (
    TERMINAL,
    TRANSITIONS,
    Actor,
    AdjustmentAcceptance,
    IllegalTransition,
    NotPermitted,
    PreconditionFailed,
    ReasonRequired,
    Status,
    accept,
    can_accept,
    can_dispute,
    can_transition,
    next_statuses,
    transition,
)

T1 = datetime(2026, 10, 16, 9, 0, tzinfo=UTC)
T2 = datetime(2026, 10, 16, 11, 30, tzinfo=UTC)
NONE_YET = AdjustmentAcceptance()
BOTH = AdjustmentAcceptance(buyer_accepted_at=T1, supplier_accepted_at=T2)

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
    ]
    s = Status.DRAFT
    for target, actor in steps:
        s = transition(s, target, actor)
    s, acc = accept(s, Actor.BUYER, NONE_YET, T1)
    s, acc = accept(s, Actor.SUPPLIER, acc, T2)
    assert s is Status.ACCEPTED
    assert acc == BOTH


@pytest.mark.parametrize("first", [Actor.BUYER, Actor.SUPPLIER])
def test_one_party_accepting_stays_proposed(first):
    s, acc = accept(Status.PROPOSED, first, NONE_YET, T1)
    assert s is Status.PROPOSED
    assert acc.accepted_by(first)
    assert not acc.complete
    other = Actor.SUPPLIER if first is Actor.BUYER else Actor.BUYER
    assert not acc.accepted_by(other)
    s, acc = accept(s, other, acc, T2)
    assert s is Status.ACCEPTED


def test_accepting_twice_keeps_first_timestamp():
    s, acc = accept(Status.PROPOSED, Actor.BUYER, NONE_YET, T1)
    s, acc = accept(s, Actor.BUYER, acc, T2)
    assert s is Status.PROPOSED
    assert acc.buyer_accepted_at == T1
    assert acc.supplier_accepted_at is None


@pytest.mark.parametrize("acceptance", [None, NONE_YET, AdjustmentAcceptance(buyer_accepted_at=T1)])
def test_direct_accept_needs_both_parties(acceptance):
    with pytest.raises(PreconditionFailed):
        transition(Status.PROPOSED, Status.ACCEPTED, Actor.SUPPLIER, acceptance=acceptance)


@pytest.mark.parametrize("actor", [Actor.REVIEWER, Actor.SYSTEM, Actor.AI])
def test_only_parties_accept(actor):
    with pytest.raises(NotPermitted):
        accept(Status.PROPOSED, actor, NONE_YET, T1)


@pytest.mark.parametrize("current", [s for s in Status if s is not Status.PROPOSED])
def test_accept_only_while_proposed(current):
    with pytest.raises(IllegalTransition):
        accept(current, Actor.BUYER, NONE_YET, T1)


@pytest.mark.parametrize("actor", [Actor.BUYER, Actor.SUPPLIER])
def test_either_party_disputes(actor):
    s = transition(Status.PROPOSED, Status.DISPUTED, actor, reason="Disagree with #063", acceptance=NONE_YET)
    assert s is Status.DISPUTED


def test_party_that_accepted_cannot_dispute():
    _, acc = accept(Status.PROPOSED, Actor.BUYER, NONE_YET, T1)
    with pytest.raises(PreconditionFailed):
        transition(Status.PROPOSED, Status.DISPUTED, Actor.BUYER, reason="changed my mind", acceptance=acc)
    # The other party still can.
    assert transition(Status.PROPOSED, Status.DISPUTED, Actor.SUPPLIER, reason="x", acceptance=acc) is Status.DISPUTED


def test_actions_per_party():
    _, acc = accept(Status.PROPOSED, Actor.BUYER, NONE_YET, T1)
    assert not can_accept(Status.PROPOSED, Actor.BUYER, acc)
    assert not can_dispute(Status.PROPOSED, Actor.BUYER, acc)
    assert can_accept(Status.PROPOSED, Actor.SUPPLIER, acc)
    assert can_dispute(Status.PROPOSED, Actor.SUPPLIER, acc)
    for actor in (Actor.REVIEWER, Actor.SYSTEM, Actor.AI):
        assert not can_accept(Status.PROPOSED, actor, NONE_YET)
        assert not can_dispute(Status.PROPOSED, actor, NONE_YET)
    for s in Status:
        if s is not Status.PROPOSED:
            assert not can_accept(s, Actor.BUYER, NONE_YET)
            assert not can_dispute(s, Actor.SUPPLIER, NONE_YET)


def test_dispute_path():
    s = transition(Status.PROPOSED, Status.DISPUTED, Actor.SUPPLIER, reason="Defects predate dispatch")
    assert transition(s, Status.RESOLVED, Actor.REVIEWER, pending_review=0) is Status.RESOLVED


@pytest.mark.parametrize("pending", [None, 1, 3])
def test_resolve_needs_empty_review_queue(pending):
    with pytest.raises(PreconditionFailed):
        transition(Status.DISPUTED, Status.RESOLVED, Actor.REVIEWER, pending_review=pending)


@pytest.mark.parametrize("actor", [a for a in Actor if a is not Actor.REVIEWER])
def test_only_reviewer_resolves(actor):
    with pytest.raises(NotPermitted):
        transition(Status.DISPUTED, Status.RESOLVED, actor, pending_review=0)


def test_reviewer_cannot_decide_proposals():
    for target in (Status.ACCEPTED, Status.DISPUTED):
        assert not can_transition(Status.PROPOSED, target, Actor.REVIEWER)


def test_disputed_only_leads_to_resolved():
    assert next_statuses(Status.DISPUTED) == [Status.RESOLVED]
    with pytest.raises(IllegalTransition):
        transition(Status.DISPUTED, Status.PROPOSED, Actor.SYSTEM)


@pytest.mark.parametrize("reason", [None, "", "   "])
def test_dispute_requires_reason(reason):
    with pytest.raises(ReasonRequired):
        transition(Status.PROPOSED, Status.DISPUTED, Actor.SUPPLIER, reason=reason)


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
    assert PreconditionFailed.status_code == 409
