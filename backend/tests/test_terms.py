import json
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.seed import PS_1042_TERMS
from app.terms import AgreementTerms


def seed_json() -> dict:
    return PS_1042_TERMS.model_dump(mode="json")


def parse(d: dict) -> AgreementTerms:
    # Go through JSON text, as an API request would.
    return AgreementTerms.model_validate_json(json.dumps(d))


def test_seed_reproduces_ps_1042_rule():
    t = PS_1042_TERMS
    assert t.quantity == 100
    assert t.invoice_amount == Decimal("10000")
    assert t.compensation.type == "per_defective_unit"
    assert t.compensation.amount_per_unit == Decimal("100")
    assert t.acceptance.min_confidence == 0.85
    assert t.acceptance.defect_tolerance_units == 0
    # The frontend's numbers: 3 confirmed defects -> $300, $400 if #063 is confirmed.
    assert 3 * t.compensation.amount_per_unit == Decimal("300")
    assert 4 * t.compensation.amount_per_unit == Decimal("400")


def test_money_is_decimal_internally():
    t = PS_1042_TERMS
    for v in (t.unit_price, t.invoice_amount, t.compensation.amount_per_unit, t.compensation.max_credit):
        assert isinstance(v, Decimal)


def test_json_uses_camel_case_and_numbers():
    d = seed_json()
    assert d["invoiceAmount"] == 10000 and not isinstance(d["invoiceAmount"], str)
    assert d["compensation"] == {"type": "per_defective_unit", "amountPerUnit": 100, "maxCredit": 10000}
    assert d["acceptance"]["minConfidence"] == 0.85


def test_json_round_trip():
    assert parse(seed_json()) == PS_1042_TERMS


def test_snake_case_input_accepted():
    assert AgreementTerms.model_validate(PS_1042_TERMS.model_dump(by_alias=False)) == PS_1042_TERMS


def test_decimal_math_is_exact():
    # 3 × 33.33 is 99.99000000000001 in floats; Decimal keeps it exact.
    d = seed_json() | {"quantity": 3, "unitPrice": 33.33, "invoiceAmount": 99.99}
    d["compensation"]["maxCredit"] = 99.99
    t = parse(d)
    assert t.invoice_amount == Decimal("99.99")
    assert t.model_dump(mode="json")["unitPrice"] == 33.33


def test_cents_serialize_as_number():
    d = seed_json() | {"quantity": 1, "unitPrice": 10.5, "invoiceAmount": 10.5}
    d["compensation"] |= {"amountPerUnit": 0.25, "maxCredit": 10.5}
    assert parse(d).model_dump(mode="json")["compensation"]["amountPerUnit"] == 0.25


def test_max_credit_equal_to_invoice_allowed():
    d = seed_json()
    d["compensation"]["maxCredit"] = d["invoiceAmount"]
    assert parse(d).compensation.max_credit == Decimal("10000")


def test_tolerance_equal_to_quantity_allowed():
    d = seed_json()
    d["acceptance"]["defectToleranceUnits"] = 100
    assert parse(d).acceptance.defect_tolerance_units == 100


def _set(d: dict, path: str, value) -> dict:
    *parents, leaf = path.split(".")
    node = d
    for p in parents:
        node = node[p]
    if value is DELETE:
        del node[leaf]
    else:
        node[leaf] = value
    return d


DELETE = object()

INVALID = {
    "invoice zero": ("invoiceAmount", 0),
    "invoice negative": ("invoiceAmount", -10000),
    "unit price zero": ("unitPrice", 0),
    "quantity zero": ("quantity", 0),
    "quantity fractional": ("quantity", 1.5),
    "invoice != qty × price": ("invoiceAmount", 9999),
    "too many decimals": ("compensation.amountPerUnit", 100.001),
    "too many digits": ("compensation.amountPerUnit", 12345678901234),
    "money as NaN": ("compensation.amountPerUnit", "NaN"),
    "blank description": ("itemDescription", "   "),
    "missing description": ("itemDescription", DELETE),
    "zero dispatch photos": ("evidenceRequirements.minDispatchPhotos", 0),
    "zero receipt photos": ("evidenceRequirements.minReceiptPhotos", 0),
    "zero inspection window": ("evidenceRequirements.inspectionWindowHours", 0),
    "no defect types": ("acceptance.defectTypes", []),
    "duplicate defect types": ("acceptance.defectTypes", ["crack", "crack"]),
    "defect type not a slug": ("acceptance.defectTypes", ["Bent Flange"]),
    "confidence zero": ("acceptance.minConfidence", 0),
    "confidence above 1": ("acceptance.minConfidence", 1.5),
    "negative tolerance": ("acceptance.defectToleranceUnits", -1),
    "tolerance > quantity": ("acceptance.defectToleranceUnits", 101),
    "unknown compensation type": ("compensation.type", "percentage"),
    "missing compensation type": ("compensation.type", DELETE),
    "amount per unit zero": ("compensation.amountPerUnit", 0),
    "max credit zero": ("compensation.maxCredit", 0),
    "max credit > invoice": ("compensation.maxCredit", 10000.01),
    "missing max credit": ("compensation.maxCredit", DELETE),
    "unknown top-level field": ("discount", 5),
    "unknown nested field": ("compensation.bonus", 5),
}


@pytest.mark.parametrize(("path", "value"), INVALID.values(), ids=INVALID.keys())
def test_invalid_terms_rejected(path, value):
    with pytest.raises(ValidationError) as exc:
        parse(_set(seed_json(), path, value))
    # Every error is on the field we broke (cross-field rules report at the model root),
    # so a case can't pass by tripping some other rule.
    for err in exc.value.errors():
        loc = ".".join(str(part) for part in err["loc"])
        assert loc == "" or loc.startswith(path), err


def test_python_float_money_rejected():
    d = PS_1042_TERMS.model_dump(by_alias=False)
    d["unit_price"] = 100.0
    with pytest.raises(ValidationError, match="not a float"):
        AgreementTerms.model_validate(d)


def test_terms_are_immutable():
    with pytest.raises(ValidationError):
        PS_1042_TERMS.quantity = 99
