//! ProofSettle: on-chain agreement, evidence and settlement record.
//!
//! What this program does (PRD section 9):
//!   * registers an agreement hash plus the numeric rule parameters
//!   * records SHA-256 hashes of dispatch / receipt evidence
//!   * records the proposed adjustment, both parties' decisions, and dispute resolution
//!   * restricts every state transition to the right party
//!   * emits an event for every change so the backend can build the audit trail
//!
//! What it deliberately does NOT do:
//!   * hold or move funds (real escrow is a non-goal for the MVP)
//!   * look at images or decide who is at fault. The AI only produces findings off-chain;
//!     every adjustment amount is computed HERE from the stored rule, never taken from a
//!     caller.
//!
//! The rules mirror the backend (backend/app/workflow.py, settlement.py, resolution.py);
//! backend/CHAIN_ALIGNMENT.md describes the mapping.
//!
//! Roles
//!   buyer      creates the shipment, approves terms, records receipt evidence,
//!              accepts or disputes the proposal
//!   supplier   approves terms, records dispatch evidence, marks the shipment in transit,
//!              accepts or disputes the proposal
//!   authority  ProofSettle backend (rules engine): proposes the adjustment
//!   reviewer   human reviewer: resolves disputes
//!
//! Workflow
//!   Draft -> Agreed -> InTransit -> Inspection -> Proposed -> Accepted (both parties)
//!                                                    \-> Disputed -> Resolved

use anchor_lang::prelude::*;

pub mod errors;
pub mod events;
pub mod state;

use errors::ProofSettleError;
use events::*;
use state::*;

// Placeholder (Anchor's template ID). Run `anchor keys sync` to replace it with your own.
declare_id!("FNp1BRdeBxrEqrW2Uyx2VicGtJqpMDGj2XUorkApuabm");

#[program]
pub mod proofsettle {
    use super::*;

    /// Buyer opens a shipment in `Draft` and registers the agreement.
    ///
    /// `params.terms_hash` must be the sha256 of the canonical terms JSON stored off-chain.
    /// The numeric parameters must match that JSON; each party checks this off-chain
    /// before approving.
    pub fn create_shipment(
        ctx: Context<CreateShipment>,
        shipment_id: [u8; 16],
        params: AgreementParams,
    ) -> Result<()> {
        let buyer = ctx.accounts.buyer.key();
        let shipment_key = ctx.accounts.shipment.key();
        let bump = ctx.bumps.shipment;

        let keys = [buyer, params.supplier, params.authority, params.reviewer];
        for (i, a) in keys.iter().enumerate() {
            for b in &keys[i + 1..] {
                require_keys_neq!(*a, *b, ProofSettleError::InvalidParties);
            }
        }
        require!(params.quantity > 0, ProofSettleError::InvalidQuantity);
        require!(params.invoice_amount_cents > 0, ProofSettleError::InvalidAmount);
        require!(params.credit_per_defect_cents > 0, ProofSettleError::InvalidAmount);
        require!(
            params.max_adjustment_cents > 0
                && params.max_adjustment_cents <= params.invoice_amount_cents,
            ProofSettleError::InvalidAmount
        );
        require!(
            params.defect_tolerance_units <= params.quantity,
            ProofSettleError::InvalidTolerance
        );
        require!(
            params.min_dispatch_evidence >= 1
                && params.min_receipt_evidence >= 1
                && u32::from(params.min_dispatch_evidence) + u32::from(params.min_receipt_evidence)
                    <= u32::from(MAX_EVIDENCE_PER_SHIPMENT),
            ProofSettleError::InvalidEvidenceRequirements
        );
        require!(params.terms_hash != [0u8; 32], ProofSettleError::ZeroHash);

        let now = Clock::get()?.unix_timestamp;

        ctx.accounts.shipment.set_inner(Shipment {
            shipment_id,
            buyer,
            supplier: params.supplier,
            authority: params.authority,
            reviewer: params.reviewer,
            terms_hash: params.terms_hash,
            invoice_amount_cents: params.invoice_amount_cents,
            quantity: params.quantity,
            credit_per_defect_cents: params.credit_per_defect_cents,
            max_adjustment_cents: params.max_adjustment_cents,
            defect_tolerance_units: params.defect_tolerance_units,
            min_dispatch_evidence: params.min_dispatch_evidence,
            min_receipt_evidence: params.min_receipt_evidence,
            buyer_approved: false,
            supplier_approved: false,
            status: ShipmentStatus::Draft,
            evidence_count: 0,
            dispatch_evidence_count: 0,
            receipt_evidence_count: 0,
            confirmed_defects: 0,
            findings_hash: [0u8; 32],
            explanation_hash: [0u8; 32],
            proposed_adjustment_cents: 0,
            buyer_accepted: false,
            supplier_accepted: false,
            dispute_reason_hash: [0u8; 32],
            resolution_hash: [0u8; 32],
            final_adjustment_cents: 0,
            audit_seq: 0,
            created_at: now,
            updated_at: now,
            bump,
        });

        let seq = next_seq(&mut ctx.accounts.shipment, now)?;
        emit!(ShipmentCreated {
            shipment: shipment_key,
            shipment_id,
            buyer,
            supplier: params.supplier,
            authority: params.authority,
            reviewer: params.reviewer,
            terms_hash: params.terms_hash,
            invoice_amount_cents: params.invoice_amount_cents,
            seq,
            timestamp: now,
        });
        Ok(())
    }

