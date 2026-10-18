"""AgreementTerms: the rules DSL both parties approve before shipment.

The settlement engine computes adjustments only from these terms and validated findings;
AI output never sets an amount.
"""

from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, field_validator, model_validator

from app.money import PositiveMoney
from app.schemas import CamelModel

DefectType = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$", max_length=64)]


class EvidenceRequirements(CamelModel):
    min_dispatch_photos: int = Field(ge=1)
    min_receipt_photos: int = Field(ge=1)
    # Hours after receipt within which the buyer must submit the inspection.
    inspection_window_hours: int = Field(gt=0)


class Acceptance(CamelModel):
    # Only findings of these types can count as defects.
    defect_types: tuple[DefectType, ...] = Field(min_length=1)
    # A finding is confirmed at or above this AI confidence (or by human review).
    # A probability, not money, so float is fine here.
    min_confidence: float = Field(gt=0, le=1)
    # Confirmed defective units the buyer accepts without credit.
    defect_tolerance_units: int = Field(ge=0)

    @field_validator("defect_types")
    @classmethod
    def _unique(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(v)) != len(v):
            raise ValueError("defect types must be unique")
        return v


class PerDefectiveUnit(CamelModel):
    type: Literal["per_defective_unit"]
    amount_per_unit: PositiveMoney
    max_credit: PositiveMoney


# Add new rule types as Annotated[PerDefectiveUnit | Other, Field(discriminator="type")].
Compensation = PerDefectiveUnit


class AgreementTerms(CamelModel):
    item_description: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
    quantity: int = Field(gt=0)
    unit_price: PositiveMoney
    invoice_amount: PositiveMoney
    evidence_requirements: EvidenceRequirements
    acceptance: Acceptance
    compensation: Compensation

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.invoice_amount != self.quantity * self.unit_price:
            raise ValueError("invoice amount must equal quantity × unit price")
        if self.compensation.max_credit > self.invoice_amount:
            raise ValueError("max credit cannot exceed the invoice amount")
        if self.acceptance.defect_tolerance_units > self.quantity:
            raise ValueError("defect tolerance cannot exceed quantity")
        return self
