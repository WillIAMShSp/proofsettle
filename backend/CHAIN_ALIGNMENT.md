# Chain alignment: Solana program vs. backend

How the Anchor program (`programs/proofsettle/`) lines up with this backend
(`app/workflow.py`, `app/settlement.py`, `app/resolution.py`), and how the backend mirrors
each shipment onto it (`app/chain/`).

**Status:** implemented. The program builds with Anchor 1.2.1, and its 20 Anchor tests pass.
The backend anchors every workflow event; `tests/test_chain_live.py` runs that end to end
against a local validator. Program ID: `FNp1BRdeBxrEqrW2Uyx2VicGtJqpMDGj2XUorkApuabm`.

An earlier version of this document compared the first program draft (commit `b02b78f`) with
the backend and listed six recommended program changes. Commit `cc14a7c` made all six:

| Recommended change | Now on-chain |
|---|---|
| 1. Two-party acceptance | `buyer_accepted` / `supplier_accepted`; `Accepted` only when both are set; a party that accepted can't dispute |
| 2. The buyer can dispute | `dispute_adjustment` is buyer-or-supplier |
| 3. No free amount in `resolve_dispute` | Takes `confirmed_defects` and applies the same rule as the proposal |
| 4. Defect tolerance | `defect_tolerance_units`; rule `min(max(0, d - tol) x credit, max)` |
| 5. A separate reviewer key | `reviewer` is the only signer of `resolve_dispute`; `authority` proposes |
| 6. Photo minimums on-chain | `min_dispatch_evidence` / `min_receipt_evidence` |

## 1. Accounts, instructions, signers

| Account | Seeds | Holds |
|---|---|---|
| `Shipment` | `["shipment", shipment_id]`, `shipment_id: [u8; 16]` | Four parties, `terms_hash`, rule params, approvals, status, evidence counters, proposal, both acceptances, dispute and outcome, `audit_seq`, timestamps |
| `Evidence` | `["evidence", shipment, evidence_count as u16 LE]` | `kind`, `sha256`, `uploader`, `recorded_at` |

`shipment_id` is the shipment's `chain_uuid` (`uuid5(SHIPMENT_NAMESPACE, "PS-1042")`). When
`PROOFSETTLE_SOLANA_SHIPMENT_SALT` is set, it's `uuid5(chain_uuid, salt)` instead.

| Instruction | Signer | Status guard -> effect |
|---|---|---|
| `create_shipment` | buyer (rent payer) | -> `Draft`; the four keys must be distinct |
| `approve_agreement(terms_hash)` | buyer or supplier | `Draft`; hash must match; both -> `Agreed` |
| `record_evidence(kind, sha256)` | supplier (Dispatch) / buyer (Receipt) | Dispatch in `Agreed`; Receipt in `InTransit`/`Inspection`, and reaching `min_receipt_evidence` moves `InTransit` -> `Inspection` |
| `mark_in_transit` | supplier | `Agreed` and ≥ `min_dispatch_evidence` -> `InTransit` |
| `propose_adjustment(confirmed_defects, findings_hash, explanation_hash)` | authority | `Inspection` -> `Proposed`; amount from the rule |
| `accept_adjustment` | buyer or supplier | `Proposed`; each once; both -> `Accepted` (`final = proposed`) |
| `dispute_adjustment(reason_hash)` | buyer or supplier, if not accepted | `Proposed` -> `Disputed` |
| `resolve_dispute(confirmed_defects, resolution_hash)` | reviewer | `Disputed` -> `Resolved`; amount from the rule |
| `verify_evidence(expected_sha256)` | none (fee payer only) | read-only; emits `EvidenceVerified { matches }` |

Every state-changing instruction bumps `Shipment.audit_seq` by exactly one and emits an event
carrying `seq`.

## 2. Statuses and transitions

The two enums match one to one. Only `InTransit` vs `"In Transit"` is spelled differently
(`app/chain/program.py: CHAIN_STATUS`).

| From -> To | Backend actors / guard | On-chain | Match |
|---|---|---|---|
| Draft -> Agreed | System, once both approved | second `approve_agreement` | ✅ |
| Agreed -> In Transit | Supplier, `minDispatchPhotos` reached | `mark_in_transit`, same minimum | ✅ |
| In Transit -> Inspection | Buyer, `minReceiptPhotos` reached | the receipt that reaches the minimum | ✅ |
| Inspection -> Proposed | System (rules engine) | authority | ✅ |
| Proposed -> Accepted | Buyer **and** Supplier | both `accept_adjustment` | ✅ |
| Proposed -> Disputed | Buyer or Supplier, if not accepted | same | ✅ |
| Disputed -> Resolved | Reviewer, engine output | reviewer, same rule | ✅ |

Remaining differences, all deliberate:

- The **inspection window** (`inspectionWindowHours`) is enforced by the backend only.
- **Receipts after the minimum.** The backend accepts receipt photos only while In Transit,
  but one upload may hold more than the minimum. The chain therefore also takes receipts in
  `Inspection`, so the rest of that upload can be recorded.
