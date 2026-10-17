from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.resolution import resolve, review_finding
from app.seed import PS_1042_FINDINGS, PS_1042_TERMS
from app.settlement import compute_adjustment
from app.workflow import Actor, NotPermitted, PreconditionFailed, Status, transition

D = Decimal
REVIEWED_AT = datetime(2026, 10, 16, 14, 0, tzinfo=UTC)


def review(findings, finding_id, decision, current=Status.DISPUTED, actor=Actor.REVIEWER):
    return [
        review_finding(current, f, decision, actor, REVIEWED_AT) if f.id == finding_id else f for f in findings
    ]


def test_buyer_disputes_063_reviewer_confirms_engine_resolves():
    proposed = compute_adjustment(PS_1042_TERMS, PS_1042_FINDINGS)
    assert (proposed.credit, proposed.settlement_amount) == (D("300"), D("9700"))
    assert [o.finding_id for o in proposed.needs_review] == ["fnd_04"]

    s = transition(Status.PROPOSED, Status.DISPUTED, Actor.BUYER, reason="Component #063 is discoloured")
    findings = review(PS_1042_FINDINGS, "fnd_04", "confirmed", current=s)
    s, adj = resolve(s, PS_1042_TERMS, findings, Actor.REVIEWER)

    assert s is Status.RESOLVED
    assert adj.credit == D("400")
    assert adj.settlement_amount == D("9600")
    assert adj.applied_rule.credit == "4 × $100 = $400"
    assert adj.needs_review == ()
    assert adj.status == "ready"
    assert next(f for f in findings if f.id == "fnd_04").reviewed_by is Actor.REVIEWER


def test_reviewer_rejects_063_keeps_proposed_amount():
    findings = review(PS_1042_FINDINGS, "fnd_04", "rejected")
    s, adj = resolve(Status.DISPUTED, PS_1042_TERMS, findings, Actor.REVIEWER)
    assert s is Status.RESOLVED
    assert (adj.credit, adj.settlement_amount) == (D("300"), D("9700"))


def test_cannot_resolve_while_needs_review_non_empty():
    with pytest.raises(PreconditionFailed):
        resolve(Status.DISPUTED, PS_1042_TERMS, PS_1042_FINDINGS, Actor.REVIEWER)


def test_reviewing_a_counted_finding_does_not_unblock_resolution():
    findings = review(PS_1042_FINDINGS, "fnd_01", "rejected")
    with pytest.raises(PreconditionFailed):
        resolve(Status.DISPUTED, PS_1042_TERMS, findings, Actor.REVIEWER)


@pytest.mark.parametrize("actor", [a for a in Actor if a is not Actor.REVIEWER])
def test_only_reviewer_reviews_findings(actor):
    with pytest.raises(NotPermitted):
        review(PS_1042_FINDINGS, "fnd_04", "confirmed", actor=actor)


@pytest.mark.parametrize("actor", [a for a in Actor if a is not Actor.REVIEWER])
def test_only_reviewer_resolves(actor):
    findings = review(PS_1042_FINDINGS, "fnd_04", "confirmed")
    with pytest.raises(NotPermitted):
        resolve(Status.DISPUTED, PS_1042_TERMS, findings, actor)


@pytest.mark.parametrize("current", [s for s in Status if s is not Status.DISPUTED])
def test_findings_reviewed_only_while_disputed(current):
    with pytest.raises(PreconditionFailed):
        review(PS_1042_FINDINGS, "fnd_04", "confirmed", current=current)
