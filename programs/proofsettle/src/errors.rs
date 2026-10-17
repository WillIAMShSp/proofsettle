use anchor_lang::prelude::*;

#[error_code]
pub enum ProofSettleError {
    #[msg("Signer is not authorized to perform this action")]
    Unauthorized,
    #[msg("Shipment is not in the status required for this action")]
    InvalidStatus,
    #[msg("Buyer, supplier and authority must be three distinct keys")]
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
    #[msg("At least one dispatch evidence record is required")]
    MissingDispatchEvidence,
    #[msg("At least one receipt evidence record is required")]
    MissingReceiptEvidence,
    #[msg("Confirmed defects exceed the shipment quantity")]
    DefectsExceedQuantity,
    #[msg("Arithmetic overflow")]
    MathOverflow,
}
