

ProofSettle — Product Requirements Document (PRD)

HackGB 2026 | Industrial / FinTech | 24–48 Hour Hackathon MVP

Product tagline: Payments backed by agreed evidence.

1\. Executive Summary

ProofSettle is a contract-aware B2B settlement platform that connects shipment inspection evidence to pre-agreed damage and acceptance rules. It helps buyers and suppliers resolve delivery discrepancies with less manual back-and-forth.

When goods arrive damaged or incomplete, buyers and suppliers may disagree about the shipment's condition, the applicable contract terms, and the amount that should be paid. Evidence is often scattered across photographs, invoices, purchase orders, and emails.

ProofSettle creates a shared transaction record before shipment, analyzes evidence at delivery, applies agreed acceptance rules, and generates a proposed financial adjustment. Both parties can approve or dispute the result.

Core innovation: Connecting three elements that are often handled separately:

What the parties agreed to before shipping.

What the shipment evidence indicates at delivery.

What financial adjustment the parties should consider.

Target customers: Small and midsize manufacturers, industrial distributors, and B2B suppliers that regularly exchange physical goods.

MVP objective: Demonstrate one complete transaction, from agreement creation to evidence-backed settlement, including a disputed case.

2\. Problem Statement

Consider a manufacturer that purchases 100 metal components for $10,000.

The delivery arrives with several visibly damaged components. The buyer requests a credit, but the supplier questions whether the damage occurred during transit and whether the proposed deduction follows the agreement.

Resolving this situation may require:

Searching for the original purchase order and acceptance terms.

Exchanging photographs and emails.

Manually calculating a credit.

Waiting for the supplier to respond.

Maintaining a consistent record of the final decision.

The problem is not simply detecting damage. It is converting evidence and agreed rules into a decision both parties can review and audit.

3\. Product Goals and Non-Goals

3.1 Product Goals

Create structured agreements with explicit acceptance and compensation rules.

Capture dispatch and delivery evidence for the same shipment.

Use AI to identify visible damage and extract relevant information from supporting documents.

Generate an explainable financial adjustment using deterministic contract rules.

Allow both parties to accept or dispute the proposal, with a Reviewer resolving disputes.

Record important events and evidence hashes in a tamper-evident audit trail.

3.2 Non-Goals

The hackathon MVP will not include:

Real-money escrow or payment processing.

A production-grade damage-detection model trained from scratch.

Automatic legal liability determinations.

Integrations with every ERP, freight carrier, or accounting system.

A fully decentralized dispute-resolution protocol.

4\. Target Users

4.1 Buyer / Procurement Manager

Wants to document the condition of received goods, enforce agreed acceptance rules, and request the correct credit without lengthy email exchanges.

4.2 Supplier / Seller

Wants access to the same evidence, protection against unsupported deductions, and a transparent way to approve or challenge adjustments.

4.3 Finance / Operations Reviewer

Wants a clear record of the original agreement, proposed adjustment, approvals, and final settlement status.

5\. Product Workflow

Step 1: Create the Agreement

The buyer and supplier establish the transaction terms, including:

Purchase order and invoice value.

Shipment quantity and item details.

Acceptable damage thresholds.

Required evidence.

Compensation formula.

Approval requirements.

Both parties approve the terms before shipment.

Step 2: Register Shipment Condition

The supplier uploads dispatch photographs and records shipment details. ProofSettle stores timestamps and cryptographic hashes of the original evidence.

Step 3: Inspect the Delivery

The buyer uploads receipt photographs. Computer vision identifies potential damage and returns structured findings with confidence scores and supporting evidence.

Document extraction may be used to read quantities, invoice fields, and other relevant information.

Step 4: Calculate the Proposed Adjustment

A deterministic rules engine compares the inspection findings with the approved agreement. It calculates a proposed adjustment and explains which rules were applied.

Insufficient or ambiguous evidence is flagged for human review.

Step 5: Approve or Dispute

The buyer and the supplier each review the case and accept or dispute the proposed adjustment.

