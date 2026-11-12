//! CGGMP-family threshold ECDSA (secp256k1) evaluation: real
//! aux-info generation, DKG, and threshold signing with ephemeral
//! in-memory test keys (Phase 3).
//!
//! Candidate evaluated: `cggmp24` **0.7.0-alpha.2** (pinned), the
//! patched successor of `cggmp21`. `cggmp21` itself is NOT evaluated
//! as a production candidate: versions `<= 0.6.2` are critically
//! vulnerable (CVE-2025-66016 — a single malicious signer can
//! reconstruct the full private key via a missing ZK-proof check),
//! and the presignature-forgery advisory RUSTSEC-2025-0127 remains
//! unpatched in the latest `cggmp21` (0.6.3). See
//! `docs/mpc/phase-3-evaluation.md`.
//!
//! Parties run as async tasks inside one process, communicating over
//! `round_based`'s simulated in-memory network. This evaluates the
//! protocol library only — not authenticated/encrypted transport,
//! signer isolation, or share storage, none of which exist yet.
//! Nothing is persisted; shares never leave the process.
//!
//! Note: safe-prime generation for the Paillier auxiliary data is
//! genuinely expensive; the ceremony test takes on the order of a
//! minute on a small machine. That cost is itself an evaluation
//! data point (aux data is generated once per signer set and can be
//! reused across keys, per the crate documentation).

use cggmp24::key_share::AnyKeyShare;
use cggmp24::supported_curves::Secp256k1;
use cggmp24::{ExecutionId, KeyShare};
use rand_core::OsRng;
use sha2::Sha256;

/// Errors from the evaluation ceremonies (stringified library errors).
pub type EvalResult<T> = Result<T, String>;

fn err<E: std::fmt::Debug>(e: E) -> String {
    format!("{e:?}")
}

/// Output of a completed evaluation ceremony.
pub struct CeremonyOutput {
    /// Shared public key, SEC 1 uncompressed encoding (65 bytes).
    pub public_key_sec1: Vec<u8>,
    /// The threshold signature's `r` component (32 bytes, big-endian).
    pub signature_r: Vec<u8>,
    /// The threshold signature's `s` component (32 bytes, big-endian).
    pub signature_s: Vec<u8>,
}

/// Run aux-info generation for `n` parties (simulated network).
async fn run_aux(n: u16, eid: &[u8]) -> EvalResult<Vec<cggmp24::key_share::AuxInfo>> {
    type Msg =
        cggmp24::key_refresh::msg::Msg<Sha256, cggmp24::security_level::SecurityLevel128>;
    let eid = ExecutionId::new(eid);
    let results = round_based::sim::async_env::run::<Msg, _>(n, |i, party| async move {
        // Safe-prime generation is intentionally expensive.
        let pregenerated = cggmp24::PregeneratedPrimes::generate(&mut OsRng);
        cggmp24::aux_info_gen(eid, i, n, pregenerated)
            .start(&mut OsRng, party)
            .await
            .map_err(err)
    })
    .await
    .into_vec();
    results.into_iter().collect()
}

/// Run threshold DKG for `t`-of-`n` (simulated network).
async fn run_keygen(
    n: u16,
    t: u16,
    eid: &[u8],
) -> EvalResult<Vec<cggmp24::IncompleteKeyShare<Secp256k1>>> {
    type Msg = cggmp24::keygen::msg::threshold::Msg<
        Secp256k1,
        cggmp24::security_level::SecurityLevel128,
        Sha256,
    >;
    let eid = ExecutionId::new(eid);
    let results = round_based::sim::async_env::run::<Msg, _>(n, |i, party| async move {
        cggmp24::keygen::<Secp256k1>(eid, i, n)
            .set_threshold(t)
            .start(&mut OsRng, party)
            .await
            .map_err(err)
    })
    .await
    .into_vec();
    results.into_iter().collect()
}

