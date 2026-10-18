"""A small synchronous Solana JSON-RPC client over urllib (as app.auth calls Supabase).

Only the calls anchoring needs. Transactions are confirmed by polling getSignatureStatuses
until "confirmed", the blockhash expires, or a deadline passes; no websockets.
"""

import base64
import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from solders.hash import Hash
from solders.pubkey import Pubkey
from solders.transaction import Transaction

COMMITMENT = "confirmed"
# Public RPCs (api.devnet.solana.com) answer bursts with HTTP 429. The request was not
# processed, so it is safe to resend, sendTransaction included (same signed bytes).
RATE_LIMIT_RETRIES = 5
RATE_LIMIT_MAX_WAIT_S = 10.0


class RpcError(Exception):
    """The RPC node was unreachable or answered with an error."""


class TransactionFailed(RpcError):
    """The transaction was rejected (simulation or execution). `logs` has the program logs."""

    def __init__(self, message: str, logs: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.logs = logs

    @property
    def program_error(self) -> str | None:
        """The Anchor error name, e.g. "InvalidStatus", if the program logged one."""
        for line in self.logs:
            if m := re.search(r"Error Code: (\w+)", line):
                return m.group(1)
        return None


def _retry_after(error: urllib.error.HTTPError, attempt: int) -> float:
    """Seconds to wait before resending: the server's Retry-After, else 1, 2, 4, 8, ..."""
    header = error.headers.get("Retry-After") if error.headers else None
    try:
        wait = float(header) if header else 2.0**attempt
    except ValueError:
        wait = 2.0**attempt
    return min(max(wait, 0.0), RATE_LIMIT_MAX_WAIT_S)


@dataclass(frozen=True)
class Blockhash:
    hash: Hash
    last_valid_block_height: int


class SolanaRpc:
    def __init__(self, url: str, *, timeout: float = 15.0) -> None:
        self.url = url
        self.timeout = timeout
        self._id = 0

    def call(self, method: str, params: list[Any]) -> Any:
        self._id += 1
        body = json.dumps({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params}).encode()
        req = urllib.request.Request(self.url, data=body, headers={"Content-Type": "application/json"})
        for attempt in range(RATE_LIMIT_RETRIES + 1):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as e:
                if e.code != 429 or attempt == RATE_LIMIT_RETRIES:
                    raise RpcError(f"{method}: {e}") from e
                time.sleep(_retry_after(e, attempt))
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
                raise RpcError(f"{method}: {e}") from e
        if "error" in payload:
            err = payload["error"]
            logs = tuple((err.get("data") or {}).get("logs") or ())
            if method == "sendTransaction":
                raise TransactionFailed(f"{method}: {err.get('message')}", logs)
            raise RpcError(f"{method}: {err.get('message')}")
        return payload.get("result")

    # --- reads -----------------------------------------------------------------------------

    def get_account_data(self, pubkey: Pubkey) -> bytes | None:
        result = self.call("getAccountInfo", [str(pubkey), {"encoding": "base64", "commitment": COMMITMENT}])
        value = result["value"]
        return None if value is None else base64.b64decode(value["data"][0])

    def get_multiple_account_data(self, pubkeys: list[Pubkey]) -> list[bytes | None]:
        out: list[bytes | None] = []
        for i in range(0, len(pubkeys), 100):  # the RPC's per-call limit
            chunk = [str(p) for p in pubkeys[i : i + 100]]
            result = self.call("getMultipleAccounts", [chunk, {"encoding": "base64", "commitment": COMMITMENT}])
            out.extend(None if v is None else base64.b64decode(v["data"][0]) for v in result["value"])
        return out

    def get_balance(self, pubkey: Pubkey) -> int:
        return int(self.call("getBalance", [str(pubkey), {"commitment": COMMITMENT}])["value"])

    def get_latest_blockhash(self) -> Blockhash:
        value = self.call("getLatestBlockhash", [{"commitment": COMMITMENT}])["value"]
        return Blockhash(Hash.from_string(value["blockhash"]), int(value["lastValidBlockHeight"]))

    def get_block_height(self) -> int:
        return int(self.call("getBlockHeight", [{"commitment": COMMITMENT}]))

    def get_signatures_for_address(self, pubkey: Pubkey, *, before: str | None = None) -> list[dict[str, Any]]:
        opts: dict[str, Any] = {"commitment": COMMITMENT, "limit": 1000}
        if before:
            opts["before"] = before
        return list(self.call("getSignaturesForAddress", [str(pubkey), opts]))

    def get_transaction_logs(self, signature: str) -> tuple[str, ...] | None:
        """The log messages of a successful transaction; None if unknown or failed."""
        result = self.call(
            "getTransaction",
            [signature, {"encoding": "json", "commitment": COMMITMENT, "maxSupportedTransactionVersion": 0}],
        )
        if result is None or result["meta"]["err"] is not None:
            return None
        return tuple(result["meta"].get("logMessages") or ())

    # --- writes ----------------------------------------------------------------------------

    def send_and_confirm(self, tx: Transaction, blockhash: Blockhash, *, deadline_s: float = 60.0) -> str:
        """Send a signed transaction and wait until it is confirmed; returns its signature."""
        encoded = base64.b64encode(bytes(tx)).decode()
        signature = self.call(
            "sendTransaction",
            [encoded, {"encoding": "base64", "preflightCommitment": COMMITMENT, "maxRetries": 5}],
        )
        deadline = time.monotonic() + deadline_s
        while True:
            statuses = self.call("getSignatureStatuses", [[signature], {"searchTransactionHistory": False}])
            status = statuses["value"][0]
            if status is not None:
                if status.get("err") is not None:
                    logs = self.get_transaction_logs_any(signature)
                    raise TransactionFailed(f"transaction {signature} failed: {status['err']}", logs)
                if status.get("confirmationStatus") in ("confirmed", "finalized"):
                    return str(signature)
            if self.get_block_height() > blockhash.last_valid_block_height:
                raise RpcError(f"transaction {signature} expired before it was confirmed")
            if time.monotonic() > deadline:
                raise RpcError(f"transaction {signature} not confirmed within {deadline_s:.0f}s")
            time.sleep(0.5)

    def get_transaction_logs_any(self, signature: str) -> tuple[str, ...]:
        """Logs of a transaction whether or not it succeeded (empty if unavailable)."""
        try:
            result = self.call(
                "getTransaction",
                [signature, {"encoding": "json", "commitment": COMMITMENT, "maxSupportedTransactionVersion": 0}],
            )
        except RpcError:
            return ()
        return tuple(((result or {}).get("meta") or {}).get("logMessages") or ())
