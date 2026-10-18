"""Inspection findings: what the AI flagged on receipt photos, plus any human review.

A finding is evidence, not a verdict. Whether it counts toward the adjustment is decided
by app.settlement from the agreement terms and the review override, never by the AI.
"""

from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, StringConstraints, model_validator

from app.schemas import CamelModel
from app.terms import DefectType
from app.workflow import Actor

Id = Annotated[str, StringConstraints(pattern=r"^[a-z]+_[A-Za-z0-9]+$", max_length=64)]
ReviewOverride = Literal["confirmed", "rejected"]


class Finding(CamelModel):
    id: Id
    # The inspected unit, e.g. "Component #017". Credit is per unit, so two findings on
    # the same unit count once.
    unit_ref: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    defect_type: DefectType
    # AI confidence; a probability, not money, so float is fine here.
    confidence: float = Field(ge=0, le=1)
    evidence_ids: tuple[Id, ...] = Field(min_length=1)
    description: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
    # The defect is already visible in the supplier's dispatch photos.
    present_in_dispatch: bool
    review_override: ReviewOverride | None = None
    reviewed_by: Actor | None = None
    reviewed_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def _review_complete(self) -> Self:
        fields = (self.review_override, self.reviewed_by, self.reviewed_at)
        if any(f is None for f in fields) and any(f is not None for f in fields):
            raise ValueError("reviewOverride, reviewedBy and reviewedAt must be set together")
        if self.reviewed_by not in (None, Actor.REVIEWER):
            raise ValueError("only a Reviewer can review a finding")
        return self
