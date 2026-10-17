"""Demo data mirroring the frontend's mock store (src/lib/store.tsx)."""

from decimal import Decimal

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