    /// Buyer and supplier each call this with the terms hash they reviewed.
    /// Once both have approved, the shipment moves to `Agreed`.
    pub fn approve_agreement(ctx: Context<PartyAction>, terms_hash: [u8; 32]) -> Result<()> {
        let now = Clock::get()?.unix_timestamp;
        let shipment_key = ctx.accounts.shipment.key();
        let approver = ctx.accounts.party.key();

        let (fully_approved, seq) = {
            let s = &mut ctx.accounts.shipment;
            require!(s.status == ShipmentStatus::Draft, ProofSettleError::InvalidStatus);
            require!(terms_hash == s.terms_hash, ProofSettleError::TermsHashMismatch);

            if approver == s.buyer {
                require!(!s.buyer_approved, ProofSettleError::AlreadyApproved);
                s.buyer_approved = true;
            } else if approver == s.supplier {
                require!(!s.supplier_approved, ProofSettleError::AlreadyApproved);
                s.supplier_approved = true;
            } else {
                return err!(ProofSettleError::Unauthorized);
            }

            let fully_approved = s.buyer_approved && s.supplier_approved;
            if fully_approved {
                s.status = ShipmentStatus::Agreed;
            }
            (fully_approved, next_seq(s, now)?)
        };

        emit!(AgreementApproved {
            shipment: shipment_key,
            approver,
            terms_hash,
            fully_approved,
            seq,
            timestamp: now,
        });
        Ok(())
    }

    /// Records the SHA-256 of one evidence file.
    ///   Dispatch: supplier only, while `Agreed`.
    ///   Receipt:  buyer only, while `InTransit` or `Inspection`. Reaching the agreed
    ///             minimum while `InTransit` moves the shipment to `Inspection`.
    pub fn record_evidence(
        ctx: Context<RecordEvidence>,
        kind: EvidenceKind,
        sha256: [u8; 32],
    ) -> Result<()> {
        require!(sha256 != [0u8; 32], ProofSettleError::ZeroHash);

        let now = Clock::get()?.unix_timestamp;
        let shipment_key = ctx.accounts.shipment.key();
        let evidence_key = ctx.accounts.evidence.key();
        let uploader = ctx.accounts.uploader.key();
        let evidence_bump = ctx.bumps.evidence;

        let (index, seq) = {
            let s = &mut ctx.accounts.shipment;
            require!(
                s.evidence_count < MAX_EVIDENCE_PER_SHIPMENT,
                ProofSettleError::EvidenceLimitReached
            );

            match kind {
                EvidenceKind::Dispatch => {
                    require_keys_eq!(uploader, s.supplier, ProofSettleError::Unauthorized);
                    require!(s.status == ShipmentStatus::Agreed, ProofSettleError::InvalidStatus);
                    s.dispatch_evidence_count += 1; // bounded by MAX_EVIDENCE_PER_SHIPMENT
                }
                EvidenceKind::Receipt => {
                    require_keys_eq!(uploader, s.buyer, ProofSettleError::Unauthorized);
                    require!(
                        matches!(s.status, ShipmentStatus::InTransit | ShipmentStatus::Inspection),
                        ProofSettleError::InvalidStatus
                    );
                    s.receipt_evidence_count += 1; // bounded by MAX_EVIDENCE_PER_SHIPMENT
                    if s.status == ShipmentStatus::InTransit
                        && s.receipt_evidence_count >= s.min_receipt_evidence
                    {
                        s.status = ShipmentStatus::Inspection;
                    }
                }
            }

            let index = s.evidence_count;
            s.evidence_count += 1;
            (index, next_seq(s, now)?)
        };

        ctx.accounts.evidence.set_inner(Evidence {
            shipment: shipment_key,
            index,
            kind,
            sha256,
            uploader,
            recorded_at: now,
            bump: evidence_bump,
        });

        emit!(EvidenceRecorded {
            shipment: shipment_key,
            evidence: evidence_key,
            index,
            kind,
            sha256,
            uploader,
            seq,
            timestamp: now,
        });
        Ok(())
    }

