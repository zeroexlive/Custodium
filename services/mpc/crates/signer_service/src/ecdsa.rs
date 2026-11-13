//! ECDSA (secp256k1) sessions on cggmp24: aux-info generation
//! (once per node set, persisted and reused), threshold DKG, and
//! threshold signing of pre-computed 32-byte digests — the same
//! protocol usage the Phase 3 evaluation executed, now driven over
//! the peer HTTP transport with persisted, encrypted shares.
//!
//! cggmp24 is pinned at =0.7.0-alpha.2 (ALPHA, not independently
//! reviewed for Custodium). Signing digests are produced by the
//! caller (Django builds transaction sighashes; their preimages are
//! constructed by our own code — the documented safe case for
//! `PrehashedDataToSign`).

use cggmp24::key_share::{AnyKeyShare, AuxInfo};
use cggmp24::supported_curves::Secp256k1;
use cggmp24::{ExecutionId, KeyShare};
use rand_core::OsRng;
use sha2::Sha256;

use crate::node::{ecdsa_share_name, meta_name, Node, AUX_NAME};
use crate::{err, SvcResult};

type AuxMsg =
    cggmp24::key_refresh::msg::Msg<Sha256, cggmp24::security_level::SecurityLevel128>;
type KeygenMsg = cggmp24::keygen::msg::threshold::Msg<
    Secp256k1,
    cggmp24::security_level::SecurityLevel128,
    Sha256,
>;
type SigningMsg = cggmp24::signing::msg::Msg<Secp256k1, Sha256>;

/// Load this node's persisted aux info, generating it with the
/// full node set on first use. Aux generation is expensive
/// (safe primes); the result is reused across keys.
async fn load_or_generate_aux(node: &Node, group: &str) -> SvcResult<AuxInfo> {
    if let Some(bytes) = node.store.load_secret(AUX_NAME)? {
        return serde_json::from_slice(&bytes).map_err(err);
    }
    let session = format!("{group}:aux");
    let all: Vec<u16> = (0..node.config.n).collect();
    let (recv, send) = crate::transport::round_based_delivery::<AuxMsg>(
        node.net.clone(),
        node.inboxes.clone(),
        session,
        &all,
    );
    let party = round_based::MpcParty::connected((recv, send));
    let pregenerated = cggmp24::PregeneratedPrimes::generate(&mut OsRng);
    let aux = cggmp24::aux_info_gen(
        ExecutionId::new(format!("custodium-aux-{group}").as_bytes()),
        node.me(),
        node.config.n,
        pregenerated,
    )
    .start(&mut OsRng, party)
    .await
    .map_err(err)?;
    let bytes = serde_json::to_vec(&aux).map_err(err)?;
    node.store.save_secret(AUX_NAME, &bytes)?;
    Ok(aux)
}

/// Run this node's part of an ECDSA DKG (`t`-of-`n`), persist the
/// resulting share (encrypted), and return the public metadata.
pub async fn run_ecdsa_keygen(
    node: &Node,
    group: &str,
    key_id: &str,
    t: u16,
) -> SvcResult<serde_json::Value> {
    crate::store::validate_key_id(key_id)?;
    if node.store.has_secret(&ecdsa_share_name(key_id)) {
        return Err(format!("key {key_id} already exists on this node"));
    }
    let aux = load_or_generate_aux(node, group).await?;
    let session = format!("{group}:keygen");
    let all: Vec<u16> = (0..node.config.n).collect();
    let (recv, send) = crate::transport::round_based_delivery::<KeygenMsg>(
        node.net.clone(),
        node.inboxes.clone(),
        session,
        &all,
    );
    let party = round_based::MpcParty::connected((recv, send));
    let incomplete = cggmp24::keygen::<Secp256k1>(
        ExecutionId::new(format!("custodium-keygen-{group}").as_bytes()),
        node.me(),
        node.config.n,
    )
    .set_threshold(t)
    .start(&mut OsRng, party)
    .await
    .map_err(err)?;
    let share = KeyShare::from_parts((incomplete, aux)).map_err(err)?;
    let public_key_point = share.shared_public_key();
    let public_key_sec1 = sec1_uncompressed(&public_key_point);
    let bytes = serde_json::to_vec(&share).map_err(err)?;
    node.store.save_secret(&ecdsa_share_name(key_id), &bytes)?;
    let meta = serde_json::json!({
        "key_id": key_id,
        "curve": "secp256k1",
        "t": t,
        "n": node.config.n,
        "public_key": hex::encode(&public_key_sec1),
    });
    node.store.save_public(&meta_name(key_id), &meta.to_string())?;
    Ok(meta)
}

/// Run this node's part of a threshold signing session for one
/// 32-byte digest; returns (r, s) hex after in-library verification.
pub async fn run_ecdsa_sign(
    node: &Node,
    group: &str,
    key_id: &str,
    signers: &[u16],
    digest: &[u8; 32],
) -> SvcResult<serde_json::Value> {
    let bytes = node
        .store
        .load_secret(&ecdsa_share_name(key_id))?
        .ok_or_else(|| format!("no ECDSA share for key {key_id} on this node"))?;
    let share: KeyShare<Secp256k1> = serde_json::from_slice(&bytes).map_err(err)?;
    let prehashed = cggmp24::PrehashedDataToSign::from_scalar(
        generic_ec::Scalar::from_be_bytes_mod_order(digest),
    );
    let session = format!("{group}:sign");
    let (recv, send) = crate::transport::round_based_delivery::<SigningMsg>(
        node.net.clone(),
        node.inboxes.clone(),
        session,
        signers,
    );
    let party = round_based::MpcParty::connected((recv, send));
    let signature = cggmp24::signing(
        ExecutionId::new(format!("custodium-sign-{group}").as_bytes()),
        signers
            .iter()
            .position(|&i| i == node.me())
            .ok_or("this node is not in the signer set")? as u16,
        signers,
        &share,
    )
    .sign(&mut OsRng, party, &prehashed)
    .await
    .map_err(err)?;
    let public_key_point = share.shared_public_key();
    signature
        .verify(&public_key_point, &prehashed)
        .map_err(err)?;
    Ok(serde_json::json!({
        "r": hex::encode(signature.r.to_be_bytes()),
        "s": hex::encode(signature.s.to_be_bytes()),
    }))
}

/// SEC 1 uncompressed encoding of a secp256k1 point.
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
