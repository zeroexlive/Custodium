//! HTTP API.
//!
//! Client surface (`/v1/*`, API token — used by the Django signer
//! client): key creation (runs a DKG ceremony across the node set),
//! public-key lookup, and threshold signing. The node receiving a
//! client request acts as *coordinator*: it starts the session on
//! the participating peers and collects public results. The
//! coordinator never receives key shares.
//!
//! Internal surface (`/internal/*`, cluster token — node-to-node
//! only): session start, session status, and the protocol inbox.

use std::sync::Arc;
use std::time::Duration;

use axum::extract::{Path, State};
use axum::http::{HeaderMap, StatusCode};
use axum::routing::{get, post};
use axum::{Json, Router};
use serde::Deserialize;

use crate::node::{meta_name, Node, SessionStatus, StartSession};
use crate::transport::InboxEnvelope;
use crate::SvcResult;

/// Build the axum router for a node.
pub fn router(node: Arc<Node>) -> Router {
    Router::new()
        .route("/healthz", get(healthz))
        .route("/v1/keys", post(create_key))
        .route("/v1/keys/{key_id}", get(get_key))
        .route("/v1/keys/{key_id}/sign", post(sign))
        .route("/internal/inbox", post(inbox))
        .route("/internal/sessions/start", post(start_session))
        .route("/internal/sessions/{group}", get(session_status))
        .with_state(node)
}

fn authorized(headers: &HeaderMap, token: &str) -> bool {
    headers
        .get("authorization")
        .and_then(|v| v.to_str().ok())
        .map(|v| v == format!("Bearer {token}"))
        .unwrap_or(false)
}

fn fail(status: StatusCode, message: impl Into<String>) -> (StatusCode, Json<serde_json::Value>) {
    (
        status,
        Json(serde_json::json!({"error": message.into()})),
    )
}

async fn healthz(State(node): State<Arc<Node>>) -> Json<serde_json::Value> {
    Json(serde_json::json!({
        "status": "ok",
        "party_index": node.config.party_index,
        "n": node.config.n,
    }))
}

// ----------------------------------------------------------------
// Client API (coordinator role)
// ----------------------------------------------------------------

/// Request body for key creation.
#[derive(Debug, Deserialize)]
pub struct CreateKey {
    /// Key identifier (also the store name stem).
    pub key_id: String,
    /// "secp256k1" | "ed25519"
    pub curve: String,
    /// Threshold.
    pub t: u16,
}

async fn create_key(
    State(node): State<Arc<Node>>,
    headers: HeaderMap,
    Json(body): Json<CreateKey>,
) -> Result<(StatusCode, Json<serde_json::Value>), (StatusCode, Json<serde_json::Value>)> {
    if !authorized(&headers, &node.config.api_token) {
        return Err(fail(StatusCode::UNAUTHORIZED, "bad API token"));
    }
    let out = coordinate_create_key(&node, &body).await;
    match out {
        Ok(meta) => Ok((StatusCode::CREATED, Json(meta))),
        Err(e) => Err(fail(StatusCode::BAD_GATEWAY, e)),
    }
}

