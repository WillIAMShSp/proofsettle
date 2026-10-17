# ProofSettle API Contract (draft v0)

What the FastAPI backend must return so the existing frontend (`src/lib/store.tsx`,
`src/routes/dashboard.tsx`, `src/routes/shipments.$id.tsx`) can drop its mock data.
Sections marked **Proposed** are not implemented yet and are open for review.

## Storage

FastAPI owns the schema (`backend/app/models.py`) and is the only writer of business state.
Tables are created on startup. SQLite (`./proofsettle.db`) is the default for local dev and
tests. For the demo, `PROOFSETTLE_DATABASE_URL` points at the Supabase Postgres database
(`postgresql+psycopg://...`), where our tables live in their own **`proofsettle`** schema.
Supabase's `public` schema has Lovable-generated tables with the same names (`shipments`,
`agreements`, `evidence`, `adjustments`, `audit_events`, ...) and a different shape. The
backend never reads or writes those.

`uv run python -m app.seed_db` drops and recreates our tables, then loads `PS-1042`,
`PS-1038` and `PS-1031`. Each one is replayed through the workflow, so the stored statuses
follow the rules and every audit chain verifies. Evidence files are `src/assets/dispatch.jpg`
and `receipt.jpg`, copied to `PROOFSETTLE_EVIDENCE_DIR` (default `./storage/evidence`) with
their real SHA-256.

## Conventions

- Every JSON response, errors included, has `Content-Type: application/json; charset=utf-8`.
  Bodies contain literal `×`, `−` and `≥`, and Windows PowerShell 5.1 garbles them without the
  charset.
- JSON keys are **camelCase** to match the TypeScript types (`disputeReason`, not
  `dispute_reason`). Python code stays snake_case; Pydantic aliases do the mapping.
- Money is a JSON **number in dollars (USD)**, matching `amount: 10000` in the frontend,
  with at most 2 decimal places. Inside the backend it is `Decimal` end to end: DB columns
  are `NUMERIC(12,2)`, Pydantic fields are `Decimal`, and all money math is `Decimal`.
  Floats never take part in money math. The only conversion is at the JSON boundary, where
  a `Decimal` is written out as a number. The backend never accepts an adjustment amount
  from the client: it always recomputes it from stored agreement terms.
- Timestamps are **ISO 8601 UTC** (`"2026-10-09T10:12:00Z"`). The frontend currently stores
  pre-formatted strings (`"Oct 09, 10:12"`, `"Just now"`); it should format `at` itself.
- Hashes are **lowercase hex SHA-256** (64 chars). The frontend's `hashOf` is a fake
  FNV-based function that also yields 64 hex chars, so `short()` keeps working unchanged.
- Caller role, until real auth exists: header `X-Demo-Role: Buyer | Supplier | Reviewer`
  (mirrors the fake login). Every `/shipments` route requires it (`400` if it's missing or
  invalid), and the backend validates the role on every write. `GET /evidence/{id}/file` is
  exempt, because an `<img src>` can't send headers. `Reviewer` is a
  neutral third party who resolves disputes. The frontend's `Role` type and login screen
  don't have it yet.

## Types (verbatim from `src/lib/store.tsx`)

```ts
export type Role = "Buyer" | "Supplier";
export const STATUSES = ["Draft", "Agreed", "In Transit", "Inspection", "Proposed", "Accepted", "Disputed", "Resolved"] as const;
export type Status = (typeof STATUSES)[number];
export type AuditEvent = { at: string; actor: string; text: string; hash: string };
export type Shipment = {
  id: string; title: string; buyer: string; supplier: string; amount: number; status: Status;
  disputeReason?: string; events: AuditEvent[];
};
```

`AuditEvent.actor` is free text today; seeded values are `"Buyer"`, `"Supplier"`, `"System"`,
`"AI"`, and `log()` falls back to `"User"`. The API restricts it to
`"Buyer" | "Supplier" | "Reviewer" | "System" | "AI"`.

## The 8 statuses

Exact strings, including the space and capitalisation in `"In Transit"`:

