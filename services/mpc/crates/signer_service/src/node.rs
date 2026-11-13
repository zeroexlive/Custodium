//! Signer node state and session orchestration.

use std::collections::HashMap;
use std::sync::{Arc, Mutex};

use serde::{Deserialize, Serialize};

use crate::config::NodeConfig;
use crate::store::ShareStore;
use crate::transport::{InboxRegistry, PeerNet};
use crate::SvcResult;

/// Lifecycle state of one session group on this node.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SessionStatus {
    /// "running" | "completed" | "failed"
    pub state: String,
    /// Public result payload on completion (public keys, signatures).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub result: Option<serde_json::Value>,
    /// Error description on failure.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

/// Request to start a session on a node (sent by the coordinator).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StartSession {
    /// "ecdsa-keygen" | "ecdsa-sign" | "frost-keygen" | "frost-sign"
    pub flow: String,
    /// Session group id; stage session ids derive from it.
    pub group: String,
    /// Key identifier the session operates on.
    pub key_id: String,
    /// Threshold (keygen flows).
    #[serde(default)]
    pub t: Option<u16>,
    /// Participating party indices (signing flows).
    #[serde(default)]
    pub signers: Option<Vec<u16>>,
    /// ECDSA: 32-byte digest to sign, hex (signing flow).
    #[serde(default)]
    pub digest_hex: Option<String>,
    /// FROST: message to sign, base64 (signing flow).
    #[serde(default)]
    pub message_b64: Option<String>,
}

/// One signer node.
pub struct Node {
    /// Static configuration.
    pub config: NodeConfig,
    /// Encrypted share store.
    pub store: Arc<ShareStore>,
    /// Peer networking context.
    pub net: PeerNet,
    /// Session inboxes.
    pub inboxes: Arc<InboxRegistry>,
    sessions: Arc<Mutex<HashMap<String, SessionStatus>>>,
    keygen_lock: Arc<tokio::sync::Mutex<()>>,
}

impl Node {
    /// Build a node from configuration (opens the share store).
    pub fn new(config: NodeConfig) -> SvcResult<Arc<Self>> {
        let store = ShareStore::open(&config.store_dir, &config.store_key_file)?;
        let net = PeerNet {
            client: reqwest::Client::new(),
            peers: config.peers.clone(),
            me: config.party_index,
            cluster_token: config.cluster_token.clone(),
        };
        Ok(Arc::new(Self {
            config,
            store: Arc::new(store),
            net,
            inboxes: Arc::new(InboxRegistry::default()),
            sessions: Arc::new(Mutex::new(HashMap::new())),
            keygen_lock: Arc::new(tokio::sync::Mutex::new(())),
        }))
    }

    /// This node's party index.
    pub fn me(&self) -> u16 {
        self.config.party_index
    }

    /// Mark a session group as running.
    pub fn begin_session(&self, group: &str) {
        self.sessions.lock().expect("lock").insert(
            group.to_string(),
            SessionStatus {
                state: "running".into(),
                result: None,
                error: None,
            },
        );
    }

    /// Mark a session group as completed with a public result.
    pub fn complete_session(&self, group: &str, result: serde_json::Value) {
        self.sessions.lock().expect("lock").insert(
            group.to_string(),
            SessionStatus {
                state: "completed".into(),
                result: Some(result),
                error: None,
            },
        );
    }

    /// Mark a session group as failed.
    pub fn fail_session(&self, group: &str, error: String) {
        self.sessions.lock().expect("lock").insert(
            group.to_string(),
            SessionStatus {
                state: "failed".into(),
                result: None,
                error: Some(error),
            },
        );
    }

    /// Current status of a session group, if known.
    pub fn session_status(&self, group: &str) -> Option<SessionStatus> {
        self.sessions.lock().expect("lock").get(group).cloned()
    }

    /// Start a session described by `req` on this node (spawns the
    /// protocol task; returns immediately). Nodes not participating
    /// in a signing quorum mark the session completed-empty at once.
    pub fn start_session(self: &Arc<Self>, req: StartSession) {
        let node = self.clone();
        self.begin_session(&req.group);
        tokio::spawn(async move {
            let result = node.run_session(&req).await;
            for stage in ["aux", "keygen", "sign", "dkg"] {
                node.inboxes.close(&format!("{}:{stage}", req.group));
            }
            match result {
                Ok(value) => node.complete_session(&req.group, value),
                Err(e) => node.fail_session(&req.group, e),
            }
        });
    }

    async fn run_session(self: &Arc<Self>, req: &StartSession) -> SvcResult<serde_json::Value> {
        match req.flow.as_str() {
            "ecdsa-keygen" => {
                let _guard = self.keygen_lock.lock().await;
                crate::ecdsa::run_ecdsa_keygen(self, &req.group, &req.key_id, req.t.unwrap_or(0))
                    .await
            }
            "ecdsa-sign" => {
                let signers = req.signers.clone().unwrap_or_default();
                if !signers.contains(&self.me()) {
                    return Ok(serde_json::json!({}));
                }
                let digest_hex = req.digest_hex.clone().unwrap_or_default();
                let digest = hex::decode(&digest_hex).map_err(crate::err)?;
                let digest: [u8; 32] = digest
                    .try_into()
                    .map_err(|_| "digest must be 32 bytes".to_string())?;
                crate::ecdsa::run_ecdsa_sign(self, &req.group, &req.key_id, &signers, &digest)
                    .await
            }
            "frost-keygen" => {
                let _guard = self.keygen_lock.lock().await;
                crate::frost::run_frost_keygen(self, &req.group, &req.key_id, req.t.unwrap_or(0))
                    .await
            }
            "frost-sign" => {
                let signers = req.signers.clone().unwrap_or_default();
                if !signers.contains(&self.me()) {
                    return Ok(serde_json::json!({}));
                }
                let message = base64::Engine::decode(
                    &base64::engine::general_purpose::STANDARD,
                    req.message_b64.clone().unwrap_or_default(),
                )
                .map_err(crate::err)?;
                let is_aggregator = signers.first() == Some(&self.me());
                crate::frost::run_frost_sign(
                    self,
                    &req.group,
                    &req.key_id,
                    &signers,
                    &message,
                    is_aggregator,
                )
                .await
            }
            other => Err(format!("unknown flow {other}")),
        }
    }
}

/// Store name of the ECDSA share for a key.
pub fn ecdsa_share_name(key_id: &str) -> String {
    format!("ecdsa-{key_id}")
}

/// Store name of the FROST key package for a key.
pub fn frost_share_name(key_id: &str) -> String {
    format!("frost-{key_id}")
}

/// Store name of the FROST public key package for a key.
pub fn frost_pub_name(key_id: &str) -> String {
    format!("frostpub-{key_id}")
}

/// Store name of the public key metadata for a key.
pub fn meta_name(key_id: &str) -> String {
    format!("meta-{key_id}")
}

/// Store name of the reusable ECDSA aux info for this node set.
pub const AUX_NAME: &str = "aux-default";