async fn coordinate_create_key(node: &Arc<Node>, body: &CreateKey) -> SvcResult<serde_json::Value> {
    crate::store::validate_key_id(&body.key_id)?;
    let flow = match body.curve.as_str() {
        "secp256k1" => "ecdsa-keygen",
        "ed25519" => "frost-keygen",
        other => return Err(format!("unsupported curve {other}")),
    };
    let n = node.config.n;
    if body.t < 2 || body.t > n {
        return Err(format!("threshold must satisfy 2 <= t <= n ({n})"));
    }
    if node.store.load_public(&meta_name(&body.key_id))?.is_some() {
        return Err(format!("key {} already exists", body.key_id));
    }
    let group = uuid::Uuid::new_v4().to_string();
    let start = serde_json::json!({
        "flow": flow,
        "group": group,
        "key_id": body.key_id,
        "t": body.t,
    });
    let all: Vec<u16> = (0..n).collect();
    for peer in &all {
        node.net
            .post_json(*peer, "/internal/sessions/start", &start)
            .await?;
    }
    // Key creation includes ECDSA aux generation (minutes on first
    // key) — allow a long deadline.
    let statuses = await_peers(node, &all, &group, 1800).await?;
    let first = statuses[0]
        .result
        .clone()
        .ok_or("coordinator peer returned no result")?;
    let public_key = first.get("public_key").cloned().unwrap_or_default();
    for st in &statuses {
        let pk = st
            .result
            .as_ref()
            .and_then(|r| r.get("public_key").cloned())
            .unwrap_or_default();
        if pk != public_key {
            return Err("participant nodes disagree on the group public key".into());
        }
    }
    Ok(first)
}

async fn get_key(
    State(node): State<Arc<Node>>,
    headers: HeaderMap,
    Path(key_id): Path<String>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    if !authorized(&headers, &node.config.api_token) {
        return Err(fail(StatusCode::UNAUTHORIZED, "bad API token"));
    }
    match local_meta(&node, &key_id) {
        Ok(Some(meta)) => Ok(Json(meta)),
        Ok(None) => Err(fail(StatusCode::NOT_FOUND, "unknown key")),
        Err(e) => Err(fail(StatusCode::INTERNAL_SERVER_ERROR, e)),
    }
}

/// Request body for signing (fields depend on the key's curve).
#[derive(Debug, Deserialize)]
pub struct Sign {
    /// Participating party indices (exactly t of them).
    pub signers: Vec<u16>,
    /// ECDSA: 32-byte digest, hex.
    #[serde(default)]
    pub digest_hex: Option<String>,
    /// FROST: message, base64.
    #[serde(default)]
    pub message_b64: Option<String>,
}

async fn sign(
    State(node): State<Arc<Node>>,
    headers: HeaderMap,
    Path(key_id): Path<String>,
    Json(body): Json<Sign>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    if !authorized(&headers, &node.config.api_token) {
        return Err(fail(StatusCode::UNAUTHORIZED, "bad API token"));
    }
    match coordinate_sign(&node, &key_id, &body).await {
        Ok(result) => Ok(Json(result)),
        Err(e) => Err(fail(StatusCode::BAD_GATEWAY, e)),
    }
}

async fn coordinate_sign(
    node: &Arc<Node>,
    key_id: &str,
    body: &Sign,
) -> SvcResult<serde_json::Value> {
    let meta = local_meta(node, key_id)?.ok_or_else(|| format!("unknown key {key_id}"))?;
    let curve = meta.get("curve").and_then(|v| v.as_str()).unwrap_or("");
    let t = meta.get("t").and_then(|v| v.as_u64()).unwrap_or(0) as u16;
    if body.signers.len() != t as usize {
        return Err(format!("signer set must contain exactly t={t} parties"));
    }
    let mut sorted = body.signers.clone();
    sorted.sort_unstable();
    sorted.dedup();
    if sorted.len() != body.signers.len() || sorted.iter().any(|&i| i >= node.config.n) {
        return Err("signer set has duplicates or out-of-range indices".into());
    }
    let (flow, extra) = match curve {
        "secp256k1" => (
            "ecdsa-sign",
            serde_json::json!({"digest_hex": body.digest_hex.clone().ok_or("digest_hex required")?}),
        ),
        "ed25519" => (
            "frost-sign",
            serde_json::json!({"message_b64": body.message_b64.clone().ok_or("message_b64 required")?}),
        ),
        other => return Err(format!("unsupported curve {other}")),
    };
    let group = uuid::Uuid::new_v4().to_string();
    let mut start = serde_json::json!({
        "flow": flow,
        "group": group,
        "key_id": key_id,
        "signers": body.signers,
    });
    start
        .as_object_mut()
        .ok_or("internal json error")?
        .extend(extra.as_object().ok_or("internal json error")?.clone());
    for peer in &body.signers {
        node.net
            .post_json(*peer, "/internal/sessions/start", &start)
            .await?;
    }
    let statuses = await_peers(node, &body.signers, &group, 600).await?;
    // Every ECDSA signer returns the same (r, s); the FROST
    // aggregator — the first listed signer — returns the signature.
    let result = statuses[0]
        .result
        .clone()
        .ok_or("result node returned no signature")?;
    if curve == "secp256k1" {
        for st in &statuses {
            if st.result != statuses[0].result {
                return Err("signer nodes disagree on the signature".into());
            }
        }
    }
    Ok(result)
}