    /// Supplier confirms the goods are dispatched. Requires the agreed minimum of
    /// dispatch photo hashes.
    pub fn mark_in_transit(ctx: Context<SupplierAction>) -> Result<()> {
        let now = Clock::get()?.unix_timestamp;
        let shipment_key = ctx.accounts.shipment.key();

        let seq = {
            let s = &mut ctx.accounts.shipment;
            require!(s.status == ShipmentStatus::Agreed, ProofSettleError::InvalidStatus);
            require!(
                s.dispatch_evidence_count >= s.min_dispatch_evidence,
                ProofSettleError::MissingDispatchEvidence
            );
            s.status = ShipmentStatus::InTransit;
            next_seq(s, now)?
        };

        emit!(ShipmentDispatched { shipment: shipment_key, seq, timestamp: now });
        Ok(())
    }

    /// Authority (rules engine) submits the inspection result.
    ///
    /// The amount is NOT a parameter. It is computed from the approved rule:
    ///   proposed = min(max(0, confirmed_defects - tolerance) * credit_per_defect, max_adjustment)
    /// This is the on-chain version of "AI must not independently decide the payment amount".
    pub fn propose_adjustment(
        ctx: Context<AuthorityAction>,
        confirmed_defects: u32,
        findings_hash: [u8; 32],
        explanation_hash: [u8; 32],
    ) -> Result<()> {
        require!(
            findings_hash != [0u8; 32] && explanation_hash != [0u8; 32],
            ProofSettleError::ZeroHash
        );

        let now = Clock::get()?.unix_timestamp;
        let shipment_key = ctx.accounts.shipment.key();

        let (proposed, seq) = {
            let s = &mut ctx.accounts.shipment;
            require!(s.status == ShipmentStatus::Inspection, ProofSettleError::InvalidStatus);
            require!(
                s.receipt_evidence_count >= s.min_receipt_evidence,
                ProofSettleError::MissingReceiptEvidence
            );
            require!(confirmed_defects <= s.quantity, ProofSettleError::DefectsExceedQuantity);

            let proposed = s
                .adjustment_for(confirmed_defects)
                .ok_or_else(|| error!(ProofSettleError::MathOverflow))?;

            s.confirmed_defects = confirmed_defects;
            s.findings_hash = findings_hash;
            s.explanation_hash = explanation_hash;
            s.proposed_adjustment_cents = proposed;
            s.buyer_accepted = false;
            s.supplier_accepted = false;
            s.status = ShipmentStatus::Proposed;
            (proposed, next_seq(s, now)?)
        };

        emit!(AdjustmentProposed {
            shipment: shipment_key,
            confirmed_defects,
            proposed_adjustment_cents: proposed,
            findings_hash,
            explanation_hash,
            seq,
            timestamp: now,
        });
        Ok(())
    }

