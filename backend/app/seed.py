"""Demo data mirroring the frontend's mock store (src/lib/store.tsx)."""

from decimal import Decimal

from app.findings import Finding
from app.terms import Acceptance, AgreementTerms, EvidenceRequirements, PerDefectiveUnit

# PS-1042: 100 metal components, $10,000, $100 credit per confirmed defective component.
PS_1042_TERMS = AgreementTerms(
    item_description="Machined metal component",
    quantity=100,
    unit_price=Decimal("100"),
    invoice_amount=Decimal("10000"),
    evidence_requirements=EvidenceRequirements(
        min_dispatch_photos=4,
        min_receipt_photos=4,
        inspection_window_hours=48,
    ),
    acceptance=Acceptance(
        defect_types=("bend", "crack", "deep_scratch", "discoloration"),
        min_confidence=0.85,
        defect_tolerance_units=0,
    ),
    compensation=PerDefectiveUnit(
        type="per_defective_unit",
        amount_per_unit=Decimal("100"),
        max_credit=Decimal("10000"),
    ),
)

# PS-1042's inspection, as shipments.$id.tsx shows it. Receipt photos are ev_05..ev_08;
# the dispatch photos (ev_01..ev_04) show all 100 components intact.
PS_1042_FINDINGS = (
    Finding(
        id="fnd_01",
        unit_ref="Component #017",
        defect_type="bend",
        confidence=0.94,
        evidence_ids=("ev_05",),
        description="Bent flange",
        present_in_dispatch=False,
    ),
    Finding(
        id="fnd_02",
        unit_ref="Component #042",
        defect_type="crack",
        confidence=0.91,
        evidence_ids=("ev_06",),
        description="Surface crack near bore",
        present_in_dispatch=False,
    ),
    Finding(
        id="fnd_03",
        unit_ref="Component #078",
        defect_type="deep_scratch",
        confidence=0.88,
        evidence_ids=("ev_07",),
        description="Deep scratch on mating face",
        present_in_dispatch=False,
    ),
    Finding(
        id="fnd_04",
        unit_ref="Component #063",
        defect_type="discoloration",
        confidence=0.52,
        evidence_ids=("ev_08",),
        description="Possible discoloration",
        present_in_dispatch=False,
    ),
)
