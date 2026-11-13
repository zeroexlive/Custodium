//! End-to-end service tests: three real signer nodes (separate
//! processes' worth of state in one test process — separate store
//! dirs, separate store keys, HTTP between them) run actual DKG
//! ceremonies and threshold signing through the client API.
//! Signatures are verified with independent implementations
//! (k256 + ecrecover for ECDSA, ed25519-zebra for Ed25519), and a
//! full node-set restart proves share persistence.

use std::fs;
use std::path::PathBuf;
use std::sync::Arc;

use custodium_signer_service::api;
use custodium_signer_service::config::NodeConfig;
use custodium_signer_service::node::Node;

const API_TOKEN: &str = "test-api-token";
const CLUSTER_TOKEN: &str = "test-cluster-token";
// Each test gets its own port set: cargo runs the tests of one
// binary in parallel, and two clusters on the same ports collide
// (the first workspace run caught exactly that).
const FROST_PORTS: [u16; 3] = [18411, 18412, 18413];
const ECDSA_PORTS: [u16; 3] = [18421, 18422, 18423];

struct TestCluster {
    root: PathBuf,
    handles: Vec<tokio::task::JoinHandle<()>>,
}

fn store_key(i: u16) -> String {
    // Distinct 32-byte store key per node (hex).
    let byte = 0x11u8 + i as u8;
    format!("{byte:02x}").repeat(32)
}

async fn start_cluster(root: &PathBuf, ports: [u16; 3]) -> TestCluster {
    let peers: Vec<String> = ports.iter().map(|p| format!("http://127.0.0.1:{p}")).collect();
    let mut handles = Vec::new();
    for i in 0..3u16 {
        let dir = root.join(format!("node{i}"));
        fs::create_dir_all(&dir).expect("mkdir");
        let key_file = dir.join("store.key");
        if !key_file.exists() {
            fs::write(&key_file, store_key(i)).expect("write store key");
        }
        let config = NodeConfig {
            party_index: i,
            n: 3,
            peers: peers.clone(),
            store_dir: dir.join("store"),
            store_key_file: key_file,
            api_token: API_TOKEN.into(),
            cluster_token: CLUSTER_TOKEN.into(),
            bind: format!("127.0.0.1:{}", ports[i as usize]),
        };
        let node: Arc<Node> = Node::new(config).expect("node");
        let listener = tokio::net::TcpListener::bind(format!("127.0.0.1:{}", ports[i as usize]))
            .await
            .expect("bind");
        handles.push(tokio::spawn(async move {
            let _ = axum::serve(listener, api::router(node)).await;
        }));
    }
    TestCluster {
        root: root.clone(),
        handles,
    }
}

impl TestCluster {
    async fn stop(self) {
        for h in self.handles {
            h.abort();
        }
        // Give sockets a moment to release the ports.
        tokio::time::sleep(std::time::Duration::from_millis(300)).await;
    }
}

fn client() -> reqwest::Client {
    reqwest::Client::new()
}

