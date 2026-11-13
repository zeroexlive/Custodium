//! Node configuration (environment-driven; no secrets in code).

use std::path::PathBuf;

/// Static configuration of one signer node.
#[derive(Debug, Clone)]
pub struct NodeConfig {
    /// This node's party index, `0..n`.
    pub party_index: u16,
    /// Total number of participant nodes.
    pub n: u16,
    /// Base URLs of ALL nodes (index = party index), including self.
    pub peers: Vec<String>,
    /// Directory holding encrypted shares + public metadata.
    pub store_dir: PathBuf,
    /// File containing the 32-byte share-store encryption key
    /// (64 hex chars or exactly 32 raw bytes). One per node; never
    /// shared between nodes, never the API/cluster token.
    pub store_key_file: PathBuf,
    /// Bearer token for the client API (`/v1/*`) — Django's credential.
    pub api_token: String,
    /// Bearer token for node-to-node endpoints (`/internal/*`).
    pub cluster_token: String,
    /// HTTP bind address for the standalone binary.
    pub bind: String,
}

impl NodeConfig {
    /// Load configuration from environment variables (binary mode).
    pub fn from_env() -> Result<Self, String> {
        let get = |k: &str| std::env::var(k).map_err(|_| format!("missing env {k}"));
        let peers: Vec<String> = get("SIGNER_PEERS")?
            .split(',')
            .map(|s| s.trim().trim_end_matches('/').to_string())
            .filter(|s| !s.is_empty())
            .collect();
        let party_index: u16 = get("SIGNER_PARTY_INDEX")?
            .parse()
            .map_err(|_| "SIGNER_PARTY_INDEX must be a number")?;
        if peers.len() < 2 {
            return Err("SIGNER_PEERS must list at least 2 node URLs".into());
        }
        if (party_index as usize) >= peers.len() {
            return Err("SIGNER_PARTY_INDEX out of range for SIGNER_PEERS".into());
        }
        Ok(Self {
            party_index,
            n: peers.len() as u16,
            peers,
            store_dir: PathBuf::from(get("SIGNER_STORE_DIR")?),
            store_key_file: PathBuf::from(get("SIGNER_STORE_KEY_FILE")?),
            api_token: get("SIGNER_API_TOKEN")?,
            cluster_token: get("SIGNER_CLUSTER_TOKEN")?,
            bind: std::env::var("SIGNER_BIND").unwrap_or_else(|_| "0.0.0.0:8401".into()),
        })
    }
}