| # | Status       | Backend enum member |
|---|--------------|---------------------|
| 1 | `Draft`      | `Status.DRAFT`      |
| 2 | `Agreed`     | `Status.AGREED`     |
| 3 | `In Transit` | `Status.IN_TRANSIT` |
| 4 | `Inspection` | `Status.INSPECTION` |
| 5 | `Proposed`   | `Status.PROPOSED`   |
| 6 | `Accepted`   | `Status.ACCEPTED`   |
| 7 | `Disputed`   | `Status.DISPUTED`   |
| 8 | `Resolved`   | `Status.RESOLVED`   |

Allowed transitions (PRD §9), as implemented in `backend/app/workflow.py`:

| From         | To           | Who may trigger                          |
|--------------|--------------|------------------------------------------|
| `Draft`      | `Agreed`     | System, once both parties have approved  |
| `Agreed`     | `In Transit` | Supplier (dispatch evidence uploaded)    |
| `In Transit` | `Inspection` | Buyer (receipt evidence uploaded)        |
| `Inspection` | `Proposed`   | System (rules engine)                    |
| `Proposed`   | `Accepted`   | Buyer and Supplier: both must accept     |
| `Proposed`   | `Disputed`   | Buyer or Supplier, reason required       |
| `Disputed`   | `Resolved`   | Reviewer only, once `needsReview` is empty |

`Accepted` and `Resolved` are terminal. Any other transition is rejected with `409`. A
role outside the "Who may trigger" column gets `403`. For example, Buyer or Supplier
resolving a dispute gets `403`, because neither party may resolve its own dispute. There is
no `Disputed → Proposed` path: a disputed proposal cannot be revised and re-proposed, and
the only way out of `Disputed` is a Reviewer moving it to `Resolved`.

A role that may make a move, but on a shipment that isn't ready for it, gets `409`:

- **Acceptance needs both parties.** Each party accepts separately. The adjustment records
  `buyerAcceptedAt` and `supplierAcceptedAt`, and the status stays `Proposed` until both
  are set. The second acceptance moves it to `Accepted`. Accepting twice is a no-op that
  keeps the first timestamp.
- **A party that has accepted can no longer dispute.** The other party still can, until it
  accepts too.
- **Resolution is the engine's output, not a typed-in number.** While `Disputed`, the
  Reviewer sets `reviewOverride` (`"confirmed"` or `"rejected"`) on findings. Resolving
  recomputes the adjustment from the reviewed findings, and is refused while the recomputed
  `needsReview` is non-empty. The resolved `credit` and `settlementAmount` are that
  recomputed adjustment's. For PS-1042, confirming `fnd_04` (#063) gives `4 × $100 = $400`
  and `$10,000 − $400 = $9,600`; rejecting it keeps `$300` / `$9,700`. The Reviewer may also
  confirm or reject findings outside `needsReview`; the engine counts them the same way.

`backend/app/workflow.py` (`accept`, `transition`) and `backend/app/resolution.py`
(`review_finding`, `resolve`) implement these rules.

The frontend's Supplier-only Accept/Dispute buttons no longer match this table. They should
follow `actions.canAccept` / `actions.canDispute`, which the backend computes for both
parties. The backend enforces every rule above regardless.

## Hard-coded values in `shipments.$id.tsx` that must come from the API

