//! FROST (RFC 9591) Ed25519 evaluation: real DKG + threshold signing
//! with ephemeral in-memory test keys (Phase 3).
//!
//! Ceremonies run in a single process with in-memory message routing
//! between simulated participants. This evaluates the *protocol
//! library* (`frost-ed25519` 3.0.0, pinned) — it does not evaluate
//! network transport, signer isolation, or storage, none of which
//! exist yet. Nothing is persisted; shares never leave the process.

use std::collections::BTreeMap;

use frost_ed25519 as frost;
use frost::keys::{KeyPackage, PublicKeyPackage};
use frost::{Identifier, Signature, SigningPackage};
use rand::rngs::OsRng;

/// Errors from the evaluation ceremonies (library errors, stringified
/// so this crate does not leak candidate-internal error types).
pub type EvalResult<T> = Result<T, String>;

fn err<E: std::fmt::Debug>(e: E) -> String {
    format!("{e:?}")
}

fn identifiers(n: u16) -> EvalResult<Vec<Identifier>> {
    (1..=n).map(|i| Identifier::try_from(i).map_err(err)).collect()
}

/// Run a full FROST DKG for `min_signers`-of-`max_signers` and return
/// each participant's key package plus the public key package.
///
/// Round 1 packages are broadcast to all participants; round 2
/// packages are delivered point-to-point — routed here through
/// in-memory maps, standing in for the (future, separately reviewed)
/// authenticated transport.
pub fn run_dkg(
    max_signers: u16,
    min_signers: u16,
) -> EvalResult<(BTreeMap<Identifier, KeyPackage>, PublicKeyPackage)> {
    let ids = identifiers(max_signers)?;
    let mut rng = OsRng;

    // Round 1: each participant generates a secret package + broadcast package.
    let mut round1_secrets = BTreeMap::new();
    let mut round1_packages = BTreeMap::new();
    for id in &ids {
        let (secret, package) = frost::keys::dkg::part1(*id, max_signers, min_signers, &mut rng)
            .map_err(err)?;
        round1_secrets.insert(*id, secret);
        round1_packages.insert(*id, package);
    }

    // Round 2: each participant consumes everyone else's round 1 package
    // and produces one round 2 package per other participant.
    let mut round2_secrets = BTreeMap::new();
    let mut round2_inbox: BTreeMap<Identifier, BTreeMap<Identifier, frost::keys::dkg::round2::Package>> =
        BTreeMap::new();
    for id in &ids {
        let others: BTreeMap<_, _> = round1_packages
            .iter()
            .filter(|(other, _)| *other != id)
            .map(|(k, v)| (*k, v.clone()))
            .collect();
        let (secret, packages) = frost::keys::dkg::part2(
            round1_secrets.remove(id).ok_or("missing round1 secret")?,
            &others,
        )
        .map_err(err)?;
        round2_secrets.insert(*id, secret);
        for (recipient, package) in packages {
            round2_inbox.entry(recipient).or_default().insert(*id, package);
        }
    }

    // Round 3: each participant finalises its long-lived key package.
    let mut key_packages = BTreeMap::new();
    let mut public_key_package: Option<PublicKeyPackage> = None;
    for id in &ids {
        let others_r1: BTreeMap<_, _> = round1_packages
            .iter()
            .filter(|(other, _)| *other != id)
            .map(|(k, v)| (*k, v.clone()))
            .collect();
        let inbox = round2_inbox.remove(id).ok_or("missing round2 inbox")?;
        let (key_package, pubkey_package) = frost::keys::dkg::part3(
            round2_secrets.get(id).ok_or("missing round2 secret")?,
            &others_r1,
            &inbox,
        )
        .map_err(err)?;
        if let Some(existing) = &public_key_package {
            if existing.verifying_key() != pubkey_package.verifying_key() {
                return Err("participants disagree on the group verifying key".into());
            }
        } else {
            public_key_package = Some(pubkey_package.clone());
        }
        key_packages.insert(*id, key_package);
    }

    Ok((
        key_packages,
        public_key_package.ok_or("no public key package produced")?,
    ))
}

