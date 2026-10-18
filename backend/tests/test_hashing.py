import hashlib
import uuid
from decimal import Decimal

import pytest

from app.hashing import canonical_json, from_chain_bytes, hash_json, shipment_uuid, to_chain_bytes
from app.seed import PS_1042_TERMS


def test_canonical_json_is_sorted_compact_utf8():
    assert canonical_json({"b": 1, "a": [True, None, "é"]}) == '{"a":[true,null,"é"],"b":1}'.encode()


def test_terms_canonical_form():
    # Written out by hand: camelCase keys sorted at every level, money as plain JSON numbers.
    expected = (
        '{"acceptance":{"defectToleranceUnits":0,"defectTypes":["bend","crack","deep_scratch","discoloration"],'
        '"minConfidence":0.85},"compensation":{"amountPerUnit":100,"maxCredit":10000,"type":"per_defective_unit"},'
        '"evidenceRequirements":{"inspectionWindowHours":48,"minDispatchPhotos":4,"minReceiptPhotos":4},'
        '"invoiceAmount":10000,"itemDescription":"Machined metal component","quantity":100,"unitPrice":100}'
    )
    assert canonical_json(PS_1042_TERMS) == expected.encode()
    assert hash_json(PS_1042_TERMS) == hashlib.sha256(expected.encode()).hexdigest()


def test_cents_are_exact_numbers():
    terms = PS_1042_TERMS.model_copy(update={"unit_price": Decimal("33.33")})
    assert b'"unitPrice":33.33' in canonical_json(terms)


@pytest.mark.parametrize("value", [Decimal("1.5"), float("nan"), b"bytes"])
def test_rejects_values_that_have_no_canonical_json(value):
    with pytest.raises((TypeError, ValueError)):
        canonical_json({"x": value})


def test_chain_bytes_round_trip():
    h = hash_json({"a": 1})
    raw = to_chain_bytes(h)
    assert len(raw) == 32
    assert raw == hashlib.sha256(b'{"a":1}').digest()
    assert from_chain_bytes(list(raw)) == h


@pytest.mark.parametrize("bad", ["ab" * 31, "AB" * 32, "zz" * 32])
def test_chain_bytes_rejects_non_sha256_hex(bad):
    with pytest.raises(ValueError):
        to_chain_bytes(bad)


def test_shipment_uuid_is_stable():
    # Pinned: it is the on-chain PDA seed, so it must never change for an existing shipment.
    assert shipment_uuid("PS-1042") == uuid.UUID("867aec08-fe1b-5d73-8f38-b2fb1e862ae8")
    assert shipment_uuid("PS-1042").version == 5
    assert len(shipment_uuid("PS-1042").bytes) == 16
    assert shipment_uuid("PS-1038") != shipment_uuid("PS-1042")
