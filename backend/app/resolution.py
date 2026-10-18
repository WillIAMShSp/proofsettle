"""Dispute resolution: a Reviewer rules on findings, then the engine recomputes.

The Reviewer never types in an amount. They set reviewOverride on findings, and the
resolved adjustment is compute_adjustment's output on the reviewed findings. Disputed ->
Resolved is allowed only once that output has nothing left in needsReview.
"""

from pydantic import AwareDatetime

from app.findings import Finding, ReviewOverride
from app.settlement import Adjustment, compute_adjustment
from app.terms import AgreementTerms
from app.workflow import Actor, NotPermitted, PreconditionFailed, Status, transition


def review_finding(
    current: Status, finding: Finding, decision: ReviewOverride, actor: Actor, at: AwareDatetime
) -> Finding:
    """Return `finding` with the Reviewer's decision recorded. Only allowed while Disputed."""
    if actor is not Actor.REVIEWER:
        raise NotPermitted(f"{actor} cannot review findings")
    if current is not Status.DISPUTED:
        raise PreconditionFailed(f"Findings can only be reviewed while Disputed, not {current}")
    return Finding.model_validate(
        finding.model_dump(by_alias=False) | {"review_override": decision, "reviewed_by": actor, "reviewed_at": at}
    )


def resolve(
    current: Status, terms: AgreementTerms, findings: tuple[Finding, ...] | list[Finding], actor: Actor
) -> tuple[Status, Adjustment]:
    """Recompute the adjustment from the reviewed findings and move Disputed -> Resolved."""
    adjustment = compute_adjustment(terms, findings)
    status = transition(current, Status.RESOLVED, actor, pending_review=len(adjustment.needs_review))
    return status, adjustment
