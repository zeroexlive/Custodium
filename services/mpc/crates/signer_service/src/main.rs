//! Custodium signer node binary.
//!
//! One process per threshold participant. Configuration is
//! environment-only (see `config::NodeConfig::from_env`):
//! SIGNER_PARTY_INDEX, SIGNER_PEERS, SIGNER_BIND, SIGNER_STORE_DIR,
//! SIGNER_STORE_KEY_FILE, SIGNER_API_TOKEN, SIGNER_CLUSTER_TOKEN.
//!
//! The service performs real threshold ceremonies, but it is NOT
//! activated in the Django wiring until the independent
//! cryptographic review passes (docs/mpc/review/); the backend gate
//! is off by default.

use std::sync::Arc;

use custodium_signer_service::{api, config::NodeConfig, node::Node};

#[tokio::main]
async fn main() -> Result<(), String> {
    let config = NodeConfig::from_env()?;
    let bind = config.bind.clone();
    let node: Arc<Node> = Node::new(config)?;
    let listener = tokio::net::TcpListener::bind(&bind)
        .await
        .map_err(|e| format!("bind {bind}: {e}"))?;
    println!(
        "custodium-signer: party {} of {} listening on {}",
        node.config.party_index, node.config.n, bind
    );
    axum::serve(listener, api::router(node))
        .await
        .map_err(|e| format!("serve: {e}"))?;
    Ok(())
}