| Line | Constant / literal | Current value | Moves to |
|------|--------------------|---------------|----------|
| 20 | `STEPS` | the first 6 statuses | **Stays client-side.** Pure presentation, derived from `STATUSES`. |
| 50, 69 | stepper slot 5 shows `Disputed`/`Resolved` | logic | Stays client-side. |
| 21 | `CREDIT` | `100` | `agreement.terms.compensation.amountPerUnit` |
| 22–27 | `findings` | 4 items (see below) | `inspection.findings` |
| 23–26 | `confirmed` flags | hand-set booleans | Which list the finding is in: `adjustment.counted`, `adjustment.excluded` or `adjustment.needsReview` (see Settlement engine) |
| 145 | "≥ 85% confidence" | `0.85` | `agreement.terms.acceptance.minConfidence` |
| 48 | `defects` | `findings.filter(confirmed).length` = 3 | `adjustment.confirmedDefects` |
| 49 | `adj` | `defects * CREDIT` = 300 | `adjustment.credit` |
| 140 | rule line | `{defects} confirmed defects × ${CREDIT} = ${adj}` | `adjustment.appliedRule.credit` |
| 141 | settlement | `s.amount - adj` = 9,700 | `adjustment.settlementAmount`; the line is `adjustment.appliedRule.settlement` |
| 147 | "would rise to `adj + CREDIT`" | 400 | `adjustment.amountIfReviewedConfirmed` |
| 87 | Goods | `"100 machined metal components"` (differs from `title` "100 metal components") | `agreement.terms.quantity` + `agreement.terms.itemDescription` |
| 92–94 | approval badges | both always "approved" | `agreement.buyerApproved`, `agreement.supplierApproved` |
| 99, 5–6 | evidence images | `dispatch.jpg` / `receipt.jpg` assets, 4 each | `evidence[].url`, grouped by `evidence[].kind` |
| 103 | photos per group | `[0, 1, 2, 3]` | `evidence.length` per kind; minimums in `agreement.terms.evidenceRequirements` |
| 107 | evidence hash | `hashOf(label + n)` (fake) | `evidence[].sha256` |
| 108 | "Verified" check | always shown | `evidence[].verified` (from the last verify run; `null` = never checked) |
| 145 | Assumptions list | 3 strings | `adjustment.assumptions` |
| 147 | Uncertainty list | 2 strings, `#063` hard-coded | Built from `adjustment.needsReview` and `adjustment.amountIfReviewedConfirmed` |
| 152 | decision shown when `Accepted`/`Disputed` | status check | `status`, plus `actions` and `adjustment.buyerAcceptedAt` / `supplierAcceptedAt` (below) |
| 157 | `role === "Supplier"` to show buttons | client role check | `actions.canAccept`, `actions.canDispute`, shown to Buyer and Supplier alike |
| 52 | event `at: "Just now"` | literal | server timestamp |
| 52 | event `actor: role ?? "User"` | client value | server, from the authenticated role |
| 52 | event `hash: hashOf(text)` | client hash | server SHA-256 (see Hashing) |
| 164, 170 | event text `"Supplier accepted $300 adjustment"` etc. | client-built | server-built |
| 181 | verify button | `setTimeout(900)` then always OK | `POST /shipments/{id}/audit/verify` |
| 182 | `"${events.length} hashes verified"` | event count | `verify.checked` / `verify.verified` |