- **Defect counting.** Which findings count (review, coverage, dispatch, confidence) is
  decided off-chain. The chain takes the resulting `confirmed_defects` and is bound to how it
  was derived through `findings_hash` and `explanation_hash`.
- **`terms_hash` is `sha256(canonical_json(terms))`.** It is not the agreement plus the
  three pubkeys this document once suggested: the hash both parties approve in the API is the
  one stored on-chain, and the parties' keys sit next to it in the account.

## 3. How the backend anchors (`app/chain/`)

| Backend event | Program instructions | Signer |
|---|---|---|
| `agreement.drafted` | `create_shipment` | buyer |
| `agreement.approved` | `approve_agreement` for the party (both, for the seed's combined event) | that party |
| `evidence.uploaded` | `record_evidence` per file, then `mark_in_transit` if the upload moved it to In Transit | uploader / supplier |
| `shipment.status_changed` (to In Transit; the seed) | `mark_in_transit` | supplier |
| `inspection.completed` | none (`skipped`); its `findingsHash` goes into the proposal | |
| `adjustment.proposed` | `propose_adjustment(confirmedDefects, findingsHash, adjustmentHash)` | authority |
| `adjustment.accepted` | `accept_adjustment` | that party |
| `adjustment.disputed` | `dispute_adjustment(sha256(reason))` | that party |
| `finding.reviewed` | none (`skipped`) | |
| `dispute.resolved` | `resolve_dispute(confirmedDefects, adjustmentHash)` | reviewer |

- **Order.** The database transition commits first. A background task then sends the event's
  instructions, as one transaction per event (chunked at 8 instructions), and stores the
  signature in `chain_tx_hash` (`chainStatus: confirmed`). If the RPC fails, the event becomes
  `failed` and the workflow carries on (PRD §9). The next write, a backend restart, or
  `POST /shipments/{id}/chain/anchor` retries it.
- **Resumable by construction.** Each event's instructions come only from its own
  hash-chained payload and the immutable agreement. So the full instruction list is a function
  of the history, and the on-chain `audit_seq` is how far along it the chain is. Anchoring
  sends only the rest. That also finishes half-sent uploads, and it recovers a signature that
  was sent but never stored, by reading `seq` out of the shipment's transaction logs.
- **Read-back.** After a proposal or resolution, the on-chain amount must equal
  `cents(adjustment.credit)`; otherwise the event is `failed`.
- **Divergence.** If the account's parties, terms or rule differ from the database, or its
  `audit_seq` is ahead of the history, anchoring stops and reports it. That happens, for
  example, after `POST /dev/reset` without a new salt.

### Verification (`POST /shipments/{id}/audit/verify`)

`check_shipment` replays the instruction list up to the on-chain `audit_seq` with the
program's rules. It compares the result field by field with the `Shipment` account, and each
anchored `Evidence` record with the stored file hash. Once fully anchored, it also compares
the status. A mismatch goes into `chain.mismatches` and makes `verified` false. This catches
an edit that local re-hashing can't: for example, a photo swapped together with its stored
hash (`test_a_swapped_photo_is_caught_by_the_chain`).

### Keys

| On-chain role | Key |
|---|---|
| `buyer`, `supplier` | Server-held demo keys (custodial). They stand in for the parties' wallets, so they record what the backend did, not each party's consent |
| `authority` | Rules engine; signs only `propose_adjustment` |
| `reviewer` | Signs only `resolve_dispute`, after the API's Reviewer check |

The real-wallet alternative still applies: the backend builds the buyer and supplier
transactions, the browser signs them, and the backend confirms them by reading the account.

### Libraries

The backend uses `solders` (keys, PDAs, transactions) with a small synchronous JSON-RPC client
over `urllib` (`app/chain/rpc.py`). `solana-py` 0.41 dropped its synchronous client, and the
backend's routes are synchronous. The Borsh codec (`app/chain/codec.py`) reads discriminators,
account order and field layouts from the IDL that `anchor build` copies to
`app/chain/proofsettle.json`, so it can't drift from the program.

## 4. What is stored on-chain, and the hash format

All hashes are `[u8; 32]` raw SHA-256, and never all zeros. In the API and the database they
are 64 lowercase hex characters; `hashing.to_chain_bytes` / `from_chain_bytes` convert at the
boundary.

| Field | Value |
|---|---|
| `terms_hash` | `agreement.terms_hash` = `sha256(canonical_json(terms))` |
| `Evidence.sha256` | `evidence.sha256`, the hash of the uploaded bytes |
| `findings_hash` | the `inspection.completed` payload's `findingsHash` |
| `explanation_hash` | the proposal's `adjustmentHash` = `sha256(canonical_json(adjustment))` |
| `dispute_reason_hash` | `sha256(reason.encode("utf-8"))` |
| `resolution_hash` | the resolution's `adjustmentHash` (the recomputed `Adjustment`) |

Money is integer **cents** (`u64`): `cents(Decimal)` is exact for 2-dp amounts. The audit
trail's own `eventHash` chain is not stored on-chain; `audit_seq` plus the per-event signatures
tie the two together.
