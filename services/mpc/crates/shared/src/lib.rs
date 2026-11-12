//! Shared types for the Custodium MPC workspace (Phase 0 skeleton).
//!
//! This crate deliberately contains **no secret material**. Key shares are
//! referenced only through the opaque [`ShareHandle`] identifier; there is
//! no type in this workspace that can hold a raw private key or a raw
//! private share.

#![forbid(unsafe_code)]

use std::fmt;

/// Production signing is compile-time disabled in this skeleton.
///
/// This flag may only be revisited after a reviewed threshold
/// implementation and an independent cryptographic review exist. Changing
/// it alone does not enable signing: every entry point also returns
/// [`MpcError::NotImplemented`].
pub const PRODUCTION_SIGNING_ENABLED: bool = false;

/// Errors returned by every MPC entry point. MPC code fails closed:
/// the default outcome of any unimplemented or unauthorised operation
/// is one of these errors, never a fallback signature.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum MpcError {
    /// The operation is a Phase 0 skeleton stub and is not implemented.
    NotImplemented,
    /// Production signing was requested while production signing is disabled.
    ProductionSigningDisabled,
    /// An independent policy check rejected the signing intent.
    PolicyRejected(String),
    /// The signing intent has expired.
    ExpiredIntent,
}

impl fmt::Display for MpcError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::NotImplemented => write!(f, "not implemented (Phase 0 skeleton)"),
            Self::ProductionSigningDisabled => {
                write!(f, "production signing is disabled")
            }
            Self::PolicyRejected(reason) => write!(f, "policy rejected: {reason}"),
            Self::ExpiredIntent => write!(f, "signing intent has expired"),
        }
    }
}

impl std::error::Error for MpcError {}

/// Convenience result alias for MPC operations.
pub type MpcResult<T> = Result<T, MpcError>;

/// Runtime mode a coordinator or signer is asked to operate in.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RuntimeMode {
    /// Local development.
    Development,
    /// Testnet / automated testing.
    Test,
    /// Production. Always refused in this skeleton.
    Production,
}

/// An approved transaction intent, bound before any signing session.
///
/// Every field is part of the binding that independent signers verify.
/// Amounts are integer base units carried as decimal strings; floating
/// point is never used for money anywhere in this workspace.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SigningIntent {
    /// Tenant (organization/project owner) identifier.
    pub tenant_id: String,
    /// Wallet identifier owned by `tenant_id`.
    pub wallet_id: String,
    /// Network identifier, e.g. `"ethereum"`, `"bsc"`, `"tron"`,
    /// `"solana"`, `"ton"` (with an environment suffix where relevant).
    pub network: String,
    /// Chain-specific asset identity (network + contract/mint/master
    /// address + program where relevant) — never a bare symbol.
    pub asset_id: String,
    /// Destination address, in the network's canonical encoding.
    pub destination: String,
    /// Amount in integer base units, as a decimal string (e.g. `"150000000"`).
    pub amount_base_units: String,
    /// Maximum permitted fee in integer base units, as a decimal string.
    pub fee_max_base_units: String,
    /// Hex/base encoding of the hash of the exact transaction payload
    /// that the signers are being asked to sign.
    pub payload_hash: String,
    /// Version of the signing policy this intent was approved under.
    pub policy_version: String,
    /// Expiry as a Unix timestamp (seconds). Intents at or past this
    /// time must be rejected.
    pub expires_at: i64,
}

/// Opaque reference to a key share held inside a signer's own secure
/// storage. The handle itself contains no key material and reveals
/// nothing about the share; it is the only share reference allowed in
/// logs, databases, and API/gRPC messages.
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct ShareHandle {
    /// Opaque, non-secret identifier (e.g. a UUID assigned at keygen).
    pub id: String,
}

impl ShareHandle {
    /// Create a handle from an opaque identifier.
    #[must_use]
    pub fn new(id: impl Into<String>) -> Self {
        Self { id: id.into() }
    }
}

/// Refuse production mode while production signing is disabled.
///
/// Shared by the coordinator and signer crates so the fail-closed rule
/// lives in exactly one place.
///
/// # Errors
/// Returns [`MpcError::ProductionSigningDisabled`] in production mode.
pub fn ensure_not_production(mode: RuntimeMode) -> MpcResult<()> {
    if mode == RuntimeMode::Production && !PRODUCTION_SIGNING_ENABLED {
        return Err(MpcError::ProductionSigningDisabled);
    }
    Ok(())
}