async fn create_key(port0: u16, curve: &str, key_id: &str) -> serde_json::Value {
    let resp = client()
        .post(format!("http://127.0.0.1:{port0}/v1/keys"))
        .bearer_auth(API_TOKEN)
        .json(&serde_json::json!({"key_id": key_id, "curve": curve, "t": 2}))
        .send()
        .await
        .expect("create key request");
    assert_eq!(resp.status(), 201, "key creation must succeed");
    resp.json().await.expect("json")
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn frost_keygen_sign_and_restart_persistence() {
    let root = std::env::temp_dir().join(format!("signer-frost-{}", uuid::Uuid::new_v4()));
    let cluster = start_cluster(&root, FROST_PORTS).await;

    // Unauthenticated requests are refused.
    let resp = client()
        .post(format!("http://127.0.0.1:{}/v1/keys", FROST_PORTS[0]))
        .json(&serde_json::json!({"key_id": "x", "curve": "ed25519", "t": 2}))
        .send()
        .await
        .expect("request");
    assert_eq!(resp.status(), 401);

    let meta = create_key(FROST_PORTS[0], "ed25519", "frost-wallet-1").await;
    let public_key_hex = meta["public_key"].as_str().expect("public key").to_string();
    let group_key = hex::decode(&public_key_hex).expect("hex");
    assert_eq!(group_key.len(), 32);

    // Sign with quorum [0, 2]; verify with ed25519-zebra.
    let message = b"custodium signer service frost test";
    let sig = sign_frost(FROST_PORTS[0], "frost-wallet-1", message).await;
    verify_zebra(&group_key, &sig, message);

    // Restart the whole node set over the same stores: the shares
    // must load from encrypted disk and sign again.
    cluster.stop().await;
    let cluster2 = start_cluster(&root, FROST_PORTS).await;
    let sig2 = sign_frost(FROST_PORTS[0], "frost-wallet-1", message).await;
    verify_zebra(&group_key, &sig2, message);
    cluster2.stop().await;
}

async fn sign_frost(port0: u16, key_id: &str, message: &[u8]) -> Vec<u8> {
    use base64::Engine;
    let resp = client()
        .post(format!("http://127.0.0.1:{port0}/v1/keys/{key_id}/sign"))
        .bearer_auth(API_TOKEN)
        .json(&serde_json::json!({
            "signers": [0, 2],
            "message_b64": base64::engine::general_purpose::STANDARD.encode(message),
        }))
        .send()
        .await
        .expect("sign request");
    assert_eq!(resp.status(), 200, "signing must succeed");
    let body: serde_json::Value = resp.json().await.expect("json");
    hex::decode(body["signature"].as_str().expect("signature")).expect("hex")
}

fn verify_zebra(group_key: &[u8], signature: &[u8], message: &[u8]) {
    assert_eq!(signature.len(), 64);
    let vk = ed25519_zebra::VerificationKey::try_from(
        <[u8; 32]>::try_from(group_key).expect("32-byte key"),
    )
    .expect("valid key");
    let sig = ed25519_zebra::Signature::try_from(
        <[u8; 64]>::try_from(signature).expect("64-byte signature"),
    )
    .expect("valid signature");
    assert!(vk.verify(&sig, message).is_ok(), "zebra must verify");
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn ecdsa_keygen_sign_and_ecrecover() {
    let root = std::env::temp_dir().join(format!("signer-ecdsa-{}", uuid::Uuid::new_v4()));
    let cluster = start_cluster(&root, ECDSA_PORTS).await;

    let meta = create_key(ECDSA_PORTS[0], "secp256k1", "ecdsa-wallet-1").await;
    let sec1 = hex::decode(meta["public_key"].as_str().expect("public key")).expect("hex");
    assert_eq!(sec1.len(), 65);

    // Sign the Phase 4 Sepolia native-transfer sighash; ecrecover
    // must return the group key's EVM address.
    let digest: [u8; 32] = [
        0xf5, 0x91, 0xbd, 0x8f, 0x35, 0xee, 0xac, 0xa1, 0x77, 0xbf, 0x38, 0x28, 0xc7,
        0x27, 0x90, 0xab, 0x67, 0x0b, 0x38, 0x81, 0x38, 0x56, 0xfd, 0x20, 0xf4, 0xbc,
        0x97, 0x62, 0x6f, 0x3b, 0x8f, 0x5d,
    ];
    let resp = client()
        .post(format!(
            "http://127.0.0.1:{}/v1/keys/ecdsa-wallet-1/sign",
            ECDSA_PORTS[0]
        ))
        .bearer_auth(API_TOKEN)
        .json(&serde_json::json!({
            "signers": [0, 2],
            "digest_hex": hex::encode(digest),
        }))
        .send()
        .await
        .expect("sign request");
    assert_eq!(resp.status(), 200, "ECDSA signing must succeed");
    let body: serde_json::Value = resp.json().await.expect("json");
    let r = hex::decode(body["r"].as_str().expect("r")).expect("hex");
    let s = hex::decode(body["s"].as_str().expect("s")).expect("hex");

    use sha3::Digest as _;
    let group_key = k256::ecdsa::VerifyingKey::from_sec1_bytes(&sec1).expect("valid key");
    let encoded = group_key.to_encoded_point(false);
    let hash = sha3::Keccak256::digest(&encoded.as_bytes()[1..]);
    let expected_address = &hash[12..];

    let mut rs = Vec::with_capacity(64);
    rs.extend_from_slice(&r);
    rs.extend_from_slice(&s);
    let signature = k256::ecdsa::Signature::from_slice(&rs).expect("valid signature");
    let mut recovered_address = None;
    for is_odd in [false, true] {
        let recid = k256::ecdsa::RecoveryId::new(is_odd, false);
        if let Ok(recovered) =
            k256::ecdsa::VerifyingKey::recover_from_prehash(&digest, &signature, recid)
        {
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
    cluster.stop().await;
}
