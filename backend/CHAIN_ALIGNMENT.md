# Chain alignment: Solana program vs. backend

This compares the Anchor program on `origin/feat/solana-blockchain` (commit `b02b78f`,
`programs/proofsettle/src/{lib,state,events,errors}.rs` and `tests/proofsettle.ts`) with this
backend (`app/workflow.py`, `app/settlement.py`, `app/resolution.py`, `API_CONTRACT.md`).

The program's README says it was **not compiled or run yet**, and it still uses Anchor's
placeholder program ID (`Fg6PaFpoGXkYsidMpWTK6W2BeZ7FEfcYkg476zPFsLnS`). Everything below is
from reading the source, not from a deployed program.

Short version: the status names and the happy path line up. Two of our rules are not
enforced on-chain: both parties accepting, and a resolution amount that comes from the
engine. The **Recommended program changes** at the end list what to fix.

## 1. Accounts, instructions, signers

### Accounts (PDAs)

| Account | Seeds | Holds |
|---------|-------|-------|
| `Shipment` | `["shipment", shipment_id]`, where `shipment_id: [u8; 16]` (UUID bytes) | Parties, `terms_hash`, numeric rule params, both approval flags, `status`, evidence counters, proposal, dispute and outcome hashes and amounts, `audit_seq`, timestamps, bump |
| `Evidence` | `["evidence", shipment_pubkey, evidence_count as u16 LE]` | `shipment`, `index`, `kind` (Dispatch/Receipt), `sha256`, `uploader`, `recorded_at`, bump |

There are three roles, each a pubkey on `Shipment`: `buyer`, `supplier` and `authority`.
`create_shipment` requires all three to be distinct. There is **no separate reviewer key**.

### Instructions

| Instruction | Args | Signer (enforced by) | Status guard → effect |
|-------------|------|----------------------|-----------------------|
| `create_shipment` | `shipment_id: [u8;16]`, `AgreementParams { supplier, authority, terms_hash, invoice_amount_cents: u64, quantity: u32, credit_per_defect_cents: u64, max_adjustment_cents: u64 }` | **buyer** (signer and rent payer) | creates `Shipment` in `Draft` |
| `approve_agreement` | `terms_hash: [u8;32]` | buyer **or** supplier (checked in handler) | `Draft`; hash must equal the stored one; each party once; moves to `Agreed` when both have approved |
| `record_evidence` | `kind: EvidenceKind`, `sha256: [u8;32]` | Dispatch: **supplier**. Receipt: **buyer**. Uploader pays rent for the `Evidence` account | Dispatch: `Agreed` only. Receipt: `InTransit` or `Inspection`; the first receipt moves to `Inspection`. Max 64 per shipment |
| `mark_in_transit` | none | **supplier** (`address = shipment.supplier`) | `Agreed` and ≥ 1 dispatch evidence → `InTransit` |
| `propose_adjustment` | `confirmed_defects: u32`, `findings_hash`, `explanation_hash` | **authority** | `Inspection` and ≥ 1 receipt evidence; `confirmed_defects ≤ quantity` → `Proposed`; amount computed on-chain |
| `accept_adjustment` | none | **supplier only** | `Proposed` → `Accepted`, `final = proposed` |
| `dispute_adjustment` | `reason_hash` | **supplier only** | `Proposed` → `Disputed` |
| `resolve_dispute` | `final_adjustment_cents: u64`, `resolution_hash` | **authority** | `Disputed`; `final ≤ invoice` → `Resolved` |
| `verify_evidence` | `expected_sha256` | none required (fee payer only) | read-only; emits `EvidenceVerified { matches }` |

Every state-changing instruction increments `Shipment.audit_seq` and emits an event carrying
`seq` and the block timestamp: `ShipmentCreated`, `AgreementApproved`, `EvidenceRecorded`,
`ShipmentDispatched`, `AdjustmentProposed`, `AdjustmentAccepted`, `AdjustmentDisputed`,
`DisputeResolved`. All hashes passed in must be non-zero (`ZeroHash`).

