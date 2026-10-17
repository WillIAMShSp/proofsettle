use anchor_lang::prelude::*;

use crate::state::EvidenceKind;

// Every state-changing event carries `seq` (Shipment.audit_seq after the change) and the
// block timestamp. The backend stores the transaction signature in `audit_events.tx_hash`.

#[event]
pub struct ShipmentCreated {
    pub shipment: Pubkey,
    pub shipment_id: [u8; 16],
    pub buyer: Pubkey,
    pub supplier: Pubkey,
    pub authority: Pubkey,
    pub terms_hash: [u8; 32],
    pub invoice_amount_cents: u64,
    pub seq: u64,
    pub timestamp: i64,
}

#[event]
pub struct AgreementApproved {
    pub shipment: Pubkey,
    pub approver: Pubkey,
    pub terms_hash: [u8; 32],
    /// True once both buyer and supplier have approved (status becomes Agreed).
    pub fully_approved: bool,
    pub seq: u64,
    pub timestamp: i64,
}

#[event]
pub struct EvidenceRecorded {
    pub shipment: Pubkey,
    pub evidence: Pubkey,
    pub index: u16,
    pub kind: EvidenceKind,
    pub sha256: [u8; 32],
    pub uploader: Pubkey,
    pub seq: u64,
    pub timestamp: i64,
}

#[event]
pub struct ShipmentDispatched {
    pub shipment: Pubkey,
    pub seq: u64,
    pub timestamp: i64,
}

#[event]
pub struct AdjustmentProposed {
    pub shipment: Pubkey,
    pub confirmed_defects: u32,
    pub proposed_adjustment_cents: u64,
    pub findings_hash: [u8; 32],
    pub explanation_hash: [u8; 32],
    pub seq: u64,
    pub timestamp: i64,
}

#[event]
pub struct AdjustmentAccepted {
    pub shipment: Pubkey,
    pub final_adjustment_cents: u64,
    pub seq: u64,
    pub timestamp: i64,
}

#[event]
pub struct AdjustmentDisputed {
    pub shipment: Pubkey,
    pub reason_hash: [u8; 32],
    pub seq: u64,
    pub timestamp: i64,
}

#[event]
pub struct DisputeResolved {
    pub shipment: Pubkey,
    pub final_adjustment_cents: u64,
    pub resolution_hash: [u8; 32],
    pub seq: u64,
    pub timestamp: i64,
}

/// Read-only result of `verify_evidence`. Not an audit event (no `seq`).
#[event]
pub struct EvidenceVerified {
    pub shipment: Pubkey,
    pub evidence: Pubkey,
    pub index: u16,
    pub matches: bool,
    pub expected_sha256: [u8; 32],
    pub recorded_sha256: [u8; 32],
    pub timestamp: i64,
}
