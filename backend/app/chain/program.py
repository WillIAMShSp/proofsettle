"""The ProofSettle program as the backend sees it: keys, addresses, accounts, transactions.

The backend signs for all four on-chain roles with server-held demo keys (CHAIN_ALIGNMENT.md
§5, "Demo / MVP: custodial"): the Buyer and Supplier keys stand in for the parties' wallets,
the authority key is the rules engine, and the reviewer key is the human Reviewer. Those
signatures therefore show what the backend recorded, not each party's own consent.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from solders.instruction import Instruction
from solders.keypair import Keypair
from solders.message import Message
from solders.pubkey import Pubkey
from solders.transaction import Transaction

from app.chain.codec import Idl, load_idl
from app.chain.rpc import SolanaRpc
from app.config import Settings
from app.workflow import Status

SHIPMENT_SEED = b"shipment"
EVIDENCE_SEED = b"evidence"

# On-chain ShipmentStatus variant -> our Status (same order; only "In Transit" is spelled differently).
CHAIN_STATUS: dict[str, Status] = {
    "Draft": Status.DRAFT,
    "Agreed": Status.AGREED,
    "InTransit": Status.IN_TRANSIT,
    "Inspection": Status.INSPECTION,
    "Proposed": Status.PROPOSED,
    "Accepted": Status.ACCEPTED,
    "Disputed": Status.DISPUTED,
    "Resolved": Status.RESOLVED,
}

# Instructions per transaction. A record_evidence instruction adds ~110 bytes (a new
# account key, its data and indexes); 8 of them plus a mark_in_transit stay well inside the
# 1,232-byte packet and the default compute budget.
MAX_OPS_PER_TX = 8


class Signer(StrEnum):
    BUYER = "buyer"
    SUPPLIER = "supplier"
    AUTHORITY = "authority"
    REVIEWER = "reviewer"


@dataclass(frozen=True)
class Op:
    """One program instruction that bumps the shipment's audit_seq by exactly one."""

    ix: str
    signer: Signer
    args: dict[str, Any]
    # record_evidence: the PDA index is the on-chain evidence_count when it is sent.
    evidence: bool = False


def load_keypair(value: str) -> Keypair:
    """A keypair from its JSON array, or from a file holding that array."""
    text = value.strip()
    if not text.startswith("["):
        text = Path(text).expanduser().read_text(encoding="utf-8").strip()
    return Keypair.from_json(text)


