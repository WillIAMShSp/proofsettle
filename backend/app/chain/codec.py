"""Borsh encoding for the ProofSettle program, driven by the IDL that `anchor build` writes.

Instruction discriminators, account order and flags, and every struct's field layout come
from app/chain/proofsettle.json, so the backend can't drift from the program it talks to.
Only fixed-size types are supported (the program uses no Vec, String or Option); anything
else raises instead of being guessed at.

Values in Python: integers as int, bool as bool, pubkey as solders Pubkey, [u8; N] as bytes,
unit enums as the variant name ("Dispatch"), structs as dicts keyed by the IDL's snake_case
field names.
"""

import base64
import json
import struct
from collections.abc import Mapping, Sequence
from functools import cache
from pathlib import Path
from typing import Any

from solders.instruction import AccountMeta, Instruction
from solders.pubkey import Pubkey

IDL_PATH = Path(__file__).with_name("proofsettle.json")

_INTS = {"u8": "<B", "u16": "<H", "u32": "<I", "u64": "<Q", "i64": "<q"}


class CodecError(ValueError):
    pass


class Idl:
    def __init__(self, raw: Mapping[str, Any]) -> None:
        self.raw = raw
        self.address = Pubkey.from_string(raw["address"])
        self.types: dict[str, dict[str, Any]] = {t["name"]: t["type"] for t in raw["types"]}
        self.instructions: dict[str, dict[str, Any]] = {ix["name"]: ix for ix in raw["instructions"]}
        self.accounts: dict[str, bytes] = {a["name"]: bytes(a["discriminator"]) for a in raw["accounts"]}
        self.events: dict[bytes, str] = {bytes(e["discriminator"]): e["name"] for e in raw["events"]}
        self.errors: dict[int, str] = {e["code"]: e["name"] for e in raw.get("errors", ())}

    # --- types -----------------------------------------------------------------------------

    def encode(self, ty: Any, value: Any) -> bytes:
        if isinstance(ty, str):
            if ty in _INTS:
                return struct.pack(_INTS[ty], value)
            if ty == "bool":
                if not isinstance(value, bool):
                    raise CodecError(f"expected bool, got {value!r}")
                return b"\x01" if value else b"\x00"
            if ty == "pubkey":
                if not isinstance(value, Pubkey):
                    raise CodecError(f"expected Pubkey, got {value!r}")
                return bytes(value)
        elif "array" in ty:
            inner, n = ty["array"]
            if inner == "u8":
                raw = bytes(value)
                if len(raw) != n:
                    raise CodecError(f"expected {n} bytes, got {len(raw)}")
                return raw
            if len(value) != n:
                raise CodecError(f"expected {n} items, got {len(value)}")
            return b"".join(self.encode(inner, v) for v in value)
        elif "defined" in ty:
            name = ty["defined"]["name"]
            td = self.types[name]
            if td["kind"] == "struct":
                return b"".join(self.encode(f["type"], value[f["name"]]) for f in td["fields"])
            if td["kind"] == "enum":
                names = [v["name"] for v in td["variants"]]
                if any("fields" in v for v in td["variants"]):
                    raise CodecError(f"enum {name} has data variants")
                if value not in names:
                    raise CodecError(f"{value!r} is not a {name} variant")
                return struct.pack("<B", names.index(value))
        raise CodecError(f"unsupported IDL type {ty!r}")

    def decode(self, ty: Any, data: bytes, offset: int = 0) -> tuple[Any, int]:
        try:
            return self._decode(ty, data, offset)
        except (struct.error, IndexError) as e:
            raise CodecError(f"data too short for {ty!r}") from e

    def _decode(self, ty: Any, data: bytes, offset: int) -> tuple[Any, int]:
        if isinstance(ty, str):
            if ty in _INTS:
                fmt = _INTS[ty]
                return struct.unpack_from(fmt, data, offset)[0], offset + struct.calcsize(fmt)
            if ty == "bool":
                b = data[offset]
                if b not in (0, 1):
                    raise CodecError(f"invalid bool byte {b}")
                return b == 1, offset + 1
            if ty == "pubkey":
                if len(data) < offset + 32:
                    raise CodecError("data too short for pubkey")
                return Pubkey.from_bytes(data[offset : offset + 32]), offset + 32
        elif "array" in ty:
            inner, n = ty["array"]
            if inner == "u8":
                if len(data) < offset + n:
                    raise CodecError(f"data too short for [u8; {n}]")
                return bytes(data[offset : offset + n]), offset + n
            items = []
            for _ in range(n):
                item, offset = self._decode(inner, data, offset)
                items.append(item)
            return items, offset
        elif "defined" in ty:
            name = ty["defined"]["name"]
            td = self.types[name]
            if td["kind"] == "struct":
                out: dict[str, Any] = {}
                for f in td["fields"]:
                    out[f["name"]], offset = self._decode(f["type"], data, offset)
                return out, offset
            if td["kind"] == "enum":
                i = data[offset]
                variants = td["variants"]
                if i >= len(variants):
                    raise CodecError(f"invalid {name} variant index {i}")
                return variants[i]["name"], offset + 1
        raise CodecError(f"unsupported IDL type {ty!r}")

    # --- instructions, accounts, events ----------------------------------------------------

    def instruction(
        self, name: str, accounts: Mapping[str, Pubkey], args: Mapping[str, Any], program_id: Pubkey
    ) -> Instruction:
        """The instruction `name`, with accounts in the IDL's order and the IDL's flags.

        Every account must be given except those the IDL pins to a fixed address
        (the system program). Unknown or missing names raise.
        """
        ix = self.instructions[name]
        known = {a["name"] for a in ix["accounts"]}
        if extra := set(accounts) - known:
            raise CodecError(f"{name}: unknown accounts {sorted(extra)}")
        metas = []
        for a in ix["accounts"]:
            if "address" in a:
                key = Pubkey.from_string(a["address"])
            elif a["name"] in accounts:
                key = accounts[a["name"]]
            else:
                raise CodecError(f"{name}: missing account {a['name']}")
            metas.append(AccountMeta(key, is_signer=a.get("signer", False), is_writable=a.get("writable", False)))
        arg_names = [a["name"] for a in ix["args"]]
        if set(args) != set(arg_names):
            raise CodecError(f"{name}: expected args {arg_names}, got {sorted(args)}")
        data = bytes(ix["discriminator"]) + b"".join(self.encode(a["type"], args[a["name"]]) for a in ix["args"])
        return Instruction(program_id, data, metas)

    def decode_account(self, name: str, data: bytes) -> dict[str, Any]:
        disc = self.accounts[name]
        if data[:8] != disc:
            raise CodecError(f"not a {name} account")
        value, _ = self.decode({"defined": {"name": name}}, data, 8)
        return value

    def decode_event(self, data: bytes) -> tuple[str, dict[str, Any]] | None:
        name = self.events.get(bytes(data[:8]))
        if name is None:
            return None
        value, _ = self.decode({"defined": {"name": name}}, data, 8)
        return name, value

    def events_in_logs(self, logs: Sequence[str], program_id: Pubkey) -> list[tuple[str, dict[str, Any]]]:
        """Events emitted by `program_id` itself in a transaction's log messages.

        Tracks the invoke stack so "Program data:" lines from other programs are ignored.
        """
        pid = str(program_id)
        stack: list[str] = []
        out = []
        for line in logs:
            if line.startswith("Program ") and " invoke [" in line:
                stack.append(line.split(" ")[1])
            elif line.startswith("Program ") and (line.endswith(" success") or " failed" in line):
                if stack:
                    stack.pop()
            elif line.startswith("Program data: ") and stack and stack[-1] == pid:
                try:
                    decoded = self.decode_event(base64.b64decode(line[len("Program data: ") :]))
                except (CodecError, ValueError):
                    continue
                if decoded:
                    out.append(decoded)
        return out


@cache
def load_idl(path: Path = IDL_PATH) -> Idl:
    return Idl(json.loads(path.read_text(encoding="utf-8")))
