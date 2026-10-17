import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.findings import Finding
from app.seed import PS_1042_FINDINGS, PS_1042_TERMS
from app.settlement import compute_adjustment
from app.terms import AgreementTerms

D = Decimal
REVIEWED_AT = datetime(2026, 10, 16, 9, 0, tzinfo=UTC)


def terms(**changes) -> AgreementTerms:
    """PS-1042 terms with dotted-path overrides, re-validated through JSON."""
    d = PS_1042_TERMS.model_dump(mode="json")
    for path, value in changes.items():
        *parents, leaf = path.split("__")
        node = d
        for p in parents:
            node = node[p]
        node[leaf] = value
    return AgreementTerms.model_validate_json(json.dumps(d))


def finding(id: str, confidence: float = 0.9, defect_type: str = "crack", **extra) -> Finding:
    return Finding(
        id=id,
        unit_ref=extra.pop("unit_ref", f"Component #{id[-3:]}"),
        defect_type=defect_type,
        confidence=confidence,
        evidence_ids=("ev_05",),
        description="test finding",
        present_in_dispatch=extra.pop("present_in_dispatch", False),
        **extra,
    )


def reviewed(f: Finding, override: str) -> Finding:
    return Finding.model_validate(
        f.model_dump(by_alias=False)
        | {"review_override": override, "reviewed_by": "Reviewer", "reviewed_at": REVIEWED_AT}
    )


def seed_with(**overrides: str) -> list[Finding]:
    """PS-1042 findings with review overrides by finding id."""
    return [reviewed(f, overrides[f.id]) if f.id in overrides else f for f in PS_1042_FINDINGS]


TEN_AT_33_33 = terms(
    quantity=10,
    unitPrice=33.33,
    invoiceAmount=333.30,
    compensation__amountPerUnit=33.33,
    compensation__maxCredit=333.30,
)


@dataclass
class Case:
    terms: AgreementTerms
    findings: list[Finding]
    confirmed: int
    credit: str
    settlement: str
    rule: str
    counted: list[str] = field(default_factory=list)
    excluded: dict[str, str] = field(default_factory=dict)
    needs_review: list[str] = field(default_factory=list)
    if_confirmed: str | None = None  # defaults to credit

    @property
    def status(self) -> str:
        return "needs_review" if self.needs_review else "ready"


