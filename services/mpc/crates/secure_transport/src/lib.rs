//! Secure transport configuration for coordinator <-> signer traffic
//! (Phase 0 skeleton).
//!
//! Inter-participant traffic must use mutually authenticated TLS
//! (mTLS) with certificate verification that cannot be disabled, over
//! `https` endpoints only. No transport is actually opened by this
//! skeleton: [`establish_channel`] fails closed. The validation logic
//! in [`validate_channel_config`] is real, pure, and tested, so the
//! rules exist before any networking code does.

#![forbid(unsafe_code)]

use custodium_mpc_shared::{MpcError, MpcResult};

/// Configuration for one mTLS channel to a peer participant.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ChannelConfig {
    /// Peer endpoint. Must be an `https://` URL.
    pub endpoint: String,
    /// Expected peer identity (certificate subject / SPIFFE ID).
    pub peer_identity: String,
    /// Path or reference to this participant's client certificate.
    /// A reference only — certificate/key file contents never pass
    /// through this struct, logs, or APIs.
    pub client_cert_ref: String,
    /// Certificate verification. Must be `true`; there is no supported
    /// configuration in which it is `false`.
    pub verify_peer_cert: bool,
}

/// Validate a channel configuration. Fails closed on any violation.
///
/// # Errors
/// [`MpcError::PolicyRejected`] if the endpoint is empty or not
/// `https`, if the peer identity or certificate reference is empty,
/// or if certificate verification is disabled.
pub fn validate_channel_config(config: &ChannelConfig) -> MpcResult<()> {
    if config.endpoint.trim().is_empty() || !config.endpoint.starts_with("https://") {
        return Err(MpcError::PolicyRejected(
            "endpoint must be a non-empty https URL".to_owned(),
        ));
    }
    if config.peer_identity.trim().is_empty() {
        return Err(MpcError::PolicyRejected(
            "peer_identity must not be empty".to_owned(),
        ));
    }
    if config.client_cert_ref.trim().is_empty() {
        return Err(MpcError::PolicyRejected(
            "client_cert_ref must not be empty".to_owned(),
        ));
    }
    if !config.verify_peer_cert {
        return Err(MpcError::PolicyRejected(
            "certificate verification cannot be disabled".to_owned(),
        ));
    }
    Ok(())
}

/// An established channel handle. The skeleton never constructs one.
#[derive(Debug)]
pub struct SecureChannel {
    /// Endpoint the channel is bound to.
    pub endpoint: String,
}

/// Open a channel to a peer. Validates the configuration first.
///
/// # Errors
/// The `signing_policy`-style [`MpcError::PolicyRejected`] errors from
/// validation, otherwise [`MpcError::NotImplemented`].
pub fn establish_channel(config: &ChannelConfig) -> MpcResult<SecureChannel> {
    validate_channel_config(config)?;
    Err(MpcError::NotImplemented)
}

#[cfg(test)]
mod tests {
    // NOTE: These tests exist but are UNEXECUTED in the current VM —
    // cargo is not installed there. Run `cargo test -p
    // custodium-mpc-secure-transport` once a toolchain is available.
    use super::*;

    fn config() -> ChannelConfig {
        ChannelConfig {
            endpoint: "https://signer-1.internal:8443".to_owned(),
            peer_identity: "signer-1".to_owned(),
            client_cert_ref: "kms://custodium/mpc/coordinator-cert".to_owned(),
            verify_peer_cert: true,
        }
    }

    #[test]
    fn valid_config_passes() {
        assert_eq!(validate_channel_config(&config()), Ok(()));
    }

    #[test]
    fn plaintext_endpoint_is_rejected() {
        let mut c = config();
        c.endpoint = "http://signer-1.internal:8443".to_owned();
        assert!(matches!(
            validate_channel_config(&c),
            Err(MpcError::PolicyRejected(_))
        ));
    }

    #[test]
    fn disabled_cert_verification_is_rejected() {
        let mut c = config();
        c.verify_peer_cert = false;
        assert!(matches!(
            validate_channel_config(&c),
            Err(MpcError::PolicyRejected(_))
        ));
    }
}
