use anchor_lang::prelude::*;

#[error_code]
pub enum ProofSettleError {
    #[msg("Signer is not authorized to perform this action")]
    Unauthorized,
    #[msg("Shipment is not in the status required for this action")]
    InvalidStatus,
    #[msg("Buyer, supplier, authority and reviewer must be four distinct keys")]
    InvalidParties,
    #[msg("Amount parameters are invalid")]
    InvalidAmount,
    #[msg("Quantity must be greater than zero")]
    InvalidQuantity,
    #[msg("A hash value must not be all zeros")]
    ZeroHash,
    #[msg("Terms hash does not match the registered agreement")]
    TermsHashMismatch,
    #[msg("This party has already approved the agreement")]
    AlreadyApproved,
    #[msg("Evidence limit reached for this shipment")]
    EvidenceLimitReached,
    #[msg("Not enough dispatch evidence recorded yet")]
    MissingDispatchEvidence,
    #[msg("Not enough receipt evidence recorded yet")]
    MissingReceiptEvidence,
    #[msg("Confirmed defects exceed the shipment quantity")]
    DefectsExceedQuantity,
    #[msg("Arithmetic overflow")]
    MathOverflow,
    #[msg("This party has already accepted the adjustment")]
    AlreadyAccepted,
    #[msg("Defect tolerance cannot exceed the shipment quantity")]
    InvalidTolerance,
    #[msg("Evidence minimums must be at least 1 and fit within the evidence limit")]
    InvalidEvidenceRequirements,
}
