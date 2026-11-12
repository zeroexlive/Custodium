//! Threshold Ed25519-compatible signing for Solana / TON.
//!
//! **Not implemented (Phase 0 skeleton).**
//!
//! Candidate: FROST for Ed25519 (RFC 9591), via the `frost-ed25519`
//! crate — see the commented, unpinned placeholder in the workspace
//! `Cargo.toml`. FROST produces Schnorr-style threshold signatures
//! that are Ed25519-verifiable; it must not be confused with ECDSA.
//! Before any implementation lands here: pin the version, review
//! audits/limitations, verify produced signatures against the exact
//! Solana transaction messages and TON wallet contracts in scope, and
//! document DKG / derivation limitations. Independent cryptographic
//! review is required before enablement.
//!
//! No single-key Ed25519, Shamir reconstruction, or mock signer may be
//! substituted here.

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

/// An Ed25519 signature value. Only a completed, verified FROST run
/// may ever construct this; the skeleton never does.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ThresholdSignature {
    /// The 64-byte Ed25519 signature.
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