class Chain:
    def __init__(
        self,
        rpc: SolanaRpc,
        keys: dict[Signer, Keypair],
        *,
        idl: Idl | None = None,
        program_id: Pubkey | None = None,
        shipment_salt: str = "",
        explorer_cluster: str = "devnet",
    ) -> None:
        if set(keys) != set(Signer):
            raise ValueError("keys for buyer, supplier, authority and reviewer are all required")
        if len({k.pubkey() for k in keys.values()}) != len(keys):
            raise ValueError("the four Solana keypairs must be distinct")
        self.rpc = rpc
        self.keys = keys
        self.idl = idl or load_idl()
        self.program_id = program_id or self.idl.address
        self.shipment_salt = shipment_salt
        self.explorer_cluster = explorer_cluster

    @classmethod
    def from_settings(cls, settings: Settings) -> "Chain | None":
        if not settings.solana_enabled:
            return None
        keys = {
            Signer.BUYER: load_keypair(settings.solana_buyer_keypair),
            Signer.SUPPLIER: load_keypair(settings.solana_supplier_keypair),
            Signer.AUTHORITY: load_keypair(settings.solana_authority_keypair),
            Signer.REVIEWER: load_keypair(settings.solana_reviewer_keypair),
        }
        program_id = Pubkey.from_string(settings.solana_program_id) if settings.solana_program_id else None
        return cls(
            SolanaRpc(settings.solana_rpc_url),
            keys,
            program_id=program_id,
            shipment_salt=settings.solana_shipment_salt,
            explorer_cluster=settings.solana_explorer_cluster,
        )

    def pubkey(self, signer: Signer) -> Pubkey:
        return self.keys[signer].pubkey()

    # --- addresses -------------------------------------------------------------------------

    def seed(self, chain_uuid: uuid.UUID) -> bytes:
        """The 16-byte shipment_id seed: the shipment's chain_uuid, salted if configured."""
        return (uuid.uuid5(chain_uuid, self.shipment_salt) if self.shipment_salt else chain_uuid).bytes

    def shipment_pda(self, seed: bytes) -> Pubkey:
        return Pubkey.find_program_address([SHIPMENT_SEED, seed], self.program_id)[0]

    def evidence_pda(self, shipment: Pubkey, index: int) -> Pubkey:
        return Pubkey.find_program_address(
            [EVIDENCE_SEED, bytes(shipment), index.to_bytes(2, "little")], self.program_id
        )[0]

    # --- reads -----------------------------------------------------------------------------

    def fetch_shipment(self, pda: Pubkey) -> dict[str, Any] | None:
        data = self.rpc.get_account_data(pda)
        return None if data is None else self.idl.decode_account("Shipment", data)

    def fetch_evidence(self, pda: Pubkey, count: int) -> list[dict[str, Any] | None]:
        addresses = [self.evidence_pda(pda, i) for i in range(count)]
        raw = self.rpc.get_multiple_account_data(addresses)
        return [None if d is None else self.idl.decode_account("Evidence", d) for d in raw]

    def signatures_by_seq(self, pda: Pubkey) -> dict[int, str]:
        """audit_seq -> the signature of the transaction that produced it, from the chain."""
        found: dict[int, str] = {}
        before = None
        while True:
            page = self.rpc.get_signatures_for_address(pda, before=before)
            for entry in page:
                if entry.get("err") is not None:
                    continue
                logs = self.rpc.get_transaction_logs(entry["signature"])
                for _, data in self.idl.events_in_logs(logs or (), self.program_id):
                    if data.get("shipment") == pda and "seq" in data:
                        found.setdefault(int(data["seq"]), entry["signature"])
            if len(page) < 1000:
                return found
            before = page[-1]["signature"]

    # --- writes ----------------------------------------------------------------------------

    def send(self, ops: Sequence[Op], pda: Pubkey, seed: bytes, evidence_count: int) -> str:
        """Send `ops` as one transaction, in order, and return its confirmed signature.

        `evidence_count` is the shipment's on-chain evidence_count before the first op;
        each record_evidence takes the next index, as the program does.
        """
        if not ops or len(ops) > MAX_OPS_PER_TX:
            raise ValueError(f"expected 1 to {MAX_OPS_PER_TX} ops, got {len(ops)}")
        ixs = []
        index = evidence_count
        for op in ops:
            ixs.append(self._instruction(op, pda, seed, index))
            if op.evidence:
                index += 1
        signers: list[Keypair] = []
        for op in ops:
            kp = self.keys[op.signer]
            if kp not in signers:
                signers.append(kp)
        blockhash = self.rpc.get_latest_blockhash()
        message = Message.new_with_blockhash(ixs, signers[0].pubkey(), blockhash.hash)
        tx = Transaction(signers, message, blockhash.hash)
        return self.rpc.send_and_confirm(tx, blockhash)

    def _instruction(self, op: Op, pda: Pubkey, seed: bytes, evidence_index: int) -> Instruction:
        signer = self.pubkey(op.signer)
        accounts: dict[str, Pubkey] = {"shipment": pda}
        args = dict(op.args)
        match op.ix:
            case "create_shipment":
                accounts["buyer"] = signer
                args["shipment_id"] = seed
            case "approve_agreement" | "accept_adjustment" | "dispute_adjustment":
                accounts["party"] = signer
            case "record_evidence":
                accounts["evidence"] = self.evidence_pda(pda, evidence_index)
                accounts["uploader"] = signer
            case "mark_in_transit":
                accounts["supplier"] = signer
            case "propose_adjustment":
                accounts["authority"] = signer
            case "resolve_dispute":
                accounts["reviewer"] = signer
            case _:
                raise ValueError(f"no account mapping for {op.ix}")
        return self.idl.instruction(op.ix, accounts, args, self.program_id)