The proposal is accepted only once both parties have accepted it, which produces a final decision record. Either party may dispute it instead, giving a reason.

A disputed proposal goes to a Reviewer, who is neither the buyer nor the supplier. The Reviewer confirms or rejects individual findings, and the rules engine recomputes the adjustment from the reviewed findings. The case is resolved with that recomputed amount; the Reviewer never enters an amount.

6\. Functional Requirements

ID

Requirement

Priority

FR-01

Create shipment and contract records

Must-have

FR-02

Define acceptance thresholds and adjustment formulas

Must-have

FR-03

Upload dispatch and delivery images

Must-have

FR-04

Run AI-assisted damage analysis

Must-have

FR-05

Calculate explainable proposed adjustments

Must-have

FR-06

Provide buyer and supplier views of the same case

Must-have

FR-07

Allow acceptance or dispute of a proposal

Must-have

FR-08

Create a tamper-evident audit record

Must-have

FR-09

Verify recorded evidence hashes

Must-have

FR-10

Parse arbitrary invoices and purchase orders

Stretch

FR-11

Integrate a real escrow provider

Stretch

FR-12

Support multiple ERP systems

Future



Key Business Rule

AI must not independently decide the payment amount.

For example, suppose the approved agreement specifies a $100 credit per confirmed defective component. If three components meet the agreed criteria, the rules engine can propose a $300 adjustment, subject to the evidence requirements and approval workflow.

The system must display the applicable rule, supporting findings, assumptions, and uncertainty. The proposed adjustment is not an automatic determination of legal liability.

7\. MVP Features

The MVP will include the following capabilities:

Agreement Management

Create a shipment record.

Define acceptance and compensation rules.

Record approval by both parties.

Evidence Management

Upload dispatch and receipt photographs.

Store evidence references and cryptographic hashes.

Associate each file with the appropriate shipment.

AI Inspection

Analyze receipt photographs for visible damage.

Return structured findings and confidence scores.

Allow human reviewers to correct inaccurate findings.

Settlement Engine

Compare inspection findings against the agreement.

Calculate the proposed adjustment.

Explain the calculation.

Flag ambiguous evidence.

Dispute Management

Allow both buyer and supplier to accept or dispute proposals.

Accept a proposal only when both parties have accepted it.

Record the reason for a dispute.

Allow a Reviewer to resolve a dispute by confirming or rejecting findings, with the settlement engine recomputing the final adjustment.

Track the case status.

Audit Trail

Record important workflow events.

Verify evidence integrity.

Optionally anchor hashes and settlement decisions to a test blockchain.

8\. Technical Architecture

Frontend

React

TypeScript

Tailwind CSS

Responsibilities:

Agreement creation.

Evidence upload.

Inspection results.

Settlement review.

Buyer and supplier approval, dispute, and Reviewer resolution workflows.

Audit history.

Backend

Python

FastAPI

Pydantic

Responsibilities:

API endpoints.

Authentication and authorization.

Agreement and shipment management.

Evidence processing.

Settlement calculations.

Workflow state management.

Database

\- Supabase

Stores:

Users and organizations.

Shipments and agreements.

Evidence metadata.

Inspection findings.

Proposed adjustments.

Decisions and audit events.

AI Services

Pretrained vision model for potential damage detection.

OCR or a multimodal model for optional invoice extraction.

Structured outputs for downstream processing.

Blockchain

Solana program written with Anchor (branch feat/solana-blockchain).

Local Solana validator or devnet.

Responsibilities:

Register agreement hashes.

Record evidence hashes.

Record settlement decisions.

Emit verifiable events.

File Storage

\- Local storage or S3-compatible object storage.

Full documents and images remain off-chain. Their cryptographic hashes and necessary transaction references may be recorded on-chain.

9\. Blockchain Design

Blockchain is included only to provide a shared way to verify that important records have not silently changed.

The Solana program should support:

Registering an agreement hash.

Recording evidence hashes for a shipment.

Recording the parties' settlement decision.

Restricting state transitions to authorized participants.

Emitting events for verification.

