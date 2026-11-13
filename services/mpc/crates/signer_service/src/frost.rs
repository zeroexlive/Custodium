//! Ed25519 sessions on FROST (RFC 9591, `frost-ed25519` =3.0.0):
//! DKG and threshold signing of complete messages — the same
//! protocol usage the Phase 3 evaluation executed, now driven over
//! the peer HTTP transport with persisted, encrypted key packages.
//!
//! Message flow per session (explicit envelopes via `FrostBus`):
//! DKG round 1 packages are broadcast; DKG round 2 packages are
//! sent point-to-point to their recipient; signing commitments are
//! broadcast within the quorum; signature shares go to the
//! aggregator (the first listed signer), which aggregates and
//! verifies. The coordinator only starts sessions and reads public
//! results — it never relays secret-bearing round 2 packages.

use std::collections::BTreeMap;

use frost_ed25519 as frost;
use frost::keys::{KeyPackage, PublicKeyPackage};
use frost::{Identifier, SigningPackage};
use rand::rngs::OsRng;

use crate::node::{frost_pub_name, frost_share_name, meta_name, Node};
use crate::transport::FrostBus;
use crate::{err, SvcResult};

fn identifier(party_index: u16) -> SvcResult<Identifier> {
    Identifier::try_from(party_index + 1).map_err(err)
}

/// Collect exactly `count` envelopes of `kind`, stashing others.
struct Collector<'a> {
    bus: &'a mut FrostBus,
    stash: Vec<(u16, String, serde_json::Value)>,
}

impl<'a> Collector<'a> {
    async fn take(
        &mut self,
        kind: &str,
        count: usize,
    ) -> SvcResult<Vec<(u16, serde_json::Value)>> {
        let mut out: Vec<(u16, serde_json::Value)> = Vec::new();
        let mut i = 0;
        while i < self.stash.len() {
            if self.stash[i].1 == kind && out.len() < count {
                let (from, _, payload) = self.stash.remove(i);
                out.push((from, payload));
            } else {
                i += 1;
            }
        }
        while out.len() < count {
            let (from, k, payload) = self.bus.recv().await?;
            if k == kind {
                out.push((from, payload));
            } else {
                self.stash.push((from, k, payload));
            }
        }
        Ok(out)
    }
}

/// Run this node's part of a FROST DKG (`t`-of-`n`), persist the
/// key package (encrypted) and the public key package, and return
/// the public metadata.
pub async fn run_frost_keygen(
    node: &Node,
    group: &str,
    key_id: &str,
    t: u16,
) -> SvcResult<serde_json::Value> {
    crate::store::validate_key_id(key_id)?;
    if node.store.has_secret(&frost_share_name(key_id)) {
        return Err(format!("key {key_id} already exists on this node"));
    }
    let n = node.config.n;
    let me = identifier(node.me())?;
    let session = format!("{group}:dkg");
    let mut bus = FrostBus::new(node.net.clone(), &node.inboxes, session)?;
    let mut collector = Collector {
        bus: &mut bus,
        stash: Vec::new(),
    };
    let mut rng = OsRng;

    // Round 1: broadcast my package, collect everyone else's.
    let (round1_secret, my_r1) =
        frost::keys::dkg::part1(me, n, t, &mut rng).map_err(err)?;
    collector
        .bus
        .broadcast("r1", serde_json::to_value(&my_r1).map_err(err)?)
        .await?;
    let mut round1_packages: BTreeMap<Identifier, frost::keys::dkg::round1::Package> =
        BTreeMap::new();
    for (from, payload) in collector.take("r1", (n - 1) as usize).await? {
        round1_packages.insert(
            identifier(from)?,
            serde_json::from_value(payload).map_err(err)?,
        );
    }

    // Round 2: one package per other participant, sent directly.
    let (round2_secret, round2_packages) =
        frost::keys::dkg::part2(round1_secret, &round1_packages).map_err(err)?;
    for (recipient, package) in &round2_packages {
        // Identifier (1-based) -> party index (0-based).
        let to = recipient
            .serialize()
            .first()
            .map(|b| (*b as u16) - 1)
            .ok_or("bad identifier")?;
        collector
            .bus
            .send_to(to, "r2", serde_json::to_value(package).map_err(err)?)
            .await?;
    }
    let mut round2_inbox: BTreeMap<Identifier, frost::keys::dkg::round2::Package> =
        BTreeMap::new();
    for (from, payload) in collector.take("r2", (n - 1) as usize).await? {
        round2_inbox.insert(
            identifier(from)?,
            serde_json::from_value(payload).map_err(err)?,
        );
    }

    // Round 3: finalise my key package.
    let (key_package, pubkey_package) =
        frost::keys::dkg::part3(&round2_secret, &round1_packages, &round2_inbox)
            .map_err(err)?;
    node.store.save_secret(
        &frost_share_name(key_id),
        &serde_json::to_vec(&key_package).map_err(err)?,
    )?;
    node.store.save_public(
        &frost_pub_name(key_id),
        &serde_json::to_string(&pubkey_package).map_err(err)?,
    )?;
    let public_key = pubkey_package
        .verifying_key()
        .serialize()
        .map_err(err)?;
    let meta = serde_json::json!({
        "key_id": key_id,
        "curve": "ed25519",
        "t": t,
        "n": n,
        "public_key": hex::encode(&public_key),
    });
    node.store
        .save_public(&meta_name(key_id), &meta.to_string())?;
    Ok(meta)
}