fn local_meta(node: &Arc<Node>, key_id: &str) -> SvcResult<Option<serde_json::Value>> {
    match node.store.load_public(&meta_name(key_id))? {
        Some(text) => Ok(Some(serde_json::from_str(&text).map_err(crate::err)?)),
        None => Ok(None),
    }
}

/// Poll peers until all their sessions complete (or one fails).
async fn await_peers(
    node: &Arc<Node>,
    peers: &[u16],
    group: &str,
    timeout_secs: u64,
) -> SvcResult<Vec<SessionStatus>> {
    let deadline = tokio::time::Instant::now() + Duration::from_secs(timeout_secs);
    loop {
        let mut statuses = Vec::new();
        let mut all_done = true;
        for peer in peers {
            let value = node
                .net
                .get_json(*peer, &format!("/internal/sessions/{group}"))
                .await?;
            let st: SessionStatus = serde_json::from_value(value).map_err(crate::err)?;
            if st.state == "failed" {
                return Err(format!(
                    "peer {peer} session failed: {}",
                    st.error.clone().unwrap_or_default()
                ));
            }
            if st.state != "completed" {
                all_done = false;
            }
            statuses.push(st);
        }
        if all_done {
            return Ok(statuses);
        }
        if tokio::time::Instant::now() > deadline {
            return Err(format!("session {group} timed out after {timeout_secs}s"));
        }
        tokio::time::sleep(Duration::from_millis(500)).await;
    }
}

// ----------------------------------------------------------------
// Internal API (node-to-node)
// ----------------------------------------------------------------

async fn inbox(
    State(node): State<Arc<Node>>,
    headers: HeaderMap,
    Json(env): Json<InboxEnvelope>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    if !authorized(&headers, &node.config.cluster_token) {
        return Err(fail(StatusCode::UNAUTHORIZED, "bad cluster token"));
    }
    if let Some(tx) = node.inboxes.sender(&env.session) {
        let _ = tx.send(crate::transport::RawIncoming {
            from: env.from,
            broadcast: env.broadcast,
            msg: env.msg,
        });
    }
    Ok(Json(serde_json::json!({"ok": true})))
}

async fn start_session(
    State(node): State<Arc<Node>>,
    headers: HeaderMap,
    Json(req): Json<StartSession>,
) -> Result<(StatusCode, Json<serde_json::Value>), (StatusCode, Json<serde_json::Value>)> {
    if !authorized(&headers, &node.config.cluster_token) {
        return Err(fail(StatusCode::UNAUTHORIZED, "bad cluster token"));
    }
    node.start_session(req);
    Ok((StatusCode::ACCEPTED, Json(serde_json::json!({"ok": true}))))
}

async fn session_status(
    State(node): State<Arc<Node>>,
    headers: HeaderMap,
    Path(group): Path<String>,
) -> Result<Json<SessionStatus>, (StatusCode, Json<serde_json::Value>)> {
    if !authorized(&headers, &node.config.cluster_token) {
        return Err(fail(StatusCode::UNAUTHORIZED, "bad cluster token"));
    }
    match node.session_status(&group) {
        Some(st) => Ok(Json(st)),
        None => Err(fail(StatusCode::NOT_FOUND, "unknown session")),
    }
}