/// Threshold-sign and verify against the group verifying key.
pub fn threshold_sign_with_package(
    key_packages: &BTreeMap<Identifier, KeyPackage>,
    pubkey_package: &PublicKeyPackage,
    signer_ids: &[Identifier],
    message: &[u8],
) -> EvalResult<Signature> {
    let mut rng = OsRng;
    let mut nonces = BTreeMap::new();
    let mut commitments = BTreeMap::new();
    for id in signer_ids {
        let key_package = key_packages.get(id).ok_or("unknown signer id")?;
        let (nonce, commitment) = frost::round1::commit(key_package.signing_share(), &mut rng);
        nonces.insert(*id, nonce);
        commitments.insert(*id, commitment);
    }
    let signing_package = SigningPackage::new(commitments, message);
    let mut signature_shares = BTreeMap::new();
    for id in signer_ids {
        let key_package = key_packages.get(id).ok_or("unknown signer id")?;
        let nonce = nonces.get(id).ok_or("missing nonce")?;
        let share = frost::round2::sign(&signing_package, nonce, key_package).map_err(err)?;
        signature_shares.insert(*id, share);
    }
    let signature = frost::aggregate(&signing_package, &signature_shares, pubkey_package)
        .map_err(err)?;
    pubkey_package
        .verifying_key()
        .verify(message, &signature)
        .map_err(err)?;
    Ok(signature)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ids(list: &[u16]) -> Vec<Identifier> {
        list.iter().map(|i| Identifier::try_from(*i).unwrap()).collect()
    }

    #[test]
    fn dkg_two_of_three_and_threshold_signing() {
        let (key_packages, pubkey_package) = run_dkg(3, 2).expect("DKG must succeed");
        assert_eq!(key_packages.len(), 3);
        // Any 2 of 3 can sign; check two different quorums.
        for quorum in [ids(&[1, 2]), ids(&[2, 3]), ids(&[1, 3])] {
            let signature = threshold_sign_with_package(
                &key_packages,
                &pubkey_package,
                &quorum,
                b"custodium phase 3 frost evaluation",
            )
            .expect("threshold signing must succeed and verify");
            // The group signature serialises to a standard 64-byte Ed25519 signature.
            let bytes = signature.serialize().expect("serialize signature");
            assert_eq!(bytes.len(), 64);
        }
    }

    #[test]
    fn below_threshold_cannot_sign() {
        let (key_packages, pubkey_package) = run_dkg(3, 2).expect("DKG must succeed");
        let result = threshold_sign_with_package(
            &key_packages,
            &pubkey_package,
            &ids(&[1]),
            b"one signer is not a quorum",
        );
        assert!(result.is_err(), "a single signer must not produce a group signature");
    }

    #[test]
    fn signature_fails_verification_for_other_message() {
        let (key_packages, pubkey_package) = run_dkg(3, 2).expect("DKG must succeed");
        let signature = threshold_sign_with_package(
            &key_packages,
            &pubkey_package,
            &ids(&[1, 2]),
            b"original message",
        )
        .expect("signing must succeed");
        assert!(
            pubkey_package
                .verifying_key()
                .verify(b"tampered message", &signature)
                .is_err(),
            "signature must not verify for a different message"
        );
    }

    #[test]
    fn group_key_is_a_standard_ed25519_key() {
        // Cross-implementation check: the FROST group verifying key and
        // signature must verify with an independent Ed25519 verifier
        // (ed25519-zebra), as Solana/TON verifiers would.
        let (key_packages, pubkey_package) = run_dkg(3, 2).expect("DKG must succeed");
        let message = b"cross-implementation verification";
        let signature = threshold_sign_with_package(
            &key_packages,
            &pubkey_package,
            &ids(&[1, 3]),
            message,
        )
        .expect("signing must succeed");
        let vk_bytes = pubkey_package
            .verifying_key()
            .serialize()
            .expect("serialize verifying key");
        let sig_bytes = signature.serialize().expect("serialize signature");
        let zebra_vk = ed25519_zebra::VerificationKey::try_from(
            <[u8; 32]>::try_from(vk_bytes.as_slice()).expect("32-byte key"),
        )
        .expect("valid ed25519 key");
        let zebra_sig = ed25519_zebra::Signature::try_from(
            <[u8; 64]>::try_from(sig_bytes.as_slice()).expect("64-byte signature"),
        )
        .expect("valid ed25519 signature");
        assert!(zebra_vk.verify(&zebra_sig, message).is_ok());
    }
}
