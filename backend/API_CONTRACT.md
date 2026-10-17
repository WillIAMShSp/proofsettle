# ProofSettle API Contract (draft v0)

What the FastAPI backend must return so the existing frontend (`src/lib/store.tsx`,
`src/routes/dashboard.tsx`, `src/routes/shipments.$id.tsx`) can drop its mock data.
Sections marked **Proposed** are not implemented yet and are open for review.

## Conventions

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
  (mirrors the fake login). The backend validates role on every write. `Reviewer` is a
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
| `Proposed`   | `Accepted`   | Supplier                                 |
| `Proposed`   | `Disputed`   | Supplier, reason required                |
| `Disputed`   | `Resolved`   | Reviewer only                            |

`Accepted` and `Resolved` are terminal. Any other transition is rejected with `409`. A
role outside the "Who may trigger" column gets `403`. For example, Buyer or Supplier
resolving a dispute gets `403`, because neither party may resolve its own dispute. There is
no `Disputed → Proposed` path: a disputed proposal cannot be revised and re-proposed, and
the only way out of `Disputed` is a Reviewer moving it to `Resolved`.
The frontend's Supplier-only Accept/Dispute buttons and its "reason required" check match
this table, but the backend enforces both.

## Hard-coded values in `shipments.$id.tsx` that must come from the API

| Line | Constant / literal | Current value | Moves to |
|------|--------------------|---------------|----------|
| 20 | `STEPS` | the first 6 statuses | **Stays client-side.** Pure presentation, derived from `STATUSES`. |
| 50, 69 | stepper slot 5 shows `Disputed`/`Resolved` | logic | Stays client-side. |
| 21 | `CREDIT` | `100` | `agreement.creditPerDefect` |
| 22–27 | `findings` | 4 items (see below) | `inspection.findings` |
| 23–26 | `confirmed` flags | hand-set booleans | `finding.confirmed`, computed server-side as `confidence >= agreement.confidenceThreshold` unless a human reviewer overrides it |
| 145 | "≥ 85% confidence" | `0.85` | `agreement.confidenceThreshold` |
| 48 | `defects` | `findings.filter(confirmed).length` = 3 | `adjustment.confirmedDefects` |
| 49 | `adj` | `defects * CREDIT` = 300 | `adjustment.amount` |
| 141 | settlement | `s.amount - adj` = 9,700 | `adjustment.settlementAmount` |
| 147 | "would rise to `adj + CREDIT`" | 400 | `adjustment.amountIfReviewedConfirmed` |
| 87 | Goods | `"100 machined metal components"` (differs from `title` "100 metal components") | `agreement.goods` |
| 92–94 | approval badges | both always "approved" | `agreement.buyerApproved`, `agreement.supplierApproved` |
| 99, 5–6 | evidence images | `dispatch.jpg` / `receipt.jpg` assets, 4 each | `evidence[].url`, grouped by `evidence[].kind` |
| 103 | photos per group | `[0, 1, 2, 3]` | `evidence.length` per kind |
| 107 | evidence hash | `hashOf(label + n)` (fake) | `evidence[].sha256` |
| 108 | "Verified" check | always shown | `evidence[].verified` (from the last verify run; `null` = never checked) |
| 145 | Assumptions list | 3 strings | `adjustment.assumptions` |
| 147 | Uncertainty list | 2 strings, `#063` hard-coded | `adjustment.uncertainty` |
| 152 | decision shown when `Accepted`/`Disputed` | status check | `status`, plus `actions` (below) |
| 157 | `role === "Supplier"` to show buttons | client role check | `actions.canAccept`, `actions.canDispute` |
| 52 | event `at: "Just now"` | literal | server timestamp |
| 52 | event `actor: role ?? "User"` | client value | server, from the authenticated role |
| 52 | event `hash: hashOf(text)` | client hash | server SHA-256 (see Hashing) |
| 164, 170 | event text `"Supplier accepted $300 adjustment"` etc. | client-built | server-built |
| 181 | verify button | `setTimeout(900)` then always OK | `POST /shipments/{id}/audit/verify` |
| 182 | `"${events.length} hashes verified"` | event count | `verify.checked` / `verify.verified` |

