//! Threshold ECDSA (secp256k1) for Ethereum / BSC / TRON.
//!
//! **Not implemented (Phase 0 skeleton).**
//!
//! Candidate: the CGGMP protocol family, via the `cggmp21` crate —
//! see the commented, unpinned placeholder in the workspace
//! `Cargo.toml`. Before any implementation lands here, the exact
//! protocol version, licence, published audits, known limitations,
//! side-channel assumptions, HD derivation support, and share-refresh
//! capability must be reviewed, the version pinned, and an independent
//! cryptographic review completed.
//!
//! There is intentionally no fallback: no single-key ECDSA, no Shamir
//! reconstruction, and no mock signer may be substituted here.

#![forbid(unsafe_code)]

use custodium_mpc_shared::{MpcError, MpcResult, ShareHandle, SigningIntent};

/// Parameters for a future distributed key-generation ceremony.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct KeygenParams {
    /// Signing threshold (initial topology target: 2).
    pub threshold: u16,
    /// Total number of participants (initial topology target: 3).
    pub total_participants: u16,
    /// Wallet the resulting key will belong to.
    pub wallet_id: String,
}

/// An ECDSA signature value. Only a completed, verified threshold
/// protocol run may ever construct this; the skeleton never does.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ThresholdSignature {
    /// Serialised signature bytes, in the target network's encoding.
    pub bytes: Vec<u8>,
}

/// Begin distributed key generation and return this participant's
/// opaque share handle.
///
/// # Errors
/// Always returns [`MpcError::NotImplemented`] in this skeleton.
pub fn keygen(_params: &KeygenParams) -> MpcResult<ShareHandle> {
    Err(MpcError::NotImplemented)
}

/// Participate in threshold signing of an approved `intent`.
///
/// # Errors
/// Always returns [`MpcError::NotImplemented`] in this skeleton.
pub fn sign(_intent: &SigningIntent, _share: &ShareHandle) -> MpcResult<ThresholdSignature> {
    Err(MpcError::NotImplemented)
}