/// Run a full ceremony: aux-info generation, DKG, then signing of
/// `message` by the parties listed in `signers` (keygen indices;
/// exactly `t` of them). The resulting signature is verified inside
/// the library (`Signature::verify`) before being returned.
pub async fn run_ceremony(
    n: u16,
    t: u16,
    signers: &[u16],
    message: &[u8],
) -> EvalResult<CeremonyOutput> {
    if signers.len() != t as usize {
        return Err("signer set must contain exactly t parties".into());
    }
    let aux = run_aux(n, b"custodium-eval-aux-v1").await?;
    let incomplete = run_keygen(n, t, b"custodium-eval-keygen-v1").await?;

    let mut key_shares: Vec<KeyShare<Secp256k1>> = Vec::new();
    for (share, aux_info) in incomplete.into_iter().zip(aux) {
        key_shares
            .push(KeyShare::from_parts((share, aux_info)).map_err(err)?);
    }
    let public_key_point = key_shares[0].shared_public_key();
    for share in &key_shares {
        if share.shared_public_key() != public_key_point {
            return Err("parties disagree on the shared public key".into());
        }
    }

    // Signing: exactly the chosen t parties, addressed by their
    // keygen indices, run with signing indices 0..t.
    type SigningMsg = cggmp24::signing::msg::Msg<Secp256k1, Sha256>;
    let data_to_sign = cggmp24::DataToSign::digest::<Sha256>(message);
    let signing_shares: Vec<KeyShare<Secp256k1>> =
        signers.iter().map(|&i| key_shares[i as usize].clone()).collect();
    let signers_owned: Vec<u16> = signers.to_vec();
    let results = round_based::sim::async_env::run_with_setup::<
        KeyShare<Secp256k1>,
        SigningMsg,
        _,
    >(
        signing_shares,
        |j, party, key_share| {
            let signers_at_keygen = signers_owned.clone();
            async move {
                cggmp24::signing(
                    ExecutionId::new(b"custodium-eval-signing-v1"),
                    j,
                    &signers_at_keygen,
                    &key_share,
                )
                .sign(&mut OsRng, party, &data_to_sign)
                .await
                .map_err(err)
            }
        },
    )
    .await
    .into_vec();
    let signatures: Vec<cggmp24::Signature<Secp256k1>> =
        results.into_iter().collect::<EvalResult<Vec<_>>>()?;
    let signature = signatures[0];
    if signatures.iter().any(|s| s != &signature) {
        return Err("signing parties produced different signatures".into());
    }
    signature
        .verify(&public_key_point, &data_to_sign)
        .map_err(err)?;

    Ok(CeremonyOutput {
        public_key_sec1: sec1_uncompressed(&public_key_point),
        signature_r: signature.r.to_be_bytes().to_vec(),
        signature_s: signature.s.to_be_bytes().to_vec(),
    })
}

