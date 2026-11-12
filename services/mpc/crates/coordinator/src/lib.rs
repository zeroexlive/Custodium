//! MPC coordinator (Phase 0 skeleton).
//!
//! The coordinator orchestrates keygen/signing sessions across the
//! independent signers. It holds **no key share** and can never sign
//! on its own; orchestration is not authorisation — each signer
//! independently evaluates signing policy (see `signing_policy`).
//!
//! Sessions refuse to start in production mode, and in every other
//! mode they fail closed with [`MpcError::NotImplemented`] until a
//! reviewed threshold implementation exists.

#![forbid(unsafe_code)]

use custodium_mpc_shared::{
    ensure_not_production, MpcError, MpcResult, RuntimeMode, SigningIntent,
};

/// Lifecycle state of a coordinator session.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SessionState {
    /// Created but never started; the only state this skeleton reaches.
    Created,
    /// Reserved for a future reviewed implementation.
    Running,
    /// Terminal: completed.
    Completed,
    /// Terminal: failed or aborted (the fail-closed resting state).
    Failed,
}

/// A key-generation session request.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct KeygenSession {
    /// Unique session identifier.
    pub session_id: String,
    /// Wallet the new key will belong to.
    pub wallet_id: String,
    /// Signature family: `"ecdsa_secp256k1"` or `"ed25519"`.
    pub scheme: String,
    /// Signing threshold (initial topology target: 2-of-3).
    pub threshold: u16,
    /// Total participants.
    pub total_participants: u16,
    /// Current lifecycle state.
    pub state: SessionState,
}

/// A signing session bound to one approved intent.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SigningSession {
    /// Unique session identifier.
    pub session_id: String,
    /// The exact intent the signers are asked to approve and sign.
    pub intent: SigningIntent,
    /// Current lifecycle state.
    pub state: SessionState,
}

impl KeygenSession {
    /// Start this keygen session.
    ///
    /// # Errors
    /// [`MpcError::ProductionSigningDisabled`] in production mode;
    /// [`MpcError::NotImplemented`] in every other mode.
    pub fn start(&mut self, mode: RuntimeMode) -> MpcResult<()> {
        ensure_not_production(mode)?;
        Err(MpcError::NotImplemented)
    }
}

impl SigningSession {
    /// Start this signing session.
    ///
    /// # Errors
    /// [`MpcError::ProductionSigningDisabled`] in production mode;
    /// [`MpcError::NotImplemented`] in every other mode.
    pub fn start(&mut self, mode: RuntimeMode) -> MpcResult<()> {
        ensure_not_production(mode)?;
        Err(MpcError::NotImplemented)
    }
}

/// Coordinator service facade matching `custodium.mpc.v1.Coordinator`
/// in `packages/proto/mpc/mpc.proto`.
#[derive(Debug, Default)]
pub struct Coordinator;

impl Coordinator {
    /// Create a keygen session (does not start it).
    #[must_use]
    pub fn create_keygen_session(&self, session: KeygenSession) -> KeygenSession {
        session
    }

    /// Create a signing session bound to `intent` (does not start it).
    #[must_use]
    pub fn create_signing_session(
        &self,
        session_id: impl Into<String>,
        intent: SigningIntent,
    ) -> SigningSession {
        SigningSession {
            session_id: session_id.into(),
            intent,
            state: SessionState::Created,
        }
    }
}
