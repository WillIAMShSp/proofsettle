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
/// PDA: ["shipment", shipment_id]  where shipment_id is the 16-byte UUID from Supabase.
#[account]
#[derive(InitSpace)]
pub struct Shipment {
    /// UUID bytes of the off-chain `shipments.id`.
    pub shipment_id: [u8; 16],

    // --- Parties -------------------------------------------------------
    pub buyer: Pubkey,
    pub supplier: Pubkey,
    /// ProofSettle backend (rules engine) or a designated human reviewer.
    /// May propose adjustments and resolve disputes. Cannot move funds (there are none).
    pub authority: Pubkey,

    // --- Agreement (terms_hash commits to the full terms_json off-chain) --
    pub terms_hash: [u8; 32],
    pub invoice_amount_cents: u64,
    pub quantity: u32,
    /// Deterministic rule: adjustment = min(defects * credit_per_defect, max_adjustment).
    pub credit_per_defect_cents: u64,
    pub max_adjustment_cents: u64,
    pub buyer_approved: bool,
    pub supplier_approved: bool,

    // --- Workflow ------------------------------------------------------
    pub status: ShipmentStatus,
    pub evidence_count: u16,
    pub dispatch_evidence_count: u16,
    pub receipt_evidence_count: u16,

    // --- Proposal ------------------------------------------------------
    pub confirmed_defects: u32,
    /// sha256 of the (human-reviewed) inspection findings JSON.
    pub findings_hash: [u8; 32],
    /// sha256 of the plain-English explanation shown to both parties.
    pub explanation_hash: [u8; 32],
    pub proposed_adjustment_cents: u64,

    // --- Dispute / outcome ---------------------------------------------
    pub dispute_reason_hash: [u8; 32],
    pub resolution_hash: [u8; 32],
    pub final_adjustment_cents: u64,

    // --- Bookkeeping ---------------------------------------------------
    /// Monotonic counter; every state-changing instruction emits an event carrying it,
    /// so the backend can detect missing events when rebuilding the audit trail.
    pub audit_seq: u64,
    pub created_at: i64,
    pub updated_at: i64,
    pub bump: u8,
}

/// One account per evidence file. Only the SHA-256 lives on-chain; the file stays
/// in Supabase Storage / S3.
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
