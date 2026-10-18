"""Operate the Solana anchoring from the command line (run from backend/):

uv run python -m app.chain keygen .solana        # four demo keypairs + the .env lines
uv run python -m app.chain fund --from ~/.config/solana/id.json --sol 0.2
uv run python -m app.chain status                # keys, balances, each shipment's anchoring
uv run python -m app.chain anchor                # send everything not on-chain yet
"""

import argparse
import sys
from pathlib import Path

from solders.keypair import Keypair
from solders.message import Message
from solders.system_program import TransferParams, transfer
from solders.transaction import Transaction
from sqlalchemy import select

from app.chain import get_chain
from app.chain.anchoring import anchor_all, check_shipment, load_shipment, shipment_address
from app.chain.program import Chain, Signer, load_keypair
from app.db import SessionLocal
from app.models import ChainStatus, Shipment

LAMPORTS_PER_SOL = 1_000_000_000


def _require_chain() -> Chain:
    chain = get_chain()
    if chain is None:
        sys.exit(
            "Solana anchoring is not configured: set PROOFSETTLE_SOLANA_RPC_URL and the four "
            "PROOFSETTLE_SOLANA_*_KEYPAIR settings (see backend/CHAIN_ALIGNMENT.md)."
        )
    return chain


def keygen(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    lines = []
    for signer in Signer:
        path = directory / f"{signer.value}.json"
        if path.exists():
            kp = load_keypair(str(path))
            print(f"kept     {path} ({kp.pubkey()})")
        else:
            kp = Keypair()
            path.write_text(kp.to_json(), encoding="utf-8")
            print(f"created  {path} ({kp.pubkey()})")
        lines.append(f"PROOFSETTLE_SOLANA_{signer.value.upper()}_KEYPAIR={path.resolve().as_posix()}")
    print(
        "\nAdd to backend/.env (git-ignored; not the committed root .env), "
        "with PROOFSETTLE_SOLANA_RPC_URL:\n" + "\n".join(lines)
    )


def fund(chain: Chain, funder_path: str, sol: float) -> None:
    funder = load_keypair(funder_path)
    lamports = round(sol * LAMPORTS_PER_SOL)
    ixs = [
        transfer(TransferParams(from_pubkey=funder.pubkey(), to_pubkey=chain.pubkey(s), lamports=lamports))
        for s in Signer
    ]
    blockhash = chain.rpc.get_latest_blockhash()
    tx = Transaction([funder], Message.new_with_blockhash(ixs, funder.pubkey(), blockhash.hash), blockhash.hash)
    print(f"Sent {sol} SOL to each demo key: {chain.rpc.send_and_confirm(tx, blockhash)}")


def status(chain: Chain) -> None:
    print(f"RPC      {chain.rpc.url}\nProgram  {chain.program_id}")
    for s in Signer:
        sol = chain.rpc.get_balance(chain.pubkey(s)) / LAMPORTS_PER_SOL
        print(f"{s.value:<9}{chain.pubkey(s)}  {sol:.4f} SOL")
    with SessionLocal() as db:
        for shipment_id in db.scalars(select(Shipment.id).order_by(Shipment.id)):
            s = load_shipment(db, shipment_id)
            assert s is not None
            counts = {cs: sum(1 for e in s.events if e.chain_status is cs) for cs in ChainStatus}
            report = check_shipment(s, chain)
            summary = ", ".join(f"{n} {cs.value}" for cs, n in counts.items() if n)
            print(f"\n{s.id}  {shipment_address(s, chain)}\n  events: {summary}")
            if not report.available:
                print("  chain unreachable")
            for m in report.mismatches:
                print(f"  mismatch: {m}")


def anchor(chain: Chain) -> None:
    with SessionLocal() as db:
        results = anchor_all(db, chain)
    if not results:
        print("Nothing to anchor.")
    for r in results:
        outcome = f"stopped: {r.error}" if r.error else "done"
        print(f"{r.shipment_id}: {r.sent} tx sent, {r.confirmed} events confirmed, {outcome}")
    if any(r.error for r in results):
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.chain", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("keygen", help="create the four demo keypairs (keeps existing files)")
    p.add_argument("directory", type=Path)
    p = sub.add_parser("fund", help="send SOL to each demo key from a funded keypair")
    p.add_argument("--from", dest="funder", required=True, help="keypair file paying for it")
    p.add_argument("--sol", type=float, default=0.2, help="SOL per key (default 0.2)")
    sub.add_parser("status", help="show keys, balances and each shipment's anchoring")
    sub.add_parser("anchor", help="anchor everything not on-chain yet")
    args = parser.parse_args()

    if args.command == "keygen":
        keygen(args.directory)
    elif args.command == "fund":
        fund(_require_chain(), args.funder, args.sol)
    elif args.command == "status":
        status(_require_chain())
    else:
        anchor(_require_chain())


if __name__ == "__main__":
    main()