Each shipment is stored in a program-derived account (PDA) seeded by the shipment's UUID, and each evidence hash in its own account. Hashes are stored as raw 32-byte SHA-256 digests and amounts as integer cents. Instructions are signed by the buyer, the supplier, or the backend acting as the program's authority.

Proposed Workflow States

Draft → Agreed → In Transit → Inspection → Proposed → Accepted

If a proposal is challenged:

Proposed → Disputed → Resolved

For the hackathon, the team will use a local Solana validator or devnet and simulated funds.

A hash proves that the submitted bytes match the recorded digest. It does not prove when a photograph was taken, whether the scene is authentic, or who caused the damage.

The application must remain functional if blockchain integration is temporarily unavailable.

10\. Core Data Model

Entity

Important Fields

Users

id, name, organization\_id, role

Shipments

id, buyer\_id, supplier\_id, invoice\_amount, status

Agreements

id, shipment\_id, terms\_json, terms\_hash, buyer\_approved, supplier\_approved

Evidence

id, shipment\_id, evidence\_type, file\_url, sha256, uploaded\_by, created\_at

Inspections

id, evidence\_id, findings\_json, confidence, review\_status

Adjustments

id, shipment\_id, rule\_id, proposed\_amount, explanation, status

Decisions

id, adjustment\_id, actor\_id, decision, reason, created\_at

Audit Events

id, shipment\_id, event\_type, payload\_hash, tx\_hash



In Supabase Postgres, these tables live in their own proofsettle schema. The public schema holds Lovable-generated tables with the same names and a different shape, which the backend never reads or writes. Local development and tests use SQLite.

Production implementations should add strict authorization, secure file access, validated schemas, and immutable event-handling practices.

11\. API Specification

Method

Endpoint

Purpose

GET

/health

Check API and database status

GET

/shipments

List shipments

GET

/shipments/{id}

Retrieve complete case

GET

/shipments/{id}/audit

Retrieve audit events with hash-chain check

GET

/evidence/{id}/file

Download an evidence file

POST

/shipments

Create shipment with agreement terms (buyer)

POST

/shipments/{id}/agreement/approve

Approve terms (buyer or supplier)

POST

/shipments/{id}/evidence

Upload dispatch (supplier) or receipt (buyer) photos

POST

/shipments/{id}/inspect

Analyze receipt photos and propose adjustment

POST

/shipments/{id}/accept

Accept proposal (buyer or supplier)

POST

/shipments/{id}/dispute

Dispute proposal with a reason (buyer or supplier)

POST

/findings/{id}/review

Confirm or reject a finding (Reviewer)

POST

/shipments/{id}/resolve

Resolve dispute with the recomputed adjustment (Reviewer)

POST

/shipments/{id}/audit/verify

Verify agreement, evidence and event hashes

POST

/dev/reset

Reload the demo data (dev mode only)



Request and response shapes are specified in backend/API\_CONTRACT.md.

The backend must validate the caller's organization and role before allowing approvals or decisions. It must calculate adjustments from stored agreement terms and validated findings rather than trusting amounts submitted by the frontend.

12\. Development Timeline

Hours 0–4: Foundation

Define the database schema.

Set up the FastAPI backend.

Create shipment records.

Build the agreement form.

Prepare a seeded demo transaction.

Hours 4–12: Core Workflow

Implement evidence uploads.

Integrate the vision model.

Return structured inspection findings.

Build the deterministic adjustment engine.

Hours 12–24: Product Experience

Complete buyer and supplier views.

Implement acceptance and dispute actions.

Add the event history.

Test the complete workflow.

Hours 24–36: Differentiation

Integrate the Solana program.

Record evidence hashes.

Verify record integrity.

Retain a working hash-based audit trail if blockchain integration fails.

Hours 36–48: Polish

Test ambiguous evidence and false detections.

Verify role restrictions.

Add loading and error states.

Prepare the presentation.

Rehearse the demo and record a backup.

For a 24-hour event, prioritize the working agreement-to-evidence-to-settlement workflow and hash verification. Invoice extraction, external escrow, and advanced computer vision are optional.