/// Run one key-generation ceremony and sign SEVERAL pre-computed
/// 32-byte digests with the same key (Phase 4 cross-check: the
/// digests are EVM transaction sighashes produced by the Python
/// backend; the preimage — the transaction — is constructed by our
/// own code, which is the documented safe case for
/// `PrehashedDataToSign`). Each signature is verified inside the
/// library before being returned. Returns the group public key
/// (SEC 1) and one (r, s) pair per digest, in order.
pub async fn run_ceremony_for_digests(
    n: u16,
    t: u16,
    signers: &[u16],
    digests: &[[u8; 32]],
) -> EvalResult<(Vec<u8>, Vec<(Vec<u8>, Vec<u8>)>)> {
    if signers.len() != t as usize {
        return Err("signer set must contain exactly t parties".into());
    }
    if digests.is_empty() {
        return Err("no digests to sign".into());
    }
    let aux = run_aux(n, b"custodium-eval-aux-v1").await?;
    let incomplete = run_keygen(n, t, b"custodium-eval-keygen-v1").await?;

    let mut key_shares: Vec<KeyShare<Secp256k1>> = Vec::new();
    for (share, aux_info) in incomplete.into_iter().zip(aux) {
        key_shares.push(KeyShare::from_parts((share, aux_info)).map_err(err)?);
    }
    let public_key_point = key_shares[0].shared_public_key();
    for share in &key_shares {
        if share.shared_public_key() != public_key_point {
            return Err("parties disagree on the shared public key".into());
        }
    }

    type SigningMsg = cggmp24::signing::msg::Msg<Secp256k1, Sha256>;
    let mut out: Vec<(Vec<u8>, Vec<u8>)> = Vec::new();
    for (index, digest) in digests.iter().enumerate() {
        let prehashed = cggmp24::PrehashedDataToSign::from_scalar(
            generic_ec::Scalar::from_be_bytes_mod_order(digest),
        );
        let signing_shares: Vec<KeyShare<Secp256k1>> =
            signers.iter().map(|&i| key_shares[i as usize].clone()).collect();
        let signers_owned: Vec<u16> = signers.to_vec();
        let eid = format!("custodium-eval-signing-digest-{index}");
        let results = round_based::sim::async_env::run_with_setup::<
            KeyShare<Secp256k1>,
            SigningMsg,
            _,
        >(
            signing_shares,
            |j, party, key_share| {
                let signers_at_keygen = signers_owned.clone();
                let eid = eid.clone();
                async move {
                    cggmp24::signing(
                        ExecutionId::new(eid.as_bytes()),
                        j,
                        &signers_at_keygen,
                        &key_share,
                    )
                    .sign(&mut OsRng, party, &prehashed)
                    .await
                    .map_err(err)
                }
            },
        )
        .await
        .into_vec();
        let signatures: Vec<cggmp24::Signature<Secp256k1>> =
            results.into_iter().collect::<EvalResult<Vec<_>>>()?;
        let signature = signatures[0];
        if signatures.iter().any(|s| s != &signature) {
            return Err("signing parties produced different signatures".into());
        }
        signature.verify(&public_key_point, &prehashed).map_err(err)?;
        out.push((
            signature.r.to_be_bytes().to_vec(),
            signature.s.to_be_bytes().to_vec(),
        ));
    }
    Ok((sec1_uncompressed(&public_key_point), out))
}

