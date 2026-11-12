//! MPC signer participant (Phase 0 skeleton).
//!
//! Each signer runs in its own security domain, custodies exactly its
//! own share (referenced here only by an opaque [`ShareHandle`]), and
//! independently evaluates signing policy before participating. A
//! signer must refuse sessions in production mode while production
//! signing is disabled, and must never accept a signing request from
//! the Django API directly — requests arrive via the coordinator with
//! a bound [`SigningIntent`].
//!
//! No share material, and no code that could reconstruct a complete
//! private key, exists in this crate.

#![forbid(unsafe_code)]

use custodium_mpc_shared::{
    ensure_not_production, MpcError, MpcResult, RuntimeMode, ShareHandle, SigningIntent,
};
use custodium_mpc_signing_policy::{evaluate, SigningPolicy};

/// Identity and custody record of one signer participant.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SignerNode {
    /// Unique signer identifier (e.g. `"signer-1"`).
    pub signer_id: String,
    /// Security domain this signer runs in (e.g. host/account label).
    /// Distinct signers must have distinct domains.
    pub security_domain: String,
    /// Handles of the shares this signer custodies. Handles only —
    /// never the shares themselves.
    pub share_handles: Vec<ShareHandle>,
}

/// A request for this signer to join a signing session.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SigningParticipation {
    /// Session identifier assigned by the coordinator.
    pub session_id: String,
    /// The bound intent to independently verify.
    pub intent: SigningIntent,
}

impl SignerNode {
    /// Participate in distributed key generation.
    ///
    /// # Errors
    /// [`MpcError::ProductionSigningDisabled`] in production mode;
    /// [`MpcError::NotImplemented`] in every other mode.
    pub fn participate_keygen(&self, mode: RuntimeMode) -> MpcResult<ShareHandle> {
        ensure_not_production(mode)?;
        Err(MpcError::NotImplemented)
    }

    /// Participate in a signing session, after independent policy
    /// evaluation of the bound intent.
    ///
    /// # Errors
    /// [`MpcError::ProductionSigningDisabled`] in production mode;
    /// the `signing_policy` errors if the intent fails policy; and
    /// [`MpcError::NotImplemented`] for an otherwise acceptable intent,
    /// because no threshold implementation exists yet.
    pub fn participate_signing(
        &self,
        mode: RuntimeMode,
        participation: &SigningParticipation,
        policy: &SigningPolicy,
        now_unix: i64,
    ) -> MpcResult<()> {
        ensure_not_production(mode)?;
        evaluate(&participation.intent, policy, now_unix)?;
        Err(MpcError::NotImplemented)
    }
}
