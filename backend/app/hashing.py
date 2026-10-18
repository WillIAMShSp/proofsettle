"""Canonical JSON and SHA-256, byte-for-byte what the Solana program expects.

The definition is the one in CHAIN_ALIGNMENT.md section 4:

    canonical_json(x) = json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                        .encode("utf-8")

applied to a Pydantic model's model_dump(mode="json", by_alias=True). Money therefore goes
through Money's serializer (10000, 99.99), never through str(Decimal). A raw Decimal, NaN or
other non-JSON value raises instead of being hashed in some ad-hoc form.

A hash is 32 raw bytes on-chain ([u8; 32]) and 64 lowercase hex characters in JSON and the
database; to_chain_bytes / from_chain_bytes convert at that boundary.
"""

import hashlib
import json
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel

# Fixed forever: changing it changes every shipment's on-chain address.
SHIPMENT_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "urn:proofsettle:shipment")


def jsonable(value: Any) -> Any:
    """Models (also inside lists and dicts) become their camelCase JSON-mode dump."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", by_alias=True)
    if isinstance(value, Mapping):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return [jsonable(v) for v in value]
    return value


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        jsonable(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_json(value: Any) -> str:
    """sha256(canonical_json(value)) as hex, e.g. termsHash = hash_json(terms)."""
    return sha256_hex(canonical_json(value))


def to_chain_bytes(hex_hash: str) -> bytes:
    raw = bytes.fromhex(hex_hash)
    if len(raw) != 32 or hex_hash != hex_hash.lower():
        raise ValueError("expected 64 lowercase hex characters")
    return raw


def from_chain_bytes(raw: bytes | Sequence[int]) -> str:
    raw = bytes(raw)
    if len(raw) != 32:
        raise ValueError("expected 32 bytes")
    return raw.hex()


def shipment_uuid(shipment_id: str) -> uuid.UUID:
    """Stable 16-byte id for the chain's shipment PDA seed, e.g. "PS-1042" -> uuid5."""
    return uuid.uuid5(SHIPMENT_NAMESPACE, shipment_id)
