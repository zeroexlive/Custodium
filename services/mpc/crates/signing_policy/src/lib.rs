//! Independent signing-policy evaluation (pure logic, no I/O).
//!
//! Each signer must evaluate policy itself against the bound
//! [`SigningIntent`] before participating in a signing session; the
//! coordinator's or Django's approval is never sufficient on its own.
//!
//! The checks implemented here are real and complete for this crate's
//! scope. Threshold cryptography is out of scope for this crate.

#![forbid(unsafe_code)]

use custodium_mpc_shared::{MpcError, MpcResult, SigningIntent};

/// A versioned signing policy an intent is evaluated against.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SigningPolicy {
    /// Policy version; must match the intent's bound `policy_version`.
    pub version: String,
    /// Maximum permitted fee, in integer base units (decimal string).
    pub max_fee_base_units: String,
    /// Optional maximum permitted amount, in integer base units
    /// (decimal string). `None` means no amount cap in this policy.
    pub max_amount_base_units: Option<String>,
}

fn parse_base_units(field: &str, value: &str) -> MpcResult<i128> {
    value.trim().parse::<i128>().map_err(|_| {
        MpcError::PolicyRejected(format!("{field} is not a valid integer: {value:?}"))
    })
}

/// Evaluate `intent` against `policy` at time `now_unix` (seconds).
///
/// Fails closed. Rejects, in order:
/// 1. an expired intent (`expires_at <= now_unix`) — [`MpcError::ExpiredIntent`];
/// 2. a policy-version mismatch;
/// 3. an empty (or whitespace-only) destination;
/// 4. an amount that is non-numeric, zero, or negative;
/// 5. an amount above the policy cap, when one is set;
/// 6. a fee that is non-numeric, negative, or above the policy fee cap.
///
/// # Errors
/// Returns [`MpcError::ExpiredIntent`] or [`MpcError::PolicyRejected`].
pub fn evaluate(intent: &SigningIntent, policy: &SigningPolicy, now_unix: i64) -> MpcResult<()> {
    if intent.expires_at <= now_unix {
        return Err(MpcError::ExpiredIntent);
    }
    if intent.policy_version != policy.version {
        return Err(MpcError::PolicyRejected(format!(
            "policy version mismatch: intent {}, policy {}",
            intent.policy_version, policy.version
        )));
    }
    if intent.destination.trim().is_empty() {
        return Err(MpcError::PolicyRejected("destination is empty".to_owned()));
    }

    let amount = parse_base_units("amount_base_units", &intent.amount_base_units)?;
    if amount <= 0 {
        return Err(MpcError::PolicyRejected(
            "amount_base_units must be > 0".to_owned(),
        ));
    }
    if let Some(cap) = &policy.max_amount_base_units {
        let cap = parse_base_units("max_amount_base_units", cap)?;
        if amount > cap {
            return Err(MpcError::PolicyRejected(
                "amount exceeds policy maximum".to_owned(),
            ));
        }
    }

    let fee = parse_base_units("fee_max_base_units", &intent.fee_max_base_units)?;
    if fee < 0 {
        return Err(MpcError::PolicyRejected(
            "fee_max_base_units must be >= 0".to_owned(),
        ));
    }
    let max_fee = parse_base_units("max_fee_base_units", &policy.max_fee_base_units)?;
    if fee > max_fee {
        return Err(MpcError::PolicyRejected(
            "fee exceeds policy maximum".to_owned(),
        ));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    // NOTE: These tests exist but are UNEXECUTED in the current VM —
    // cargo is not installed there. Run `cargo test -p
    // custodium-mpc-signing-policy` once a toolchain is available.
    use super::*;

    fn intent() -> SigningIntent {
        SigningIntent {
            tenant_id: "tenant-1".to_owned(),
            wallet_id: "wallet-1".to_owned(),
            network: "ethereum".to_owned(),
            asset_id: "usdt_ethereum".to_owned(),
            destination: "0x1234567890abcdef1234567890abcdef12345678".to_owned(),
            amount_base_units: "150000000".to_owned(),
            fee_max_base_units: "1000".to_owned(),
            payload_hash: "deadbeef".to_owned(),
            policy_version: "v1".to_owned(),
            expires_at: 2_000_000_000,
        }
    }

    fn policy() -> SigningPolicy {
        SigningPolicy {
            version: "v1".to_owned(),
            max_fee_base_units: "5000".to_owned(),
            max_amount_base_units: None,
        }
    }

    const NOW: i64 = 1_900_000_000;

    #[test]
    fn valid_intent_passes() {
        assert_eq!(evaluate(&intent(), &policy(), NOW), Ok(()));
    }

    #[test]
    fn expired_intent_is_rejected() {
        let mut i = intent();
        i.expires_at = NOW;
        assert_eq!(evaluate(&i, &policy(), NOW), Err(MpcError::ExpiredIntent));
    }

    #[test]
    fn zero_and_negative_amounts_are_rejected() {
        for amount in ["0", "-5"] {
            let mut i = intent();
            i.amount_base_units = amount.to_owned();
            assert!(matches!(
                evaluate(&i, &policy(), NOW),
                Err(MpcError::PolicyRejected(_))
            ));
        }
    }

    #[test]
    fn non_numeric_amount_is_rejected() {
        let mut i = intent();
        i.amount_base_units = "150.00".to_owned(); // floats are not base units
        assert!(matches!(
            evaluate(&i, &policy(), NOW),
            Err(MpcError::PolicyRejected(_))
        ));
    }

    #[test]
    fn empty_destination_is_rejected() {
        let mut i = intent();
        i.destination = "  ".to_owned();
        assert!(matches!(
            evaluate(&i, &policy(), NOW),
            Err(MpcError::PolicyRejected(_))
        ));
    }

    #[test]
    fn fee_above_policy_max_is_rejected() {
        let mut i = intent();
        i.fee_max_base_units = "5001".to_owned();
        assert!(matches!(
            evaluate(&i, &policy(), NOW),
            Err(MpcError::PolicyRejected(_))
        ));
    }

    #[test]
    fn policy_version_mismatch_is_rejected() {
        let mut i = intent();
        i.policy_version = "v99".to_owned();
        assert!(matches!(
            evaluate(&i, &policy(), NOW),
            Err(MpcError::PolicyRejected(_))
        ));
    }
}
