"""Deterministic settlement engine: agreement terms + findings -> proposed adjustment.

compute_adjustment is pure: no I/O, no AI calls, no clock, and Decimal for all money.
Given the same terms and findings it always returns the same Adjustment.

Each finding lands in exactly one of three lists, checked in this order:

1. reviewOverride "rejected"            -> excluded (a rejection always wins)
2. reviewOverride "confirmed"           -> counted
3. defect type not in the agreement     -> excluded
4. already present in dispatch photos   -> excluded
5. confidence below minConfidence       -> needsReview (never counted)
6. otherwise                            -> counted

Rules 3 and 4 come before 5 so that needsReview holds only findings the rules would count
if a Reviewer confirmed them, which is what amountIfReviewedConfirmed assumes. A Reviewer
can still confirm an excluded finding; rule 2 then counts it.

Credit is per defective unit, so several counted findings on one unit count once.

Needs-review findings do not block Inspection -> Proposed. The engine proposes the amount
from confirmed findings only, which is the lowest credit the evidence supports, and shows
the pending findings and amountIfReviewedConfirmed next to it. status is "needs_review"
so the UI can flag the uncertainty, but the move to Proposed is still allowed.
"""

from decimal import Decimal
from typing import Literal

from app.findings import Finding
from app.money import Money
from app.schemas import CamelModel
from app.terms import AgreementTerms

Reason = Literal[
    # counted
    "review_confirmed",
    "meets_threshold",
    # excluded
    "review_rejected",
    "defect_type_not_covered",
    "present_in_dispatch",
    # needsReview
    "below_confidence",
]


class FindingOutcome(CamelModel):
    finding_id: str
    unit_ref: str
    reason: Reason
    detail: str


class AppliedRule(CamelModel):
    credit: str  # e.g. "3 × $100 = $300"
    settlement: str  # e.g. "$10,000 − $300 = $9,700"


class Adjustment(CamelModel):
    confirmed_defects: int
    credit: Money
    settlement_amount: Money
    applied_rule: AppliedRule
    counted: tuple[FindingOutcome, ...]
    excluded: tuple[FindingOutcome, ...]
    needs_review: tuple[FindingOutcome, ...]
    # The credit if every needs-review finding were confirmed; equals credit when none are.
    amount_if_reviewed_confirmed: Money
    assumptions: tuple[str, ...]
    status: Literal["ready", "needs_review"]


def compute_adjustment(terms: AgreementTerms, findings: tuple[Finding, ...] | list[Finding]) -> Adjustment:
    ids = [f.id for f in findings]
    if len(set(ids)) != len(ids):
        raise ValueError("finding ids must be unique")

    acceptance = terms.acceptance
    threshold = _pct(acceptance.min_confidence)
    counted: list[FindingOutcome] = []
    excluded: list[FindingOutcome] = []
    needs_review: list[FindingOutcome] = []

    for f in findings:
        if f.review_override == "rejected":
            excluded.append(_outcome(f, "review_rejected", "Rejected by Reviewer"))
        elif f.review_override == "confirmed":
            counted.append(_outcome(f, "review_confirmed", "Confirmed by Reviewer"))
        elif f.defect_type not in acceptance.defect_types:
            excluded.append(_outcome(f, "defect_type_not_covered", f"{f.defect_type} is not a covered defect type"))
        elif f.present_in_dispatch:
            excluded.append(_outcome(f, "present_in_dispatch", "Already visible in dispatch photos"))
        elif f.confidence < acceptance.min_confidence:
            detail = f"{_pct(f.confidence)} confidence is below the {threshold} threshold"
            needs_review.append(_outcome(f, "below_confidence", detail))
        else:
            counted.append(_outcome(f, "meets_threshold", f"{_pct(f.confidence)} confidence, at or above {threshold}"))

    confirmed_units = {o.unit_ref for o in counted}
    credit, credit_rule = _credit(terms, len(confirmed_units))
    if_confirmed, _ = _credit(terms, len(confirmed_units | {o.unit_ref for o in needs_review}))
    settlement = terms.invoice_amount - credit

    return Adjustment(
        confirmed_defects=len(confirmed_units),
        credit=credit,
        settlement_amount=settlement,
        applied_rule=AppliedRule(
            credit=credit_rule,
            settlement=f"{usd(terms.invoice_amount)} − {usd(credit)} = {usd(settlement)}",
        ),
        counted=tuple(counted),
        excluded=tuple(excluded),
        needs_review=tuple(needs_review),
        amount_if_reviewed_confirmed=if_confirmed,
        assumptions=_assumptions(terms),
        status="needs_review" if needs_review else "ready",
    )


def _outcome(f: Finding, reason: Reason, detail: str) -> FindingOutcome:
    return FindingOutcome(finding_id=f.id, unit_ref=f.unit_ref, reason=reason, detail=detail)


def _credit(terms: AgreementTerms, confirmed: int) -> tuple[Decimal, str]:
    """min(max(0, confirmed − tolerance) × amountPerUnit, maxCredit), and the rule as text."""
    tolerance = terms.acceptance.defect_tolerance_units
    per_unit = terms.compensation.amount_per_unit
    cap = terms.compensation.max_credit
    raw = max(0, confirmed - tolerance) * per_unit

    if tolerance == 0:
        text = f"{confirmed} × {usd(per_unit)} = {usd(raw)}"
    elif confirmed > tolerance:
        text = f"({confirmed} − {tolerance} tolerated) × {usd(per_unit)} = {usd(raw)}"
    else:
        text = f"{confirmed} confirmed, {tolerance} tolerated = {usd(raw)}"
    if raw > cap:
        text += f", capped at {usd(cap)}"
    return min(raw, cap), text


def _assumptions(terms: AgreementTerms) -> tuple[str, ...]:
    acceptance = terms.acceptance
    tolerance = acceptance.defect_tolerance_units
    return (
        f"Only findings at ≥ {_pct(acceptance.min_confidence)} confidence count as confirmed, unless a Reviewer decides",
        f"Covered defect types: {', '.join(acceptance.defect_types)}",
        "Defects already visible in dispatch photos are excluded",
        f"First {tolerance} defective unit{'s' if tolerance != 1 else ''} accepted without credit"
        if tolerance
        else "No defect tolerance: every confirmed defective unit is credited",
        (
            f"Credit rule taken unchanged from the signed agreement: {usd(terms.compensation.amount_per_unit)} "
            f"per defective unit, capped at {usd(terms.compensation.max_credit)}"
        ),
    )


def usd(amount: Decimal) -> str:
    # "$9,700" for whole dollars, "$99.99" otherwise.
    if amount == amount.to_integral_value():
        return f"${int(amount):,}"
    return f"${amount.quantize(Decimal('0.01')):,}"


def _pct(p: float) -> str:
    # 0.85 -> "85%", 0.875 -> "87.5%"; via repr so the float's shortest form is used.
    return f"{(Decimal(repr(p)) * 100).normalize():f}%"