13\. Demo Plan

The demonstration should show one complete transaction and one disputed case.

Demo Scenario

A manufacturer ships 100 components worth $10,000.

The buyer reports that three components arrived damaged. The agreement specifies a $100 credit per confirmed defective component.

Demo Sequence

0:00–0:30 — Introduce the Problem

Explain the disagreement between buyer and supplier over the damaged shipment.

0:30–1:00 — Show the Agreement

Display the agreed compensation formula and both parties' approvals.

1:00–1:45 — Upload Evidence

Show the dispatch and receipt photographs, AI findings, and evidence limitations.

1:45–2:15 — Calculate the Adjustment

Demonstrate how the rules engine calculates a proposed $300 credit.

2:15–3:00 — Verify the Decision

Switch between the buyer's and supplier's views, demonstrate acceptance by both parties or a dispute resolved by a Reviewer, and show the audit trail and evidence-hash verification.

Required Demo Cases

Case A: Accepted Adjustment

Evidence meets the predefined criteria.

The adjustment is calculated correctly.

Both parties accept.

The case closes with an auditable record.

Case B: Disputed Adjustment

The buyer or supplier challenges the evidence or interpretation.

The system records the dispute and its reason.

A Reviewer confirms or rejects the disputed findings.

The rules engine recomputes the adjustment, and the case is resolved with an auditable record.

This demonstrates that ProofSettle supports accountable decisions rather than automatically trusting AI outputs.

14\. Success Metrics

The MVP will be considered successful if:

A seeded transaction can be processed end to end in under three minutes.

The adjustment engine returns the expected result for every predefined test case.

Buyer and supplier can access the same agreement and evidence record.

Modifying an evidence file causes its hash verification to fail.

Unauthorized users cannot approve agreements or resolve disputes.

Ambiguous or low-confidence findings are flagged for review.

These are prototype acceptance criteria, not claims about real-world accuracy or customer savings.

15\. Business Model

Initial Target Market

Small and midsize manufacturers and industrial distributors that regularly exchange physical goods and experience recurring receiving discrepancies.

Potential Revenue Models

Monthly subscription based on transaction volume.

Per-shipment or per-dispute fee.

Enterprise integrations with procurement and accounting systems.

Future Expansion

Potential future capabilities include supplier-quality claims management, purchase-order compliance, ERP integrations, and integrations with payment or escrow providers.

Before commercial launch, the team should validate dispute frequency, existing claims workflows, evidence-retention practices, and willingness to pay.

16\. Risks and Mitigation

Risk

Mitigation

AI falsely detects damage

Use confidence thresholds and human review

Photos cannot establish when damage occurred

Compare dispatch and receipt evidence; disclose uncertainty

Contract terms are ambiguous

Use explicit structured rules in the MVP

Supplier disputes a finding

Preserve the evidence and route the case for review

Blockchain integration takes too long

Keep the core workflow independent of chain availability

Demo becomes a collection of disconnected features

Build and rehearse one end-to-end transaction first



17\. Final Pitch

ProofSettle — Payments backed by agreed evidence.

Every damaged delivery can turn into a dispute over photographs, contracts, and money. ProofSettle connects the original agreement to shipment evidence and a transparent settlement proposal, helping buyers and suppliers resolve discrepancies using the same verifiable record.

We are not asking AI to decide who is legally at fault. We use AI to organize evidence, deterministic rules to calculate proposed adjustments, and a shared audit trail to make decisions easier to verify.

Our goal is simple: turn a disputed shipment into a clear, explainable, and auditable business decision.

18\. Final Product Strategy

ProofSettle should focus on one standout capability: agreement-aware settlement.

The contract terms, AI findings, financial calculation, dispute workflow, and audit trail must work together in one polished demonstration.

The team should avoid spending most of the hackathon building generic dashboards, a complex multi-agent system, or a real-money escrow mechanism. The strongest product story is that ProofSettle connects physical-world evidence to an agreed financial outcome while preserving both parties' ability to challenge the result.