Static copy (the "AI never decides the payment amount" banner, the "AI cannot prove when or
where" note, page `head` meta) stays in the frontend.

Current mock findings, which become the seeded inspection for `PS-1042`:

| id | unitRef | description | defectType | confidence | outcome |
|----|---------|-------------|------------|-----------:|---------|
| `fnd_01` | Component #017 | Bent flange | `bend` | 0.94 | counted |
| `fnd_02` | Component #042 | Surface crack near bore | `crack` | 0.91 | counted |
| `fnd_03` | Component #078 | Deep scratch on mating face | `deep_scratch` | 0.88 | counted |
| `fnd_04` | Component #063 | Possible discoloration | `discoloration` | 0.52 | needs review |

These are `PS_1042_FINDINGS` in `backend/app/seed.py`. None is present at dispatch and none
has been reviewed.

Seed data from `store.tsx` to replicate: `PS-1042` (Proposed, 7 events), `PS-1038`
(In Transit, 40 hydraulic valves, $6,400, Kestrel Fluid Systems), `PS-1031` (Resolved,
250 steel brackets, $3,750). All buyers are Northgate Assembly Ltd.

As seeded by `backend/app/seed_db.py`:

- **`PS-1042`** has `store.tsx`'s 7 events, with the same texts and times (in 2026). One
  change: "Shipment marked In Transit" has actor `Supplier`, not `System`, because only the
  Supplier may make that move. Evidence is `ev_01`–`ev_04` (dispatch) and `ev_05`–`ev_08`
  (receipt), and the adjustment is `adj_01`.
- **`PS-1038`** has 4 events, through In Transit, and dispatch evidence `ev_09`–`ev_12`. It
  has no findings or adjustment yet.
- **`PS-1031`** has 11 events. It is $15 per bracket with 1 tolerated defect. The proposal
  was `(3 − 1) × $15 = $30`. The Supplier disputed it ("Bracket #101 shows a weld seam, not
  a crack"). The Reviewer rejected `fnd_07` (#101) and `fnd_08` (#187, needs review), and
  the resolution was `(2 − 1) × $15 = $15` → `$3,735`. `fnd_09` is excluded as present at
  dispatch.

## Agreement terms (rules DSL)

`AgreementTerms` in `backend/app/terms.py`. This is the PS-1042 seed from `backend/app/seed.py`:

```json
{
  "itemDescription": "Machined metal component",
  "quantity": 100,
  "unitPrice": 100,
  "invoiceAmount": 10000,
  "evidenceRequirements": {
    "minDispatchPhotos": 4,
    "minReceiptPhotos": 4,
    "inspectionWindowHours": 48
  },
  "acceptance": {
    "defectTypes": ["bend", "crack", "deep_scratch", "discoloration"],
    "minConfidence": 0.85,
    "defectToleranceUnits": 0
  },
  "compensation": {
    "type": "per_defective_unit",
    "amountPerUnit": 100,
    "maxCredit": 10000
  }
}
```

Validation (any failure → `422`):

- All money fields are `> 0`, with at most 2 decimal places and 12 digits.
- `invoiceAmount` must equal `quantity × unitPrice` exactly (Decimal math).
- `compensation.maxCredit` must be `≤ invoiceAmount`.
- `quantity`, `minDispatchPhotos`, `minReceiptPhotos` and `inspectionWindowHours` must be `≥ 1`.
- `minConfidence` is in `(0, 1]`. It is a probability, not money, so it is a float.
- `defectTypes` must be non-empty, unique, lowercase snake_case slugs.
- `0 ≤ defectToleranceUnits ≤ quantity`.
- Unknown fields are rejected at every level, and terms are immutable once parsed.

Meanings:

- `defectToleranceUnits` is the number of confirmed defective units the buyer accepts
  without credit.
- `inspectionWindowHours` is counted from receipt.
- `compensation.type` is a discriminator: `"per_defective_unit"` is the only rule type
  today, and new rule types get their own `type` value. For PS-1042, the adjustment is
  `min(max(0, confirmed − tolerance) × amountPerUnit, maxCredit)` = `3 × $100` = `$300`.
  See Settlement engine below.

## Findings

`Finding` in `backend/app/findings.py`:

```json
{
  "id": "fnd_04",
  "unitRef": "Component #063",
  "defectType": "discoloration",
  "confidence": 0.52,
  "evidenceIds": ["ev_08"],
  "description": "Possible discoloration",
  "presentInDispatch": false,
  "reviewOverride": null,
  "reviewedBy": null,
  "reviewedAt": null
}
```

- `confidence` is the AI's confidence in `[0, 1]`, as a float.
- `defectType` uses the same slug format as `acceptance.defectTypes`.
- `evidenceIds` must be non-empty.
- `presentInDispatch` is true when the defect is already visible in the dispatch photos.
- `reviewOverride` is `"confirmed" | "rejected" | null`. It, `reviewedBy` and `reviewedAt`
  are set together or not at all. `reviewedBy` must be `"Reviewer"`, and `reviewedAt` is an
  ISO 8601 timestamp with a timezone.

## Settlement engine

`compute_adjustment(terms, findings)` in `backend/app/settlement.py` is a pure function. It
does no I/O, makes no AI calls, does not read the clock and uses only `Decimal` for money.
Each finding lands in exactly one list. The rules are checked in this order:

| # | Condition | List | `reason` |
|---|-----------|------|----------|
| 1 | `reviewOverride == "rejected"` | `excluded` | `review_rejected` |
| 2 | `reviewOverride == "confirmed"` | `counted` | `review_confirmed` |
| 3 | `defectType` not in `acceptance.defectTypes` | `excluded` | `defect_type_not_covered` |
| 4 | `presentInDispatch` | `excluded` | `present_in_dispatch` |
| 5 | `confidence < acceptance.minConfidence` | `needsReview` | `below_confidence` |
| 6 | otherwise | `counted` | `meets_threshold` |

- A rejection always wins. A Reviewer's confirmation counts a finding even if rules 3–5
  would have kept it out.
- Rules 3 and 4 come before rule 5. A low-confidence finding of an uncovered type, or one
  already present at dispatch, is excluded rather than sent to review. So `needsReview` only
  holds findings that would count if a Reviewer confirmed them.
- Needs-review findings are never counted.
- Credit is per defective **unit**. Several counted findings with the same `unitRef` count
  once, so `confirmedDefects` is the number of distinct units in `counted`.
- `credit = min(max(0, confirmedDefects − defectToleranceUnits) × amountPerUnit, maxCredit)`
- `settlementAmount = invoiceAmount − credit`
- `amountIfReviewedConfirmed` uses the same formula, counting the units in both `counted`
  and `needsReview`. It equals `credit` when `needsReview` is empty.
- `status` is `"needs_review"` if `needsReview` is non-empty, otherwise `"ready"`.

**Needs-review findings do not block `Inspection → Proposed`.** The engine proposes the
credit from counted findings only, which is the lowest credit the evidence supports. The
pending findings and `amountIfReviewedConfirmed` are shown next to it, as the frontend does
today with $300 proposed and #063 flagged. `status` is a hint for the UI, not a gate.

`appliedRule.credit` takes one of these forms:

| Case | Example |
|------|---------|
| no tolerance | `3 × $100 = $300` |
| tolerance, some charged | `(3 − 1 tolerated) × $100 = $200` |
| tolerance covers all | `3 confirmed, 5 tolerated = $0` |
| cap hit (suffix) | `3 × $100 = $300, capped at $250` |

Amounts are written as `$9,700` for whole dollars and as `$99.99` otherwise.

## Endpoints and JSON shapes

### `GET /health` (implemented)

```json
{ "status": "ok", "db": "ok" }
```

### `GET /shipments` — shipment list (implemented)

Exactly the dashboard's fields. `events` is omitted from list items; the dashboard doesn't
read it.

```json
[
  {
    "id": "PS-1042",
    "title": "100 metal components",
    "buyer": "Northgate Assembly Ltd",
    "supplier": "Ferro Precision Works",
    "amount": 10000,
    "status": "Proposed"
  }
]
```

### `GET /shipments/{id}` — shipment detail (implemented)

A superset of `Shipment`. Fields not yet created are `null` (e.g. `adjustment` before
`Proposed`).

```json
{
  "id": "PS-1042",
  "title": "100 metal components",
  "buyer": "Northgate Assembly Ltd",
  "supplier": "Ferro Precision Works",
  "amount": 10000,
  "status": "Proposed",
  "disputeReason": null,

  "agreement": {
    "terms": { "...": "AgreementTerms, see below" },
    "buyerApproved": true,
    "supplierApproved": true,
    "termsHash": "<sha256>"
  },

  "evidence": [
    {
      "id": "ev_01",
      "kind": "dispatch",
      "url": "/evidence/ev_01/file",
      "sha256": "<sha256>",
      "uploadedBy": "Supplier",
      "at": "2026-10-11T08:05:00Z",
      "verified": true
    }
  ],

  "inspection": {
    "findings": [
      {
        "id": "fnd_01", "unitRef": "Component #017", "defectType": "bend", "confidence": 0.94,
        "evidenceIds": ["ev_05"], "description": "Bent flange", "presentInDispatch": false,
        "reviewOverride": null, "reviewedBy": null, "reviewedAt": null
      }
    ]
  },

  "adjustment": {
    "id": "adj_01",
    "computedAt": "2026-10-15T16:32:00Z",
    "confirmedDefects": 3,
    "credit": 300,
    "settlementAmount": 9700,
    "appliedRule": {
      "credit": "3 × $100 = $300",
      "settlement": "$10,000 − $300 = $9,700"
    },
    "counted": [
      { "findingId": "fnd_01", "unitRef": "Component #017", "reason": "meets_threshold", "detail": "94% confidence, at or above 85%" },
      { "findingId": "fnd_02", "unitRef": "Component #042", "reason": "meets_threshold", "detail": "91% confidence, at or above 85%" },
      { "findingId": "fnd_03", "unitRef": "Component #078", "reason": "meets_threshold", "detail": "88% confidence, at or above 85%" }
    ],
    "excluded": [],
    "needsReview": [
      { "findingId": "fnd_04", "unitRef": "Component #063", "reason": "below_confidence", "detail": "52% confidence is below the 85% threshold" }
    ],
    "amountIfReviewedConfirmed": 400,
    "assumptions": [
      "Only findings at ≥ 85% confidence count as confirmed, unless a Reviewer decides",
      "Covered defect types: bend, crack, deep_scratch, discoloration",
      "Defects already visible in dispatch photos are excluded",
      "No defect tolerance: every confirmed defective unit is credited",
      "Credit rule taken unchanged from the signed agreement: $100 per defective unit, capped at $10,000"
    ],
    "status": "needs_review",
    "buyerAcceptedAt": null,
    "supplierAcceptedAt": null
  },

  "actions": { "canAccept": true, "canDispute": true, "canReview": false, "canResolve": false },

  "events": [
    {
      "id": "evt_01",
      "seq": 1,
      "at": "2026-10-09T10:12:00Z",
      "actor": "Buyer",
      "type": "agreement.drafted",
      "text": "Agreement drafted: 100 components, $10,000",
      "hash": "<sha256>",
      "payloadHash": "<sha256>",
      "prevHash": null,
      "txHash": null,
      "chainStatus": "skipped"
    }
  ]
}
```

`adjustment` is the engine's `Adjustment` output (see Settlement engine), computed fresh
from the stored terms and findings on every request, plus the stored record's `id` and
`computedAt`. It is `null` before `Proposed`, and `inspection` is `null` before any findings
exist. `credit` replaces the old `amount`. `appliedRule`,
`counted`, `excluded`, `needsReview` and `status` replace the old `rule`, `creditPerDefect`
and `uncertainty`. The frontend builds its Uncertainty list from `needsReview` and
`amountIfReviewedConfirmed`.
`buyerAcceptedAt` and `supplierAcceptedAt` are the per-party acceptance of this adjustment
(ISO 8601, or `null` until that party accepts). The UI shows each party's state from them,
e.g. "Buyer accepted · waiting for Supplier".

`actions` is computed for the caller's `X-Demo-Role`:

| Field | True when |
|-------|-----------|
| `canAccept` | Caller is Buyer or Supplier, status is `Proposed`, and the caller hasn't accepted yet |
| `canDispute` | Same as `canAccept`. Accepting gives up the right to dispute |
| `canReview` | Caller is Reviewer and status is `Disputed` (may set `reviewOverride` on findings) |
| `canResolve` | `canReview`, and the recomputed `adjustment.needsReview` is empty |

So on the seeded PS-1042 (`Proposed`, nobody accepted yet), Buyer and Supplier both see
`canAccept: true, canDispute: true`. After the Buyer accepts, the Buyer sees both `false`
while the Supplier still sees both `true`.
`evidence[].kind` is `"dispatch" | "receipt"`; the UI's "Dispatch photos" / "Receipt photos"
headings map to these. `events[].txHash` is the Solana transaction signature, set only once the event is anchored
on-chain. `chainStatus` is `pending | confirmed | failed | skipped`, and is `skipped` for
everything until chain anchoring exists. `hash` is the event's `eventHash` and `prevHash` is
its `prevEventHash` (see Hashing). `id`, `seq`, `type`, `payloadHash`, `prevHash`, `txHash`
and `chainStatus` are additions to `AuditEvent`; the existing four fields are unchanged.

### `GET /shipments/{id}/audit` — audit trail with chain check (implemented)

The shipment's events, as in the detail response, plus `verify_chain`'s per-event result.
Only stored hashes are checked here; evidence files aren't re-hashed (that is
`POST .../audit/verify`).

```json
{
  "shipmentId": "PS-1042",
  "verified": true,
  "checked": 7,
  "events": [ { "id": "evt_01", "...": "same shape as detail events" } ],
  "checks": [
    {
      "id": "evt_01", "seq": 1,
      "storedHash": "<sha256>", "recomputedHash": "<sha256>",
      "payloadOk": true, "linkOk": true, "ok": true
    }
  ]
}
```

- `payloadOk` means `payloadHash` matches the stored payload.
- `linkOk` means `seq` follows on from the previous event, and `prevEventHash` is the
  previous event's stored `eventHash`.
- `ok` means both of those, and the recomputed event hash equals the stored one.

Editing an event's text, actor, time or payload fails that event. Deleting an event fails
the one after it. Rewriting an event together with its own hash still fails the next
event's link.

### `GET /evidence/{id}/file` — evidence file (implemented)

The raw stored bytes, with the uploaded content type (`image/jpeg` for the seed).
`sha256(body)` equals `evidence[].sha256`. No `X-Demo-Role` is needed. Unknown id or
missing file → `404`.

### `POST /shipments/{id}/audit/verify` — verify hashes (**Proposed**)

Recomputes every event hash and its chain link, and re-hashes every evidence file from
storage. Path is nested under the shipment rather than the PRD's `/audit/{id}/verify`, since
the UI verifies a whole shipment at once.

```json
{
  "shipmentId": "PS-1042",
  "verified": true,
  "checked": 15,
  "events": [
    { "id": "evt_01", "storedHash": "<sha256>", "recomputedHash": "<sha256>", "ok": true }
  ],
  "evidence": [
    { "id": "ev_01", "storedHash": "<sha256>", "recomputedHash": "<sha256>", "ok": true }
  ],
  "chain": { "available": false, "anchored": 0, "mismatches": [] },
  "verifiedAt": "2026-10-17T12:00:00Z"
}
```

- `verified` is `true` only if every event and evidence item has `ok: true`.
- `checked` = `events.length + evidence.length`. The button label becomes
  `"${checked} hashes verified"`, or a failure state when `verified` is `false`.
- `chain.available: false` means the chain was unreachable. Verification still succeeds on
  local hashes alone (PRD §9: the app must work without the blockchain).

## Hashing (implemented: `backend/app/hashing.py`, `backend/app/audit.py`)

```
canonical_json(x) = json.dumps(x, sort_keys=True, separators=(",", ":"),
                               ensure_ascii=False, allow_nan=False).encode("utf-8")
```

`x` is a model's `model_dump(mode="json", by_alias=True)`: camelCase keys, and money as JSON
numbers via `Money` (`10000`, `33.33`). A raw `Decimal`, `NaN` or `datetime` raises an error
rather than being hashed. This is the definition in `backend/CHAIN_ALIGNMENT.md` §4, so a
hash's 32 raw bytes are what the Solana program takes as `[u8; 32]`. In JSON and in the
database a hash is 64 lowercase hex characters.

```
termsHash     = sha256(canonical_json(terms))
payloadHash   = sha256(canonical_json(event.payload))
eventHash     = sha256(canonical_json({
  "shipmentId", "seq", "at", "actor", "type", "text", "payloadHash", "prevEventHash"
}))
```

`at` is ISO 8601 UTC with a `Z` suffix. `prevEventHash` is the previous event's `eventHash`,
or `null` for `seq` 1. It links each event to the one before it, so deleting or reordering
events is detectable as well as editing them. Payloads carry the hashes of what the event
is about, e.g. `termsHash`, each evidence file's `sha256`, `findingsHash` (of the findings
list) and `adjustmentHash` (of the engine's `Adjustment`).

For the chain, each shipment also has a stable `chainUuid = uuid5(namespace, id)`, e.g.
`PS-1042` → `867aec08-fe1b-5d73-8f38-b2fb1e862ae8`. Its 16 bytes are the program's shipment
PDA seed. It is not exposed in the API yet.
`evidence.sha256` is the SHA-256 of the raw uploaded bytes. As the PRD says, a matching
hash shows the bytes are unchanged. It does not prove when or where a photo was taken.

## Errors

FastAPI's default shape, `{ "detail": "<message>" }`:

| Code | When |
|------|------|
| 400 | Missing or invalid `X-Demo-Role`; dispute submitted without a reason |
| 403 | Role not allowed to perform this transition |
| 404 | Unknown shipment id |
| 409 | Transition not allowed from the current status; or allowed but its guard isn't met (other party hasn't accepted, caller already accepted and tries to dispute, `needsReview` not empty on resolve, findings reviewed outside `Disputed`) |
| 422 | Request body validation failure (Pydantic) |
