"""Inspection providers: something that looks at the evidence photos and reports findings.

A provider returns its raw output as JSON text, the way a vision model would. The backend
never trusts that text: parse_report validates it against InspectionReport, which has no
id, review, amount or status fields (unknown keys are rejected), and checks that every
evidenceId is a photo the provider was actually given. Only then do the findings become
app.findings.Finding rows, and the amount still comes from app.settlement alone.

MockProvider is the only provider for now. A real one implements the same protocol:
take an InspectionRequest (terms plus the photo bytes) and return the report JSON.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Protocol

from pydantic import Field, StringConstraints, ValidationError

from app.findings import Finding, Id
from app.schemas import CamelModel
from app.terms import AgreementTerms, DefectType

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mock_inspection.json"


@dataclass(frozen=True)
class Photo:
    id: str
    kind: str  # "dispatch" | "receipt"
    content_type: str
    sha256: str
    data: bytes


@dataclass(frozen=True)
class InspectionRequest:
    shipment_id: str
    terms: AgreementTerms
    dispatch: tuple[Photo, ...]
    receipt: tuple[Photo, ...]


class ProviderFinding(CamelModel):
    """One finding as a provider reports it. The backend assigns the id."""

    unit_ref: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    defect_type: DefectType
    confidence: float = Field(ge=0, le=1)
    evidence_ids: tuple[Id, ...] = Field(min_length=1)
    description: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
    present_in_dispatch: bool


class InspectionReport(CamelModel):
    findings: tuple[ProviderFinding, ...] = Field(max_length=500)


class InspectionFailed(Exception):
    """The provider failed or returned output that doesn't validate. Nothing is stored."""


class InspectionProvider(Protocol):
    name: str

    def inspect(self, request: InspectionRequest) -> str:
        """Return an InspectionReport as JSON text."""
        ...


class MockProvider:
    """Deterministic findings from a fixture, mapped onto the request's receipt photos.

    Each fixture finding names a receipt photo by position (`receiptPhoto`, wrapping
    around), so the same fixture works for any shipment.
    """

    name = "mock"

    def __init__(self, fixture: Path = FIXTURE) -> None:
        self.fixture = fixture

    def inspect(self, request: InspectionRequest) -> str:
        if not request.receipt:
            raise InspectionFailed("No receipt photos to inspect")
        findings = []
        for f in json.loads(self.fixture.read_text(encoding="utf-8"))["findings"]:
            photo = request.receipt[f.pop("receiptPhoto") % len(request.receipt)]
            findings.append(f | {"evidenceIds": [photo.id]})
        return json.dumps({"findings": findings})


def parse_report(raw: str, request: InspectionRequest) -> InspectionReport:
    """Validate a provider's raw output against the schema and the photos it was given."""
    try:
        report = InspectionReport.model_validate_json(raw)
    except ValidationError as e:
        raise InspectionFailed(f"Inspection output failed validation: {e.error_count()} error(s)") from e
    known = {p.id for p in request.dispatch + request.receipt}
    for f in report.findings:
        unknown = set(f.evidence_ids) - known
        if unknown:
            raise InspectionFailed(f"Inspection output cites unknown evidence {', '.join(sorted(unknown))}")
    return report


def to_finding(id: str, f: ProviderFinding) -> Finding:
    return Finding(id=id, **f.model_dump(by_alias=False))
