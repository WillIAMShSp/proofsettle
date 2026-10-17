"""Demo data mirroring the frontend's mock store (src/lib/store.tsx)."""

from decimal import Decimal

from app.findings import Finding
from app.terms import Acceptance, AgreementTerms, EvidenceRequirements, PerDefectiveUnit

# PS-1042: 100 metal components, $10,000, $100 credit per confirmed defective component.
PS_1042_TERMS = AgreementTerms(
    item_description="Machined metal component",
    quantity=100,
    unit_price=Decimal(100),
    invoice_amount=Decimal(10000),
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
        amount_per_unit=Decimal(100),
        max_credit=Decimal(10000),
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

# PS-1038: 40 hydraulic valves, $6,400, in transit (dispatch photos only, no inspection yet).
PS_1038_TERMS = AgreementTerms(
    item_description="Hydraulic ball valve",
    quantity=40,
    unit_price=Decimal(160),
    invoice_amount=Decimal(6400),
    evidence_requirements=EvidenceRequirements(
        min_dispatch_photos=4,
        min_receipt_photos=4,
        inspection_window_hours=24,
    ),
    acceptance=Acceptance(
        defect_types=("leak", "thread_damage", "corrosion"),
        min_confidence=0.9,
        defect_tolerance_units=0,
    ),
    compensation=PerDefectiveUnit(
        type="per_defective_unit",
        amount_per_unit=Decimal(160),
        max_credit=Decimal(1600),
    ),
)

# PS-1031: 250 steel brackets, $3,750, one tolerated defect. Proposed at (3 − 1) × $15 = $30,
# disputed by the Supplier over #101, and resolved after review at (2 − 1) × $15 = $15.
PS_1031_TERMS = AgreementTerms(
    item_description="Steel mounting bracket",
    quantity=250,
    unit_price=Decimal(15),
    invoice_amount=Decimal(3750),
    evidence_requirements=EvidenceRequirements(
        min_dispatch_photos=4,
        min_receipt_photos=4,
        inspection_window_hours=72,
    ),
    acceptance=Acceptance(
        defect_types=("bend", "crack", "corrosion"),
        min_confidence=0.85,
        defect_tolerance_units=1,
    ),
    compensation=PerDefectiveUnit(
        type="per_defective_unit",
        amount_per_unit=Decimal(15),
        max_credit=Decimal(750),
    ),
)

# As the AI reported them, before review. Receipt photos are ev_17..ev_20.
PS_1031_FINDINGS = (
    Finding(
        id="fnd_05",
        unit_ref="Bracket #012",
        defect_type="corrosion",
        confidence=0.93,
        evidence_ids=("ev_17",),
        description="Surface corrosion on mounting face",
        present_in_dispatch=False,
    ),
    Finding(
        id="fnd_06",
        unit_ref="Bracket #044",
        defect_type="bend",
        confidence=0.9,
        evidence_ids=("ev_18",),
        description="Bent mounting tab",
        present_in_dispatch=False,
    ),
    Finding(
        id="fnd_07",
        unit_ref="Bracket #101",
        defect_type="crack",
        confidence=0.89,
        evidence_ids=("ev_19",),
        description="Hairline crack along weld",
        present_in_dispatch=False,
    ),
    Finding(
        id="fnd_08",
        unit_ref="Bracket #187",
        defect_type="bend",
        confidence=0.61,
        evidence_ids=("ev_20",),
        description="Possible slight bend",
        present_in_dispatch=False,
    ),
    Finding(
        id="fnd_09",
        unit_ref="Bracket #203",
        defect_type="corrosion",
        confidence=0.95,
        evidence_ids=("ev_20",),
        description="Corrosion spot",
        present_in_dispatch=True,
    ),
)