    /// Buyer or supplier accepts the proposal. It becomes `Accepted` only once both have.
    pub fn accept_adjustment(ctx: Context<PartyAction>) -> Result<()> {
        let now = Clock::get()?.unix_timestamp;
        let shipment_key = ctx.accounts.shipment.key();
        let accepter = ctx.accounts.party.key();

        let (fully_accepted, adjustment_cents, seq) = {
            let s = &mut ctx.accounts.shipment;
            require!(s.status == ShipmentStatus::Proposed, ProofSettleError::InvalidStatus);

            if accepter == s.buyer {
                require!(!s.buyer_accepted, ProofSettleError::AlreadyAccepted);
                s.buyer_accepted = true;
            } else if accepter == s.supplier {
                require!(!s.supplier_accepted, ProofSettleError::AlreadyAccepted);
                s.supplier_accepted = true;
            } else {
                return err!(ProofSettleError::Unauthorized);
            }

            let fully_accepted = s.buyer_accepted && s.supplier_accepted;
            if fully_accepted {
                s.final_adjustment_cents = s.proposed_adjustment_cents;
                s.status = ShipmentStatus::Accepted;
            }
            (fully_accepted, s.proposed_adjustment_cents, next_seq(s, now)?)
        };

        emit!(AdjustmentAccepted {
            shipment: shipment_key,
            accepter,
            fully_accepted,
            adjustment_cents,
            seq,
            timestamp: now,
        });
        Ok(())
    }

    /// Buyer or supplier disputes the proposal. A party that has already accepted can't.
    /// `reason_hash` commits to the written reason stored off-chain.
    pub fn dispute_adjustment(ctx: Context<PartyAction>, reason_hash: [u8; 32]) -> Result<()> {
        require!(reason_hash != [0u8; 32], ProofSettleError::ZeroHash);

        let now = Clock::get()?.unix_timestamp;
        let shipment_key = ctx.accounts.shipment.key();
        let disputer = ctx.accounts.party.key();

        let seq = {
            let s = &mut ctx.accounts.shipment;
            require!(s.status == ShipmentStatus::Proposed, ProofSettleError::InvalidStatus);
            if disputer == s.buyer {
                require!(!s.buyer_accepted, ProofSettleError::AlreadyAccepted);
            } else if disputer == s.supplier {
                require!(!s.supplier_accepted, ProofSettleError::AlreadyAccepted);
            } else {
                return err!(ProofSettleError::Unauthorized);
            }
            s.dispute_reason_hash = reason_hash;
            s.status = ShipmentStatus::Disputed;
            next_seq(s, now)?
        };

        emit!(AdjustmentDisputed {
            shipment: shipment_key,
            disputer,
            reason_hash,
            seq,
            timestamp: now,
        });
        Ok(())
    }

    /// Reviewer closes a dispute with the reviewed defect count. The final amount is the
    /// agreed rule applied to that count, exactly as for a proposal; it is never typed in.
    pub fn resolve_dispute(
        ctx: Context<ReviewerAction>,
        confirmed_defects: u32,
        resolution_hash: [u8; 32],
    ) -> Result<()> {
        require!(resolution_hash != [0u8; 32], ProofSettleError::ZeroHash);

        let now = Clock::get()?.unix_timestamp;
        let shipment_key = ctx.accounts.shipment.key();

        let (final_adjustment_cents, seq) = {
            let s = &mut ctx.accounts.shipment;
            require!(s.status == ShipmentStatus::Disputed, ProofSettleError::InvalidStatus);
            require!(confirmed_defects <= s.quantity, ProofSettleError::DefectsExceedQuantity);

            let final_adjustment_cents = s
                .adjustment_for(confirmed_defects)
                .ok_or_else(|| error!(ProofSettleError::MathOverflow))?;

            s.confirmed_defects = confirmed_defects;
            s.final_adjustment_cents = final_adjustment_cents;
            s.resolution_hash = resolution_hash;
            s.status = ShipmentStatus::Resolved;
            (final_adjustment_cents, next_seq(s, now)?)
        };

        emit!(DisputeResolved {
            shipment: shipment_key,
            confirmed_defects,
            final_adjustment_cents,
            resolution_hash,
            seq,
            timestamp: now,
        });
        Ok(())
    }

    /// Anyone can check a file hash against the on-chain record (FR-09).
    /// Emits `EvidenceVerified { matches }`; changes no state.
    pub fn verify_evidence(ctx: Context<VerifyEvidence>, expected_sha256: [u8; 32]) -> Result<()> {
        let ev = &ctx.accounts.evidence;
        emit!(EvidenceVerified {
            shipment: ctx.accounts.shipment.key(),
            evidence: ev.key(),
            index: ev.index,
            matches: ev.sha256 == expected_sha256,
            expected_sha256,
            recorded_sha256: ev.sha256,
            timestamp: Clock::get()?.unix_timestamp,
        });
        Ok(())
    }
}