## 2. Statuses and transitions

### Status enum

Same eight states, in the same order. The only difference is the spelling of `In Transit`.
Borsh encodes the enum as a single `u8` index:

| u8 | On-chain `ShipmentStatus` | Our `Status` |
|---:|---------------------------|--------------|
| 0 | `Draft` | `"Draft"` |
| 1 | `Agreed` | `"Agreed"` |
| 2 | `InTransit` | `"In Transit"` |
| 3 | `Inspection` | `"Inspection"` |
| 4 | `Proposed` | `"Proposed"` |
| 5 | `Accepted` | `"Accepted"` |
| 6 | `Disputed` | `"Disputed"` |
| 7 | `Resolved` | `"Resolved"` |

A mapping `CHAIN_STATUS = list(Status)` works as long as neither enum is reordered.

### Transitions vs. `TRANSITIONS`

| From → To | Our actors / guard | On-chain signer / guard | Match? |
|-----------|-------------------|-------------------------|--------|
| Draft → Agreed | System, once both approved | Automatic on the second `approve_agreement`; each approval must carry the matching `terms_hash` | ✅ |
| Agreed → In Transit | Supplier | Supplier; ≥ 1 dispatch evidence | ✅ (we require `minDispatchPhotos`, e.g. 4; chain checks only ≥ 1) |
| In Transit → Inspection | Buyer | Buyer, implicitly via the first receipt `record_evidence` | ✅ (receipt minimum is again only ≥ 1 on-chain) |
| Inspection → Proposed | System (rules engine) | authority | ✅ if the backend holds the authority key |
| Proposed → Accepted | Buyer **and** Supplier, both required | **Supplier alone** | ❌ |
| Proposed → Disputed | Buyer **or** Supplier, reason required | **Supplier only**, `reason_hash` required | ❌ (buyer can't dispute) |
| Disputed → Resolved | **Reviewer only**, `needsReview` empty, amount = engine output | authority, any amount ≤ invoice | ⚠️ / ❌ (see below) |
| Disputed → Proposed | not allowed | not allowed (`dispute_adjustment` needs `Proposed`, `propose_adjustment` needs `Inspection`) | ✅ |
| Terminal | Accepted, Resolved | Accepted, Resolved (no instruction leaves them) | ✅ |

## 3. Mismatches with our rules

1. **Acceptance needs both parties? No.** `accept_adjustment` is a `SupplierAction`. The
   buyer has no acceptance instruction, and one supplier signature makes the shipment
   `Accepted`. Our `workflow.accept` keeps the shipment `Proposed` until `buyerAcceptedAt`
   and `supplierAcceptedAt` are both set. Also missing on-chain: "a party that has accepted
   can no longer dispute". A single acceptance closes the proposal anyway, so that rule has
   nothing to apply to yet.
2. **Buyer can't dispute.** `dispute_adjustment` is also supplier-only. We allow either party.
3. **Can only a reviewer resolve? Not as a separate role.** `resolve_dispute` checks
   `authority`, which is the same key that signs `propose_adjustment`. The program's own
   comment says the authority is "ProofSettle backend (rules engine) or a designated human
   reviewer". On-chain, the System/rules engine (propose) and the Reviewer (resolve) are one
   signer. Buyer and supplier are correctly blocked (the test "supplier cannot resolve their
   own dispute" checks this). If the backend holds the authority key, the Reviewer-only rule
   rests on the API's `X-Demo-Role` check alone.
4. **Does any instruction take an amount from the caller? Yes: `resolve_dispute`.**
   It takes `final_adjustment_cents: u64` and checks only `≤ invoice_amount_cents`. It
   doesn't check `max_adjustment_cents`, the defect count, or any hash of the engine's
   output. That contradicts "Resolution is the engine's output, not a typed-in number"
   (`app/resolution.py`). `resolution_hash` is an unconstrained commitment, so nothing ties
   it to the amount.
   `propose_adjustment` is better. It takes `confirmed_defects` and computes the amount from
   stored params, but:
   - **The formula ignores `defectToleranceUnits`.** On-chain:
     `min(defects × credit_per_defect, max_adjustment, invoice)`. Ours:
     `min(max(0, defects − tolerance) × amountPerUnit, maxCredit)`. These agree only when
     the tolerance is 0, as in the PS-1042 seed. With tolerance 1 and 3 defects, the chain
     proposes $300 and the engine $200.
   - `confirmed_defects` is still a caller-supplied number. Pass `adjustment.confirmed_defects`,
     which counts distinct units after the review/coverage/dispatch/confidence rules. The
     only binding to how it was derived is `findings_hash`.
   - No instruction takes a hash of the engine's `Adjustment`. `explanation_hash` is the
     closest slot (see §4).
5. **Disputed → Proposed path? No.** That matches our rule.
6. **Does it move real funds? No.** There is no token or escrow account and no SOL transfer
   to a counterparty. The only lamports involved are rent for the `Shipment` and `Evidence`
   accounts (the buyer pays for the first, the uploader for each evidence record) and
   transaction fees. Buyer and supplier keys therefore need devnet SOL.
7. Smaller gaps:
   - **Inspection window.** `inspectionWindowHours` has no on-chain check.
   - **Shipment IDs.** The PDA seed is a 16-byte UUID, but our IDs are `PS-1042`. We need a
     UUID per shipment: store a `uuid4` column, or derive one with `uuid5(NAMESPACE, "PS-1042")`.
   - **Concurrent evidence.** The `Evidence` PDA is indexed by the current `evidence_count`.
     Two uploads sent at once derive the same address, and one fails. The backend must send
     evidence transactions one at a time per shipment and re-read `evidence_count` before
     each.
   - **Rule params vs. `terms_hash`.** The numeric params are stored next to `terms_hash`,
     but nothing on-chain checks that they match the hashed terms JSON. Each party must check
     that off-chain before approving.

## 4. What is stored on-chain, and the hash format

**Hashes** (all `[u8; 32]`, raw bytes, must not be all zeros):

| Field | Meaning in the program | What our backend should put there |
|-------|------------------------|-----------------------------------|
| `Shipment.terms_hash` | sha256 of the canonical `terms_json` (the comment asks that it include the authority key and the numeric params) | `sha256(canonical_json(agreement))`, where `agreement` = `AgreementTerms` JSON plus the three pubkeys (see below) |
| `Evidence.sha256` | sha256 of one evidence file | `evidence.sha256`, the hash of the raw uploaded bytes (already our definition) |
| `Shipment.findings_hash` | sha256 of the human-reviewed findings JSON | `sha256(canonical_json([f.model_dump(mode="json", by_alias=True) for f in findings]))` |
| `Shipment.explanation_hash` | sha256 of the explanation shown to both parties | `sha256(canonical_json(adjustment.model_dump(mode="json", by_alias=True)))`, i.e. the engine's full output (`appliedRule`, `counted`, `excluded`, `needsReview`, `assumptions`) |
| `Shipment.dispute_reason_hash` | sha256 of the written reason | `sha256(reason.encode("utf-8"))` |
| `Shipment.resolution_hash` | sha256 of the resolution record | `sha256(canonical_json(resolved_adjustment))`, the recomputed `Adjustment` from `resolution.resolve` |

**Plain values:** the three pubkeys; `invoice_amount_cents`, `credit_per_defect_cents`,
`max_adjustment_cents`, `proposed_adjustment_cents` and `final_adjustment_cents` as `u64`
**cents**; `quantity` and `confirmed_defects` as `u32`; approval flags; status; evidence
counters; `audit_seq`; `created_at` / `updated_at` as unix seconds.

Our `event.hash` audit chain is **not** stored on-chain. The program says it left out an
on-chain hash chain. `events[].txHash` becomes the Solana transaction signature (base58,
88 chars), not a 64-hex SHA-256. `audit_seq` gives a per-shipment counter the backend can
use to spot missing chain events.

### Fitting our output into the hashes

- The format is **32 raw bytes of SHA-256**. Our API uses lowercase 64-char hex, so convert
  at the boundary: `list(bytes.fromhex(h))` going in, `bytes(arr).hex()` coming out.
  `hashlib.sha256(...).digest()` is already the right shape.
- `canonical_json` isn't implemented yet: the `API_CONTRACT.md` Hashing section is still
  Proposed and no code exists. When it's written, pin it down exactly:
  `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")`,
  applied to `model_dump(mode="json", by_alias=True)`. That way money goes through `Money`'s
  serializer (`10000`, `99.99`) and never through `str(Decimal)`. If the TypeScript side ever
  has to re-derive these hashes, use RFC 8785 (JCS) on both sides instead, because Python's
  and JS's float formatting (`minConfidence: 0.85`) only happens to agree.
- **Money units.** The chain uses integer cents and we use `Decimal` dollars with at most 2
  dp. `int(amount * 100)` is exact, and `NUMERIC(12,2)` maxes out far below `u64`. After
  every propose, the backend should read back `proposed_adjustment_cents` and check that it
  equals `int(adjustment.credit * 100)`. If they differ (the tolerance case above), treat it
  as an anchoring failure.
- `AgreementParams` comes from `AgreementTerms`: `quantity`,
  `invoice_amount_cents = cents(invoiceAmount)`,
  `credit_per_defect_cents = cents(compensation.amountPerUnit)`,
  `max_adjustment_cents = cents(compensation.maxCredit)`. Our validator already guarantees
  `maxCredit ≤ invoiceAmount`, which the program requires.

## 5. Calling it from the Python backend

### Who signs what

| On-chain role | Who holds the key | Signs |
|---------------|-------------------|-------|
| `authority` | **Backend (oracle)**, server-side keypair from config/secret, never sent to clients | `propose_adjustment` (after `compute_adjustment`), `resolve_dispute` (only after a `Reviewer` request passes `resolution.resolve`) |
| `buyer` | Buyer's wallet (or a backend-held demo key, see below) | `create_shipment` (payer), `approve_agreement`, `record_evidence(Receipt)` |
| `supplier` | Supplier's wallet (or demo key) | `approve_agreement`, `record_evidence(Dispatch)`, `mark_in_transit`, `accept_adjustment`, `dispute_adjustment` |
| Reviewer | No on-chain identity today | Acts through the API. The backend then signs `resolve_dispute` as authority |

There are two ways to handle buyer and supplier keys:

- **Demo / MVP: custodial.** The backend holds one keypair per demo party, keyed by
  `X-Demo-Role`, and signs for them. It's simple, but those signatures then prove nothing
  about consent.
- **Real wallets.** The backend builds the transaction with the authority as neither signer
  nor payer, returns it base64-encoded, and the frontend signs it with the user's wallet and
  submits it. The backend then confirms by reading the account and events.

Either way, the chain is a mirror, not the source of truth. Do the DB transition first,
anchor afterwards, and store the signature in `txHash`. If the RPC is unreachable, the
workflow still proceeds and `chain.available: false` (PRD §9: the app works without the
chain).

### Library choice

| Package | Latest | Released | Status |
|---------|--------|----------|--------|
| `anchorpy` | 0.21.0 | 2025-03-26 | Repo `kevinheavey/anchorpy` isn't archived, but its last push was 2025-03-26. Snyk rates it Inactive, and an open issue asks for Anchor 0.32 support. Unproven against this program's **Anchor 1.2.1** IDL |
| `solders` | 0.29.0 | 2026-08-13 | Active (keypairs, `Pubkey.find_program_address`, `Instruction`, transactions) |
| `solana` (solana-py) | 0.41.0 | 2026-10-03 | Active (async RPC client), requires Python ≥ 3.11; we're on 3.12 |

(PyPI and GitHub data checked 2026-10-17.)

**Recommendation: `solders` + `solana`, with a small hand-written codec driven by the IDL.**
Don't use AnchorPy. Our layout is all fixed-size (no `Vec`, `String` or `Option`), so Borsh
here is just little-endian `struct.pack`. Taking discriminators from the IDL that
`anchor build` writes (`target/idl/proofsettle.json`) keeps us in step with the program and
needs no generator.

- Instruction data = 8-byte discriminator + Borsh args. The Anchor default discriminator is
  `sha256(b"global:<ix_name>")[:8]`, and the IDL lists it per instruction. Read it from the
  IDL rather than hard-coding it.
- Accounts are 8-byte `sha256(b"account:Shipment")[:8]` + fields. Events show up in tx logs
  as `Program data: <base64>` with an `sha256(b"event:<Name>")[:8]` prefix.
- `AgreementParams` = `<32s32s32sQIQQ` (124 bytes). `create_shipment` data =
  disc + `16s` + params.
- `Shipment` after the discriminator =
  `<16s32s32s32s32sQIQQ??BHHHI32s32sQ32s32sQQqqB` (`struct.calcsize` = 354, which matches
  `INIT_SPACE`).
- `Evidence` after the discriminator = `<32sHB32s32sqB`.
- `EvidenceKind` and `ShipmentStatus` are one `u8` each.

```python
import hashlib, struct, uuid
from solders.pubkey import Pubkey
from solders.instruction import Instruction, AccountMeta

def shipment_pda(program_id: Pubkey, shipment_uuid: uuid.UUID) -> Pubkey:
    return Pubkey.find_program_address([b"shipment", shipment_uuid.bytes], program_id)[0]

def propose_ix(program_id, disc: bytes, shipment: Pubkey, authority: Pubkey,
               confirmed_defects: int, findings_hash: bytes, explanation_hash: bytes) -> Instruction:
    data = disc + struct.pack("<I32s32s", confirmed_defects, findings_hash, explanation_hash)
    return Instruction(program_id, data, [
        AccountMeta(shipment, is_signer=False, is_writable=True),
        AccountMeta(authority, is_signer=True, is_writable=False),
    ])
```

Account order must follow each `#[derive(Accounts)]` struct exactly. For example,
`CreateShipment` is `shipment` (w), `buyer` (s, w), then `system_program`, and
`RecordEvidence` is `shipment` (w), `evidence` (w), `uploader` (s, w), then `system_program`.
Cover the codec with a pytest that round-trips against `anchor test` output, or against a
local validator, once the program builds.

## Recommended program changes

Ask the program's author for these. They are listed in order of impact.

1. **Two-party acceptance.** Add `buyer_accepted` / `supplier_accepted` flags and let either
   party call `accept_adjustment`. Move to `Accepted` only when both are set, and reject
   `dispute_adjustment` from a party that has already accepted.
2. **Let the buyer dispute.** Make `dispute_adjustment` buyer-or-supplier, as
   `approve_agreement` already is.
3. **Drop the free amount from `resolve_dispute`.** Take `confirmed_defects: u32` +
   `resolution_hash`, and compute `final` with the same function as `propose_adjustment`.
   The resolution is then the engine's output by construction.
4. **Add the tolerance to the rule.** Add `defect_tolerance_units: u32` to `AgreementParams`
   / `Shipment` and use `min(max(0, d − tol) × credit, max_adjustment)`. Otherwise the
   on-chain amount and `compute_adjustment` diverge whenever tolerance > 0.
5. **A separate `reviewer` pubkey** on `Shipment`, distinct from buyer and supplier, as the
   only signer of `resolve_dispute`. `authority` keeps `propose_adjustment`. That mirrors
   `Actor.SYSTEM` vs. `Actor.REVIEWER`.
6. Optionally, `min_dispatch_photos` / `min_receipt_photos` in params, so the evidence
   minimums are enforced on-chain too.