/// SEC 1 uncompressed encoding of a secp256k1 point from its affine
/// coordinates.
fn sec1_uncompressed(
    point: &generic_ec::NonZero<generic_ec::Point<Secp256k1>>,
) -> Vec<u8> {
    use generic_ec::coords::{HasAffineX, HasAffineY};
    let mut out = Vec::with_capacity(65);
    out.push(0x04);
    out.extend_from_slice(
        point
            .x()
            .expect("non-zero point has an x coordinate")
            .as_be_bytes(),
    );
    out.extend_from_slice(
        point
            .y()
            .expect("non-zero point has a y coordinate")
            .as_be_bytes(),
    );
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use sha2::Digest;

    #[tokio::test(flavor = "multi_thread", worker_threads = 4)]
    async fn two_of_three_ceremony_signs_and_verifies() {
        let message = b"custodium phase 3 cggmp24 evaluation";
        let output = run_ceremony(3, 2, &[0, 2], message)
            .await
            .expect("2-of-3 ceremony must complete");

        assert_eq!(output.public_key_sec1.len(), 65);
        assert_eq!(output.public_key_sec1[0], 0x04);
        assert_eq!(output.signature_r.len(), 32);
        assert_eq!(output.signature_s.len(), 32);

        // Independent verification with k256, exactly as an EVM chain
        // would: ECDSA over secp256k1 with SHA-256 prehash.
        let verifying_key =
            k256::ecdsa::VerifyingKey::from_sec1_bytes(&output.public_key_sec1)
                .expect("valid secp256k1 public key");
        let mut rs = Vec::with_capacity(64);
        rs.extend_from_slice(&output.signature_r);
        rs.extend_from_slice(&output.signature_s);
        let signature = k256::ecdsa::Signature::from_slice(&rs).expect("valid signature");
        let digest = Sha256::digest(message);
        use k256::ecdsa::signature::hazmat::PrehashVerifier;
        assert!(
            verifying_key.verify_prehash(&digest, &signature).is_ok(),
            "k256 must verify the threshold signature"
        );
    }

    /// Phase 4 cross-proof: the digests below are EVM transaction
    /// sighashes computed by the Python backend
    /// (`waas.modules.evm.transactions`, chain Sepolia, from the
    /// module's own test fixtures: a native transfer, nonce 0, and
    /// an ERC-20 transfer, nonce 1). The threshold group signs both
    /// in ONE key-generation ceremony; the test then derives the
    /// group key's EVM address (Keccak-256 of x||y, last 20 bytes)
    /// and proves `ecrecover` returns exactly that address for each
    /// signature — i.e. these threshold signatures are valid EVM
    /// transaction signatures from the wallet's address.
    #[tokio::test(flavor = "multi_thread", worker_threads = 4)]
    async fn threshold_signatures_are_valid_evm_signatures() {
        use sha3::Digest as _;
        const NATIVE_SIGHASH: [u8; 32] = [
            0xf5, 0x91, 0xbd, 0x8f, 0x35, 0xee, 0xac, 0xa1, 0x77, 0xbf, 0x38, 0x28,
            0xc7, 0x27, 0x90, 0xab, 0x67, 0x0b, 0x38, 0x81, 0x38, 0x56, 0xfd, 0x20,
            0xf4, 0xbc, 0x97, 0x62, 0x6f, 0x3b, 0x8f, 0x5d,
        ];
        const TOKEN_SIGHASH: [u8; 32] = [
            0x4a, 0x00, 0x65, 0x60, 0xd9, 0x1b, 0x83, 0x51, 0xfc, 0x6b, 0x99, 0xd6,
            0x43, 0x13, 0xb5, 0x1e, 0xe7, 0xfe, 0xf2, 0x8d, 0xf7, 0xfc, 0xb8, 0x61,
            0x61, 0x71, 0x76, 0x58, 0xd3, 0x2e, 0xd8, 0x81,
        ];
        let digests = [NATIVE_SIGHASH, TOKEN_SIGHASH];
        let (public_key_sec1, signatures) =
            run_ceremony_for_digests(3, 2, &[0, 2], &digests)
                .await
                .expect("2-of-3 ceremony must sign both digests");
        assert_eq!(signatures.len(), 2);

        // The wallet address an EVM chain would see for this group key.
        let group_key = k256::ecdsa::VerifyingKey::from_sec1_bytes(&public_key_sec1)
            .expect("valid secp256k1 public key");
        let encoded = group_key.to_encoded_point(false);
        let xy = &encoded.as_bytes()[1..]; // x || y, no 0x04 prefix
        let hash = sha3::Keccak256::digest(xy);
        let expected_address = &hash[12..];

        for (digest, (r, s)) in digests.iter().zip(&signatures) {
            let mut rs = Vec::with_capacity(64);
            rs.extend_from_slice(r);
            rs.extend_from_slice(s);
            let signature =
                k256::ecdsa::Signature::from_slice(&rs).expect("valid signature encoding");
            // ecrecover: exactly one recovery id must reproduce the
            // group key (and therefore the address).
            let mut recovered_address = None;
            for is_odd in [false, true] {
                let recid = k256::ecdsa::RecoveryId::new(is_odd, false);
                if let Ok(recovered) = k256::ecdsa::VerifyingKey::recover_from_prehash(
                    digest, &signature, recid,
                ) {
                    if recovered == group_key {
                        let point = recovered.to_encoded_point(false);
                        let rhash = sha3::Keccak256::digest(&point.as_bytes()[1..]);
                        recovered_address = Some(rhash[12..].to_vec());
                    }
                }
            }
            assert_eq!(
                recovered_address.as_deref(),
                Some(expected_address),
                "ecrecover must return the group key's EVM address"
            );
        }
    }
}