/// Bumps the per-shipment event counter and returns the new value.
fn next_seq(shipment: &mut Shipment, now: i64) -> Result<u64> {
    shipment.audit_seq = shipment
        .audit_seq
        .checked_add(1)
        .ok_or_else(|| error!(ProofSettleError::MathOverflow))?;
    shipment.updated_at = now;
    Ok(shipment.audit_seq)
}

// ---------------------------------------------------------------------------
// Instruction arguments
// ---------------------------------------------------------------------------

#[derive(AnchorSerialize, AnchorDeserialize, Clone)]
pub struct AgreementParams {
    pub supplier: Pubkey,
    pub authority: Pubkey,
    pub reviewer: Pubkey,
    pub terms_hash: [u8; 32],
    pub invoice_amount_cents: u64,
    pub quantity: u32,
    pub credit_per_defect_cents: u64,
    pub max_adjustment_cents: u64,
    pub defect_tolerance_units: u32,
    pub min_dispatch_evidence: u16,
    pub min_receipt_evidence: u16,
}

// ---------------------------------------------------------------------------
// Account contexts
// ---------------------------------------------------------------------------

#[derive(Accounts)]
#[instruction(shipment_id: [u8; 16])]
pub struct CreateShipment<'info> {
    #[account(
        init,
        payer = buyer,
        space = 8 + Shipment::INIT_SPACE,
        seeds = [b"shipment", shipment_id.as_ref()],
        bump
    )]
    pub shipment: Account<'info, Shipment>,
    #[account(mut)]
    pub buyer: Signer<'info>,
    pub system_program: Program<'info, System>,
}

/// Actions either party may take: approve_agreement, accept_adjustment,
/// dispute_adjustment. The handler checks the signer is the buyer or the supplier.
#[derive(Accounts)]
pub struct PartyAction<'info> {
    #[account(
        mut,
        seeds = [b"shipment", shipment.shipment_id.as_ref()],
        bump = shipment.bump
    )]
    pub shipment: Account<'info, Shipment>,
    pub party: Signer<'info>,
}

#[derive(Accounts)]
pub struct RecordEvidence<'info> {
    #[account(
        mut,
        seeds = [b"shipment", shipment.shipment_id.as_ref()],
        bump = shipment.bump
    )]
    pub shipment: Account<'info, Shipment>,
    #[account(
        init,
        payer = uploader,
        space = 8 + Evidence::INIT_SPACE,
        seeds = [b"evidence", shipment.key().as_ref(), &shipment.evidence_count.to_le_bytes()],
        bump
    )]
    pub evidence: Account<'info, Evidence>,
    /// Supplier (dispatch) or buyer (receipt); checked in the handler.
    #[account(mut)]
    pub uploader: Signer<'info>,
    pub system_program: Program<'info, System>,
}

/// Actions only the supplier may take: mark_in_transit.
#[derive(Accounts)]
pub struct SupplierAction<'info> {
    #[account(
        mut,
        seeds = [b"shipment", shipment.shipment_id.as_ref()],
        bump = shipment.bump
    )]
    pub shipment: Account<'info, Shipment>,
    #[account(address = shipment.supplier @ ProofSettleError::Unauthorized)]
    pub supplier: Signer<'info>,
}

/// Actions only the authority (rules engine) may take: propose_adjustment.
#[derive(Accounts)]
pub struct AuthorityAction<'info> {
    #[account(
        mut,
        seeds = [b"shipment", shipment.shipment_id.as_ref()],
        bump = shipment.bump
    )]
    pub shipment: Account<'info, Shipment>,
    #[account(address = shipment.authority @ ProofSettleError::Unauthorized)]
    pub authority: Signer<'info>,
}

/// Actions only the reviewer may take: resolve_dispute.
#[derive(Accounts)]
pub struct ReviewerAction<'info> {
    #[account(
        mut,
        seeds = [b"shipment", shipment.shipment_id.as_ref()],
        bump = shipment.bump
    )]
    pub shipment: Account<'info, Shipment>,
    #[account(address = shipment.reviewer @ ProofSettleError::Unauthorized)]
    pub reviewer: Signer<'info>,
}

#[derive(Accounts)]
pub struct VerifyEvidence<'info> {
    #[account(
        seeds = [b"shipment", shipment.shipment_id.as_ref()],
        bump = shipment.bump
    )]
    pub shipment: Account<'info, Shipment>,
    #[account(has_one = shipment)]
    pub evidence: Account<'info, Evidence>,
}