# fmt: off
CASES = {
    "PS-1042 as seeded": Case(
        PS_1042_TERMS, list(PS_1042_FINDINGS), 3, "300", "9700", "3 × $100 = $300",
        counted=["fnd_01", "fnd_02", "fnd_03"], needs_review=["fnd_04"], if_confirmed="400",
    ),
    "PS-1042, #063 confirmed by review": Case(
        PS_1042_TERMS, seed_with(fnd_04="confirmed"), 4, "400", "9600", "4 × $100 = $400",
        counted=["fnd_01", "fnd_02", "fnd_03", "fnd_04"],
    ),
    "PS-1042, #063 rejected by review": Case(
        PS_1042_TERMS, seed_with(fnd_04="rejected"), 3, "300", "9700", "3 × $100 = $300",
        counted=["fnd_01", "fnd_02", "fnd_03"], excluded={"fnd_04": "review_rejected"},
    ),
    "zero defects": Case(PS_1042_TERMS, [], 0, "0", "10000", "0 × $100 = $0"),
    "all below threshold": Case(
        PS_1042_TERMS, [finding("fnd_001", 0.5), finding("fnd_002", 0.849)], 0, "0", "10000", "0 × $100 = $0",
        needs_review=["fnd_001", "fnd_002"], if_confirmed="200",
    ),
    "exactly at threshold counts": Case(
        PS_1042_TERMS, [finding("fnd_001", 0.85)], 1, "100", "9900", "1 × $100 = $100", counted=["fnd_001"],
    ),
    "cap hit": Case(
        terms(compensation__maxCredit=250), [finding(f"fnd_00{i}") for i in range(1, 4)], 3, "250", "9750",
        "3 × $100 = $300, capped at $250", counted=["fnd_001", "fnd_002", "fnd_003"],
    ),
    "cap also limits the if-reviewed amount": Case(
        terms(compensation__maxCredit=250), [finding("fnd_001"), finding("fnd_002"), finding("fnd_003", 0.4)],
        2, "200", "9800", "2 × $100 = $200", counted=["fnd_001", "fnd_002"], needs_review=["fnd_003"],
        if_confirmed="250",
    ),
    "tolerance absorbs some defects": Case(
        terms(acceptance__defectToleranceUnits=1), list(PS_1042_FINDINGS), 3, "200", "9800",
        "(3 − 1 tolerated) × $100 = $200", counted=["fnd_01", "fnd_02", "fnd_03"], needs_review=["fnd_04"],
        if_confirmed="300",
    ),
    "tolerance absorbs all defects": Case(
        terms(acceptance__defectToleranceUnits=5), list(PS_1042_FINDINGS), 3, "0", "10000",
        "3 confirmed, 5 tolerated = $0", counted=["fnd_01", "fnd_02", "fnd_03"], needs_review=["fnd_04"],
        if_confirmed="0",
    ),
    "defect present at dispatch": Case(
        PS_1042_TERMS, [finding("fnd_001"), finding("fnd_002", present_in_dispatch=True)], 1, "100", "9900",
        "1 × $100 = $100", counted=["fnd_001"], excluded={"fnd_002": "present_in_dispatch"},
    ),
    "low-confidence defect present at dispatch is excluded, not reviewed": Case(
        PS_1042_TERMS, [finding("fnd_001", 0.3, present_in_dispatch=True)], 0, "0", "10000", "0 × $100 = $0",
        excluded={"fnd_001": "present_in_dispatch"},
    ),
    "wrong defect type": Case(
        PS_1042_TERMS, [finding("fnd_001"), finding("fnd_002", 0.99, defect_type="dent")], 1, "100", "9900",
        "1 × $100 = $100", counted=["fnd_001"], excluded={"fnd_002": "defect_type_not_covered"},
    ),
    "rejected override beats high confidence": Case(
        PS_1042_TERMS, [reviewed(finding("fnd_001", 0.99), "rejected")], 0, "0", "10000", "0 × $100 = $0",
        excluded={"fnd_001": "review_rejected"},
    ),
    "confirmed override counts a wrong type": Case(
        PS_1042_TERMS, [reviewed(finding("fnd_001", 0.2, defect_type="dent"), "confirmed")], 1, "100", "9900",
        "1 × $100 = $100", counted=["fnd_001"],
    ),
    "two findings on one unit count once": Case(
        PS_1042_TERMS, [finding("fnd_001", unit_ref="Component #017"), finding("fnd_002", unit_ref="Component #017")],
        1, "100", "9900", "1 × $100 = $100", counted=["fnd_001", "fnd_002"],
    ),
    "3 × $33.33 is exact": Case(
        TEN_AT_33_33, [finding(f"fnd_00{i}") for i in range(1, 4)], 3, "99.99", "233.31", "3 × $33.33 = $99.99",
        counted=["fnd_001", "fnd_002", "fnd_003"],
    ),
}
# fmt: on