Static copy (the "AI never decides the payment amount" banner, the "AI cannot prove when or
where" note, page `head` meta) stays in the frontend.

Current mock findings, which become the seeded inspection for `PS-1042`:

| item | issue | confidence | confirmed |
|------|-------|-----------:|-----------|
| Component #017 | Bent flange | 0.94 | true |
| Component #042 | Surface crack near bore | 0.91 | true |
| Component #078 | Deep scratch on mating face | 0.88 | true |
| Component #063 | Possible discoloration | 0.52 | false (needs review) |

Seed data from `store.tsx` to replicate: `PS-1042` (Proposed, 7 events), `PS-1038`
(In Transit, 40 hydraulic valves, $6,400, Kestrel Fluid Systems), `PS-1031` (Resolved,
250 steel brackets, $3,750). All buyers are Northgate Assembly Ltd.

## Endpoints and JSON shapes

### `GET /health` (implemented)

```json
{ "status": "ok", "db": "ok" }
```

### `GET /shipments` — shipment list (**Proposed**)

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

### `GET /shipments/{id}` — shipment detail (**Proposed**)

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
    "goods": "100 machined metal components",
    "quantity": 100,
    "creditPerDefect": 100,
    "confidenceThreshold": 0.85,
    "buyerApproved": true,
    "supplierApproved": true,
    "termsHash": "<sha256>"
  },

  "evidence": [
    {
      "id": "ev_01",
      "kind": "dispatch",
      "url": "/files/ev_01.jpg",
      "sha256": "<sha256>",
      "uploadedBy": "Supplier",
      "at": "2026-10-11T08:05:00Z",
      "verified": true
    }
  ],

  "inspection": {
    "findings": [
      { "item": "Component #017", "issue": "Bent flange", "confidence": 0.94, "confirmed": true, "needsReview": false },
      { "item": "Component #063", "issue": "Possible discoloration", "confidence": 0.52, "confirmed": false, "needsReview": true }
    ]
  },

  "adjustment": {
    "id": "adj_01",
    "rule": "creditPerConfirmedDefect",
    "confirmedDefects": 3,
    "creditPerDefect": 100,
    "amount": 300,
    "settlementAmount": 9700,
    "amountIfReviewedConfirmed": 400,
    "assumptions": [
      "Only findings at ≥ 85% confidence count as confirmed",
      "Dispatch photos show all 100 components intact",
      "Credit rule taken unchanged from the signed agreement"
    ],
    "uncertainty": [
      "1 item (#063) needs human review, excluded from total",
      "If confirmed, adjustment would rise to $400"
    ]
  },

  "actions": { "canAccept": true, "canDispute": true, "canResolve": false },

  "events": [
    {
      "id": "evt_01",
      "at": "2026-10-09T10:12:00Z",
      "actor": "Buyer",
      "text": "Agreement drafted: 100 components, $10,000",
      "hash": "<sha256>",
      "prevHash": null,
      "txHash": null
    }
  ]
}
```

`actions.canResolve` is true only for a Reviewer on a `Disputed` shipment.
`evidence[].kind` is `"dispatch" | "receipt"`; the UI's "Dispatch photos" / "Receipt photos"
headings map to these. `actions` is computed for the caller's `X-Demo-Role` from the
transition table. `events[].txHash` is set only when the event was anchored on-chain.
`id`, `prevHash` and `txHash` are additions to `AuditEvent`; the existing four fields are
unchanged.

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

## Hashing (**Proposed**)

```
event.hash = sha256(canonical_json({
  "shipmentId", "seq", "at", "actor", "type", "text", "prevHash"
}))
```

`canonical_json` means sorted keys, no whitespace, UTF-8. `prevHash` links each event to the
one before it, so deleting or reordering events is detectable as well as editing them.
`evidence.sha256` is the SHA-256 of the raw uploaded bytes. As the PRD says, a matching
hash shows the bytes are unchanged. It does not prove when or where a photo was taken.

## Errors

FastAPI's default shape, `{ "detail": "<message>" }`:

| Code | When |
|------|------|
| 400 | Missing or invalid `X-Demo-Role`; dispute submitted without a reason |
| 403 | Role not allowed to perform this transition |
| 404 | Unknown shipment id |
| 409 | Transition not allowed from the current status |
| 422 | Request body validation failure (Pydantic) |
