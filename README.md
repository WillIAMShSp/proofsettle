# ProofSettle: Solana program (Anchor)

On-chain half of the PRD's "audit trail" (sections 8, 9, 10). It stores the agreement hash and rule
parameters, evidence hashes, and the settlement decision, restricts each step to the right party, and
emits an event for every change. It holds no funds (real escrow is a non-goal for the MVP).

**Status: not compiled or run yet.** I wrote this against the Anchor 1.2.x docs but could not build it here.
Expect to fix a small compile error or two on the first `anchor build`.

## Layout

```
Anchor.toml, Cargo.toml, rust-toolchain.toml   Anchor workspace root
programs/proofsettle/
  Cargo.toml
  src/lib.rs      instructions + account contexts
  src/state.rs    Shipment, Evidence, enums
  src/events.rs   audit events
  src/errors.rs   error codes
tests/proofsettle.ts   demo Case A (accepted), Case B (disputed), auth guards, verify_evidence
tests/package.json     test-only deps (kept apart from the web app's package.json)
```

## Setup (Anchor 1.2.x)

The Anchor workspace lives in this repo next to the web app (`Anchor.toml`, `Cargo.toml`,
`rust-toolchain.toml` at the root). The program tests have their own `tests/package.json` so the
web app's `package.json` / `bun.lock` (synced with Lovable) are not touched. `target/` and `.anchor/`
are git-ignored and excluded from ESLint/Prettier.

```bash
avm install 1.2.1 && avm use 1.2.1
(cd tests && npm install)   # mocha, chai, @anchor-lang/core, @solana/web3.js
anchor keys sync            # replaces the placeholder program ID in lib.rs and Anchor.toml
anchor build
anchor test
```

Anchor 1.x moved the TypeScript client to `@anchor-lang/core` (the old `@coral-xyz/anchor` is no longer
the supported path), and `anchor test` now uses Surfpool by default, so install that first.

## State machine

```
Draft --(buyer + supplier approve)--> Agreed --(dispatch photo + mark_in_transit)--> InTransit
  --(buyer records receipt photo)--> Inspection --(authority proposes)--> Proposed
  Proposed --accept--> Accepted
  Proposed --dispute--> Disputed --(authority resolves)--> Resolved
```

## Instructions

| Instruction | Who signs | Effect | PRD endpoint |
|---|---|---|---|
| `create_shipment` | buyer | Registers parties, `terms_hash`, invoice, quantity, rule | `POST /shipments` + `/agreement` |
| `approve_agreement` | buyer, then supplier | Must pass the same `terms_hash`; both approved -> `Agreed` | `POST /agreement/approve` |
| `record_evidence` | supplier (dispatch) / buyer (receipt) | Stores SHA-256 in an `Evidence` PDA | `POST /evidence` |
| `mark_in_transit` | supplier | Needs >= 1 dispatch hash | (status change) |
| `propose_adjustment` | authority | Computes amount from the stored rule | `POST /adjustment` |
| `accept_adjustment` | supplier | -> `Accepted` | `POST /adjustments/{id}/decision` |
| `dispute_adjustment` | supplier | Stores reason hash -> `Disputed` | `POST /adjustments/{id}/decision` |
| `resolve_dispute` | authority | Final amount (<= invoice) -> `Resolved` | (review flow) |
| `verify_evidence` | anyone | Emits `EvidenceVerified { matches }` | `POST /audit/{id}/verify` |

## PDAs

- Shipment: `["shipment", shipment_id]`, where `shipment_id` is the 16 bytes of the Supabase UUID
- Evidence: `["evidence", shipment, index_le_u16]`

## How it maps to the PRD's rules

- **"AI must not decide the amount."** `propose_adjustment` takes a defect count, not an amount:
  `min(defects x credit_per_defect, max_adjustment, invoice)`. The caller cannot override it.
- **Authority.** One key (the FastAPI backend, or a human reviewer) proposes and resolves. It cannot send
  funds anywhere because the program holds none. Both parties see its address before approving.
- **Terms hash.** Put the authority key and the numeric rule parameters inside `terms_json`, so the hash
  both sides approve also commits to them. The program checks the hash matches, not the JSON itself.
- **Audit trail.** Every state change emits an event with a per-shipment `seq`. Store the transaction
  signature in `audit_events.tx_hash`; gaps in `seq` mean a missed event.
- **Chain down.** Treat chain writes as best-effort in the backend so the app keeps working (PRD section 9).

## Known limits

- A hash proves bytes are unchanged since recording, not when or where a photo was taken.
- No timeouts or cancellation (for example, auto-release after 48 hours). Easy to add with `Clock`.
- The authority is trusted for proposals and dispute resolution; multi-sig or a reviewer role split is a
  natural next step.
- An on-chain hash chain over events was left out to avoid depending on hashing helpers whose Anchor 1.x
  re-exports I couldn't confirm. The ledger plus `seq` already gives ordering.
