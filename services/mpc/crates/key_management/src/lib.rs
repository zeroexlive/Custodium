//! Key lifecycle metadata management (Phase 0 skeleton).
//!
//! This crate tracks *metadata about* keys — which wallet, network,
//! and opaque [`ShareHandle`] a key has, and its lifecycle state. It
//! never stores, derives, serialises, or reconstructs key material:
//! shares live only inside each signer's own secure storage, outside
//! the application database, logs, and APIs.
//!
//! Lifecycle transitions that would touch shares (rotation, refresh /
//! resharing, signer replacement, recovery) are not implemented and
//! fail closed until the reviewed threshold implementation defines
//! them safely.

#![forbid(unsafe_code)]

use custodium_mpc_shared::{MpcError, MpcResult, ShareHandle};

/// Lifecycle state of a managed key.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum KeyLifecycleState {
    /// Keygen has been requested but not completed.
    PendingKeygen,
    /// Key is active (metadata state only; signing may still be disabled).
    Active,
    /// Key is suspended and must not be used for new signing sessions.
    Suspended,
    /// Key is retired and must never be used again.
    Retired,
}

/// Non-secret metadata describing one MPC key.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct KeyMetadata {
    /// Unique key identifier.
    pub key_id: String,
    /// Wallet this key belongs to.
    pub wallet_id: String,
    /// Network / chain family this key serves.
    pub network: String,
    /// Signature family: `"ecdsa_secp256k1"` or `"ed25519"`.
    pub scheme: String,
    /// Signing threshold (initial topology target: 2-of-3).
    pub threshold: u16,
    /// Total participants holding shares.
    pub total_participants: u16,
    /// Public key / public address material. Public data only — this
    /// struct has no field capable of holding secret material.
    pub public_key: String,
    /// Opaque handles of the shares, one per participant. Handles
    /// only; the shares themselves are never present here.
    pub share_handles: Vec<ShareHandle>,
    /// Current lifecycle state.
    pub state: KeyLifecycleState,
}

/// Request a share refresh / resharing for `key_id`.
///
/// # Errors
/// Always [`MpcError::NotImplemented`]: refresh support depends on the
/// reviewed threshold implementation and must not be improvised.
pub fn request_share_refresh(_key_id: &str) -> MpcResult<()> {
    Err(MpcError::NotImplemented)
}

/// Request replacement of one signer participant for `key_id`.
///
/// # Errors
/// Always [`MpcError::NotImplemented`] in this skeleton.
pub fn request_signer_replacement(_key_id: &str, _signer_id: &str) -> MpcResult<()> {
    Err(MpcError::NotImplemented)
}

/// Request key recovery for `key_id`.
///
/// Recovery is a designed, audited procedure — not a code path that
/// reconstructs a complete private key. It does not exist here.
///
/// # Errors
/// Always [`MpcError::NotImplemented`] in this skeleton.
pub fn request_recovery(_key_id: &str) -> MpcResult<()> {
    Err(MpcError::NotImplemented)
}