/// Run this node's part of a FROST signing session for a complete
/// message. The aggregator returns the group signature; other
/// signers return an empty result after sending their share.
pub async fn run_frost_sign(
    node: &Node,
    group: &str,
    key_id: &str,
    signers: &[u16],
    message: &[u8],
    is_aggregator: bool,
) -> SvcResult<serde_json::Value> {
    let key_bytes = node
        .store
        .load_secret(&frost_share_name(key_id))?
        .ok_or_else(|| format!("no FROST share for key {key_id} on this node"))?;
    let key_package: KeyPackage = serde_json::from_slice(&key_bytes).map_err(err)?;
    let pub_bytes = node
        .store
        .load_public(&frost_pub_name(key_id))?
        .ok_or_else(|| format!("no FROST public package for key {key_id}"))?;
    let pubkey_package: PublicKeyPackage =
        serde_json::from_str(&pub_bytes).map_err(err)?;

    let session = format!("{group}:sign");
    let mut bus = FrostBus::new(node.net.clone(), &node.inboxes, session)?;
    let mut collector = Collector {
        bus: &mut bus,
        stash: Vec::new(),
    };
    let mut rng = OsRng;
    let quorum = signers.len();

    // Round 1: broadcast my signing commitment within the quorum.
    let (nonce, my_commitment) =
        frost::round1::commit(key_package.signing_share(), &mut rng);
    collector
        .bus
        .broadcast("c1", serde_json::to_value(&my_commitment).map_err(err)?)
        .await?;
    let mut commitments: BTreeMap<Identifier, frost::round1::SigningCommitments> =
        BTreeMap::new();
    commitments.insert(identifier(node.me())?, my_commitment);
    for (from, payload) in collector.take("c1", quorum - 1).await? {
        commitments.insert(
            identifier(from)?,
            serde_json::from_value(payload).map_err(err)?,
        );
    }
    let signing_package = SigningPackage::new(commitments, message);

    // Round 2: produce my signature share.
    let my_share =
        frost::round2::sign(&signing_package, &nonce, &key_package).map_err(err)?;
    if !is_aggregator {
        collector
            .bus
            .send_to(
                signers[0],
                "s2",
                serde_json::to_value(&my_share).map_err(err)?,
            )
            .await?;
        return Ok(serde_json::json!({}));
    }
    let mut shares: BTreeMap<Identifier, frost::round2::SignatureShare> = BTreeMap::new();
    shares.insert(identifier(node.me())?, my_share);
    for (from, payload) in collector.take("s2", quorum - 1).await? {
        shares.insert(
            identifier(from)?,
            serde_json::from_value(payload).map_err(err)?,
        );
    }
    let signature =
        frost::aggregate(&signing_package, &shares, &pubkey_package).map_err(err)?;
    pubkey_package
        .verifying_key()
        .verify(message, &signature)
        .map_err(err)?;
    Ok(serde_json::json!({
        "signature": hex::encode(signature.serialize().map_err(err)?),
    }))
}
