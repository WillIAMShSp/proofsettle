"""Money: Decimal everywhere inside the backend, a plain number in JSON.

Values are dollars with at most 2 decimal places and 12 significant digits, matching the
NUMERIC(12,2) column. Twelve digits fit well inside a double's 15, so the conversions at
the JSON boundary below are exact; nothing else should ever turn money into a float.
"""

from decimal import Decimal
from typing import Annotated

from pydantic import BeforeValidator, Field, PlainSerializer, ValidationInfo
from sqlalchemy import Numeric

MONEY_SQL = Numeric(12, 2, asdecimal=True)


def _reject_python_float(value: object, info: ValidationInfo) -> object:
    # JSON numbers arrive as floats in "json" mode and are fine; a float passed from
    # Python code means someone did money math in floats.
    if isinstance(value, float) and info.mode == "python":
        raise ValueError("money must be a Decimal, int or str, not a float")
    return value


def _to_json_number(value: Decimal) -> int | float:
    return int(value) if value == value.to_integral_value() else float(value)


Money = Annotated[
    Decimal,
    BeforeValidator(_reject_python_float),
    Field(max_digits=12, decimal_places=2),
    PlainSerializer(_to_json_number, return_type=int | float, when_used="json"),
]
PositiveMoney = Annotated[Money, Field(gt=0)]
