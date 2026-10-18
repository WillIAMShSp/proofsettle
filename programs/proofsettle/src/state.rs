use anchor_lang::prelude::*;

/// Hard cap on evidence records per shipment (keeps account counters tiny and bounded).
pub const MAX_EVIDENCE_PER_SHIPMENT: u16 = 64;

/// Workflow from the PRD:
///   Draft -> Agreed -> InTransit -> Inspection -> Proposed -> Accepted
///   Proposed -> Disputed -> Resolved
#[derive(AnchorSerialize, AnchorDeserialize, Clone, Copy, PartialEq, Eq, InitSpace)]
pub enum ShipmentStatus {
    Draft,
    Agreed,
    InTransit,
    Inspection,
    Proposed,
    Accepted,
    Disputed,
    Resolved,
}

#[derive(AnchorSerialize, AnchorDeserialize, Clone, Copy, PartialEq, Eq, InitSpace)]
pub enum EvidenceKind {
    /// Photos the supplier records before shipping.
    Dispatch,
    /// Photos the buyer records on receipt.
    Receipt,
}

/// One account per shipment. Holds the agreement, the workflow state and the
/// commitments (hashes) to everything that lives off-chain.
///
/// PDA: ["shipment", shipment_id]  where shipment_id is the backend's 16-byte
/// `chain_uuid` for the shipment (uuid5 of its id, e.g. "PS-1042").
#[account]
#[derive(InitSpace)]
pub struct Shipment {
    /// UUID bytes of the off-chain shipment (backend `shipments.chain_uuid`).
    pub shipment_id: [u8; 16],

    // --- Parties -------------------------------------------------------
    pub buyer: Pubkey,
    pub supplier: Pubkey,
    /// ProofSettle backend (rules engine). Only signer of `propose_adjustment`.
    /// Cannot move funds (there are none).
    pub authority: Pubkey,
    /// Human reviewer. Only signer of `resolve_dispute`.
    pub reviewer: Pubkey,

    // --- Agreement (terms_hash commits to the full terms JSON off-chain) --
    pub terms_hash: [u8; 32],
    pub invoice_amount_cents: u64,
    pub quantity: u32,
    /// Deterministic rule, the same as the backend's settlement engine:
    ///   adjustment = min(max(0, defects - defect_tolerance_units) * credit_per_defect,
    ///                    max_adjustment)
    pub credit_per_defect_cents: u64,
    pub max_adjustment_cents: u64,
    pub defect_tolerance_units: u32,
    /// Photos needed before the shipment can move on (Agreed -> InTransit,
    /// InTransit -> Inspection).
    pub min_dispatch_evidence: u16,
    pub min_receipt_evidence: u16,
    pub buyer_approved: bool,
    pub supplier_approved: bool,

    // --- Workflow ------------------------------------------------------
    pub status: ShipmentStatus,
    pub evidence_count: u16,
    pub dispatch_evidence_count: u16,
    pub receipt_evidence_count: u16,

    // --- Proposal ------------------------------------------------------
    /// Confirmed defective units behind the current amount: the proposal's count,
    /// replaced by the reviewed count when a dispute is resolved.
    pub confirmed_defects: u32,
    /// sha256 of the inspection findings JSON.
    pub findings_hash: [u8; 32],
    /// sha256 of the settlement engine's full adjustment JSON, shown to both parties.
    pub explanation_hash: [u8; 32],
    pub proposed_adjustment_cents: u64,
    /// Both parties must accept the proposal before it becomes `Accepted`.
    pub buyer_accepted: bool,
    pub supplier_accepted: bool,

    // --- Dispute / outcome ---------------------------------------------
    pub dispute_reason_hash: [u8; 32],
    pub resolution_hash: [u8; 32],
    pub final_adjustment_cents: u64,

    // --- Bookkeeping ---------------------------------------------------
    /// Monotonic counter; every state-changing instruction bumps it by exactly one
    /// and emits an event carrying it, so the backend can detect missing events and
    /// tell how far its history has been mirrored on-chain.
    pub audit_seq: u64,
    pub created_at: i64,
    pub updated_at: i64,
    pub bump: u8,
}

impl Shipment {
    /// The agreed rule applied to a confirmed defect count, in cents.
    pub fn adjustment_for(&self, confirmed_defects: u32) -> Option<u64> {
        let credited = confirmed_defects.saturating_sub(self.defect_tolerance_units);
        u64::from(credited)
            .checked_mul(self.credit_per_defect_cents)
            .map(|raw| raw.min(self.max_adjustment_cents))
    }
}

/// One account per evidence file. Only the SHA-256 lives on-chain; the file stays
/// in the backend's evidence storage.
///
/// PDA: ["evidence", shipment, index_le_u16]
#[account]
#[derive(InitSpace)]
pub struct Evidence {
    pub shipment: Pubkey,
    pub index: u16,
    pub kind: EvidenceKind,
    pub sha256: [u8; 32],
    pub uploader: Pubkey,
    pub recorded_at: i64,
    pub bump: u8,
}
