# ProofSettle: Solana program (Anchor)

The on-chain half of the PRD's audit trail (sections 8, 9 and 10). It stores the agreement
hash and rule parameters, evidence hashes, and the settlement decision. It restricts each step
to the right party and emits an event for every change. It holds no funds: real escrow is a
non-goal for the MVP.

The backend mirrors each shipment's history onto it (`backend/app/chain/`). The database
stays the source of truth, and the chain makes edits to that history detectable. See
`backend/CHAIN_ALIGNMENT.md` for how backend events map onto instructions.

**Status:** builds with Anchor 1.2.1, and 20 Anchor tests pass on Surfpool. The backend's live
anchoring tests also pass against it (`backend/tests/test_chain_live.py`).
Program ID: `FNp1BRdeBxrEqrW2Uyx2VicGtJqpMDGj2XUorkApuabm`.

## Layout

```
Anchor.toml, Cargo.toml, rust-toolchain.toml   Anchor workspace (repo root)
programs/proofsettle/src/
  lib.rs      instructions + account contexts
  state.rs    Shipment, Evidence, enums, the adjustment rule
  events.rs   audit events
  errors.rs   error codes
tests/proofsettle.ts    Anchor tests (own package.json, kept apart from the web app's)
scripts/sync-idl.mjs    post-build hook: copies the IDL to backend/app/chain/proofsettle.json
txtx.yml, runbooks/     Surfpool deployment runbooks (generated, Windows paths fixed)
```

## State machine

```
Draft --(buyer + supplier approve)--> Agreed --(min dispatch photos + mark_in_transit)--> InTransit
  --(buyer records the min receipt photos)--> Inspection --(authority proposes)--> Proposed
  Proposed --(buyer AND supplier accept)--> Accepted
  Proposed --(buyer OR supplier disputes)--> Disputed --(reviewer resolves)--> Resolved
```

## Instructions

| Instruction | Who signs | Effect |
|---|---|---|
| `create_shipment` | buyer | Registers the four parties, `terms_hash`, invoice, quantity, rule, tolerance and photo minimums |
| `approve_agreement` | buyer, supplier | Must pass the same `terms_hash`; both approved -> `Agreed` |
| `record_evidence` | supplier (dispatch) / buyer (receipt) | Stores the SHA-256 in an `Evidence` PDA; reaching the receipt minimum -> `Inspection` |
| `mark_in_transit` | supplier | Needs the dispatch minimum -> `InTransit` |
| `propose_adjustment` | authority | Takes the defect count; computes the amount from the stored rule -> `Proposed` |
| `accept_adjustment` | buyer, supplier | Each party once; `Accepted` only when both have |
| `dispute_adjustment` | buyer, supplier | Stores the reason hash -> `Disputed`; not after that party accepted |
| `resolve_dispute` | reviewer | Takes the reviewed defect count; same rule -> `Resolved` |
| `verify_evidence` | anyone | Emits `EvidenceVerified { matches }` |

Every amount is `min(max(0, defects - tolerance) x credit_per_defect, max_adjustment)`, the same
rule as the backend's settlement engine. No instruction takes an amount from the caller.
Buyer, supplier, authority (rules engine) and reviewer must be four distinct keys.

## PDAs

- Shipment: `["shipment", shipment_id]`, where `shipment_id` is the backend's 16-byte
  `chain_uuid` (uuid5 of e.g. `PS-1042`, optionally salted; see the backend settings)
- Evidence: `["evidence", shipment, index_le_u16]`

## Build and test

Toolchain: Rust (rustup), Agave/Solana CLI 3.1.x, Anchor CLI 1.2.1, Surfpool, Node 20+.

```bash
(cd tests && npm install)
anchor build --arch v0 --tools-version v1.52
anchor test --skip-build
```

- `--arch v0`: Anchor 1.2.1 builds SBPF v3 by default, which devnet doesn't support yet. SBPF
  v0 runs on every cluster.
- `--tools-version v1.52`: the platform tools that ship with Solana CLI 3.1.x. Anchor's default
  is v1.57.
- `anchor keys sync` is only needed with a new program keypair. The deploy key is
  `target/deploy/proofsettle-keypair.json`, which is git-ignored. Back it up: whoever holds it
  controls the program ID.

**Windows (native, no WSL):**

- Anchor runs hooks and scripts with `bash -c`. Put Git's `C:\Program Files\Git\bin` before
  `System32` on PATH.
- Installing Solana's platform tools needs symlinks, so Windows needs admin rights or
  Developer Mode. Without either, unpack `platform-tools-windows-x86_64.tar.bz2` (v1.52) into
  `%USERPROFILE%\.cache\solana\v1.52\platform-tools` yourself. Then link it with
  `mklink /J <solana-release>\bin\platform-tools-sdk\sbf\dependencies\platform-tools <that dir>`.
- `solana-test-validator` needs the same symlink rights, so use Surfpool. Surfpool needs
  OpenSSL 3 (`libcrypto-3-x64.dll`, `libssl-3-x64.dll`) next to `surfpool.exe`. Git for
  Windows ships both in `mingw64\bin`.

## Deploy to devnet

```bash
solana airdrop 2 -u devnet          # or https://faucet.solana.com (deploying needs ~2.5 SOL)
solana program deploy target/deploy/proofsettle.so \
  --program-id target/deploy/proofsettle-keypair.json -u devnet
```

Then point the backend at it; see "Solana anchoring" in the root README.

## Known limits

- A hash proves bytes are unchanged since they were recorded. It doesn't prove when or where a
  photo was taken.
- There are no on-chain timeouts. The inspection window is enforced by the backend only.
- The demo backend holds all four keys (custodial). The signatures show what the backend
  recorded, not each party's own consent. Real wallets would sign the buyer and supplier
  steps in the browser.
- `terms_hash` is checked for equality only. The numeric parameters stored next to it must
  match the hashed terms off-chain, and the backend checks this when it verifies a shipment.