@pytest.mark.parametrize("case", CASES.values(), ids=CASES.keys())
def test_compute_adjustment(case: Case):
    adj = compute_adjustment(case.terms, case.findings)

    assert adj.confirmed_defects == case.confirmed
    assert adj.credit == D(case.credit)
    assert adj.settlement_amount == D(case.settlement)
    assert adj.settlement_amount == case.terms.invoice_amount - adj.credit
    assert adj.applied_rule.credit == case.rule
    assert [o.finding_id for o in adj.counted] == case.counted
    assert {o.finding_id: o.reason for o in adj.excluded} == case.excluded
    assert [o.finding_id for o in adj.needs_review] == case.needs_review
    assert adj.amount_if_reviewed_confirmed == D(case.if_confirmed or case.credit)
    assert adj.status == case.status
    # Every finding lands in exactly one list.
    placed = [o.finding_id for o in (*adj.counted, *adj.excluded, *adj.needs_review)]
    assert sorted(placed) == sorted(f.id for f in case.findings)
    for v in (adj.credit, adj.settlement_amount, adj.amount_if_reviewed_confirmed):
        assert isinstance(v, Decimal)


def test_ps_1042_matches_frontend():
    adj = compute_adjustment(PS_1042_TERMS, PS_1042_FINDINGS)
    d = adj.model_dump(mode="json")
    assert d["credit"] == 300 and d["settlementAmount"] == 9700 and d["amountIfReviewedConfirmed"] == 400
    assert d["appliedRule"] == {"credit": "3 × $100 = $300", "settlement": "$10,000 − $300 = $9,700"}
    assert d["needsReview"] == [
        {
            "findingId": "fnd_04",
            "unitRef": "Component #063",
            "reason": "below_confidence",
            "detail": "52% confidence is below the 85% threshold",
        }
    ]
    assert d["status"] == "needs_review"
    assert d["assumptions"][0] == "Only findings at ≥ 85% confidence count as confirmed, unless a Reviewer decides"


def test_cents_in_rule_text():
    adj = compute_adjustment(TEN_AT_33_33, [finding("fnd_001"), finding("fnd_002"), finding("fnd_003")])
    assert adj.applied_rule.settlement == "$333.30 − $99.99 = $233.31"
    assert adj.model_dump(mode="json")["credit"] == 99.99


def test_seed_findings_match_frontend():
    shown = [(f.unit_ref, f.description, f.confidence) for f in PS_1042_FINDINGS]
    assert shown == [
        ("Component #017", "Bent flange", 0.94),
        ("Component #042", "Surface crack near bore", 0.91),
        ("Component #078", "Deep scratch on mating face", 0.88),
        ("Component #063", "Possible discoloration", 0.52),
    ]
    assert all(f.review_override is None and not f.present_in_dispatch for f in PS_1042_FINDINGS)


def test_is_deterministic():
    a = compute_adjustment(PS_1042_TERMS, PS_1042_FINDINGS)
    assert compute_adjustment(PS_1042_TERMS, PS_1042_FINDINGS) == a


def test_duplicate_finding_ids_rejected():
    with pytest.raises(ValueError, match="unique"):
        compute_adjustment(PS_1042_TERMS, [finding("fnd_001"), finding("fnd_001")])


INVALID_FINDINGS = {
    "confidence above 1": {"confidence": 1.01},
    "negative confidence": {"confidence": -0.1},
    "no evidence": {"evidence_ids": ()},
    "override without reviewer": {"review_override": "confirmed"},
    "reviewer without override": {"reviewed_by": "Reviewer", "reviewed_at": REVIEWED_AT},
    "reviewed by a party": {"review_override": "confirmed", "reviewed_by": "Buyer", "reviewed_at": REVIEWED_AT},
    "unknown override": {"review_override": "maybe", "reviewed_by": "Reviewer", "reviewed_at": REVIEWED_AT},
    "naive review time": {
        "review_override": "confirmed",
        "reviewed_by": "Reviewer",
        "reviewed_at": datetime(2026, 10, 16, 9, 0),
    },
    "defect type not a slug": {"defect_type": "Bent Flange"},
}


@pytest.mark.parametrize("changes", INVALID_FINDINGS.values(), ids=INVALID_FINDINGS.keys())
def test_invalid_findings_rejected(changes):
    with pytest.raises(ValidationError):
        Finding.model_validate(PS_1042_FINDINGS[0].model_dump(by_alias=False) | changes)
