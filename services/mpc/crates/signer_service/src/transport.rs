//! Peer transport.
//!
//! Participant nodes exchange protocol messages DIRECTLY with each
//! other over HTTP (`POST /internal/inbox`), authenticated by the
//! cluster token. Two consumers share one inbox mechanism:
//!
//! * the CGGMP protocols run on `round_based`, whose `Delivery`
//!   abstraction is a (Stream, Sink) pair — implemented here with an
//!   inbox-fed stream and an HTTP sink (broadcast = all peers except
//!   self, matching `round_based`'s own simulated network);
//! * the FROST protocols use explicit JSON envelopes through the
//!   same inbox (`FrostBus`).
//!
//! Messages arriving before the local session task has registered
//! its receiver are buffered in an unbounded channel (get-or-create
//! semantics), so session start order across nodes does not matter.
//! Messages for closed sessions are dropped.

use std::collections::{HashMap, HashSet};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};

use futures_util::{Sink, Stream};
use round_based::{Incoming, MessageDestination, MessageType, Outgoing};
use serde::{Deserialize, Serialize};
use tokio::sync::mpsc::{unbounded_channel, UnboundedReceiver, UnboundedSender};

use crate::SvcResult;

/// One raw protocol message as transported between nodes.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RawIncoming {
    /// Sending party index.
    pub from: u16,
    /// Broadcast (all parties) vs point-to-point.
    pub broadcast: bool,
    /// Protocol payload (protocol-specific JSON).
    pub msg: serde_json::Value,
}

/// Envelope posted to a peer's inbox endpoint.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct InboxEnvelope {
    /// Session identifier (unique per ceremony/signing).
    pub session: String,
    /// Sending party index.
    pub from: u16,
    /// Broadcast vs point-to-point.
    pub broadcast: bool,
    /// Protocol payload.
    pub msg: serde_json::Value,
}

/// Registry of per-session inboxes for this node.
#[derive(Default)]
pub struct InboxRegistry {
    senders: Mutex<HashMap<String, UnboundedSender<RawIncoming>>>,
    receivers: Mutex<HashMap<String, UnboundedReceiver<RawIncoming>>>,
    closed: Mutex<HashSet<String>>,
}

impl InboxRegistry {
    /// Get (creating if needed) the sender half for a session.
    /// Returns `None` if the session is already closed.
    pub fn sender(&self, session: &str) -> Option<UnboundedSender<RawIncoming>> {
        if self.closed.lock().expect("lock").contains(session) {
            return None;
        }
        let mut senders = self.senders.lock().expect("lock");
        if let Some(tx) = senders.get(session) {
            return Some(tx.clone());
        }
        let (tx, rx) = unbounded_channel();
        senders.insert(session.to_string(), tx.clone());
        self.receivers
            .lock()
            .expect("lock")
            .insert(session.to_string(), rx);
        Some(tx)
    }

    /// Take the receiver half for a session (once).
    pub fn take_receiver(&self, session: &str) -> Option<UnboundedReceiver<RawIncoming>> {
        // Ensure the channel exists even if no message arrived yet.
        let _ = self.sender(session);
        self.receivers.lock().expect("lock").remove(session)
    }

    /// Close a session: drop its channels, reject late messages.
    pub fn close(&self, session: &str) {
        self.closed.lock().expect("lock").insert(session.to_string());
        self.senders.lock().expect("lock").remove(session);
        self.receivers.lock().expect("lock").remove(session);
    }
}

/// Shared node-to-node HTTP context (client + addressing + token).
#[derive(Clone)]
pub struct PeerNet {
    /// reqwest client (connection pooling).
    pub client: reqwest::Client,
    /// All node base URLs by party index.
    pub peers: Vec<String>,
    /// This node's party index.
    pub me: u16,
    /// Cluster bearer token.
    pub cluster_token: String,
}

impl PeerNet {
    /// POST one envelope to one peer's inbox.
    pub async fn post_inbox(&self, to: u16, env: &InboxEnvelope) -> SvcResult<()> {
        let url = format!(
            "{}/internal/inbox",
            self.peers
                .get(to as usize)
                .ok_or_else(|| format!("unknown peer index {to}"))?
        );
        let resp = self
            .client
            .post(url)
            .bearer_auth(&self.cluster_token)
            .json(env)
            .send()
            .await
            .map_err(crate::err)?;
        if !resp.status().is_success() {
            return Err(format!(
                "peer {to} inbox rejected message: {}",
                resp.status()
            ));
        }
        Ok(())
    }

    /// POST a control-plane JSON call to a peer; returns the JSON body.
    pub async fn post_json(
        &self,
        to: u16,
        path: &str,
        body: &serde_json::Value,
    ) -> SvcResult<serde_json::Value> {
        let url = format!(
            "{}{}",
            self.peers
                .get(to as usize)
                .ok_or_else(|| format!("unknown peer index {to}"))?,
            path
        );
        let resp = self
            .client
            .post(url)
            .bearer_auth(&self.cluster_token)
            .json(body)
            .send()
            .await
            .map_err(crate::err)?;
        let status = resp.status();
        let value: serde_json::Value = resp.json().await.map_err(crate::err)?;
        if !status.is_success() {
            return Err(format!("peer {to} {path} -> {status}: {value}"));
        }
        Ok(value)
    }

    /// GET a control-plane JSON resource from a peer.
    pub async fn get_json(&self, to: u16, path: &str) -> SvcResult<serde_json::Value> {
        let url = format!(
            "{}{}",
            self.peers
                .get(to as usize)
                .ok_or_else(|| format!("unknown peer index {to}"))?,
            path
        );
        let resp = self
            .client
            .get(url)
            .bearer_auth(&self.cluster_token)
            .send()
            .await
            .map_err(crate::err)?;
        let status = resp.status();
        let value: serde_json::Value = resp.json().await.map_err(crate::err)?;
        if !status.is_success() {
            return Err(format!("peer {to} GET {path} -> {status}: {value}"));
        }
        Ok(value)
    }
}

/// Build the `round_based` Delivery pair for one protocol session:
/// an inbox-fed stream of `Incoming<M>` and an HTTP sink of
/// `Outgoing<M>`. Message (de)serialization failures abort the
/// session (fail closed).
///
/// `participants` lists the KEYGEN party indices taking part in
/// this session, in session order. `round_based` addresses parties
/// by their *session* index (0..participants.len()), so the wire's
/// keygen indices are translated in both directions — for a
/// full-set session (keygen, aux) the mapping is the identity; for
/// a signing session with quorum [0, 2], session index 1 is keygen
/// party 2. (Getting this wrong aborts signing with
/// `SenderIndexOutOfRange` — the exact failure the first service
/// test run caught.)
pub fn round_based_delivery<M>(
    net: PeerNet,
    inboxes: Arc<InboxRegistry>,
    session: String,
    participants: &[u16],
) -> (
    impl Stream<Item = Result<Incoming<M>, std::io::Error>> + Unpin,
    impl Sink<Outgoing<M>, Error = std::io::Error> + Unpin,
)
where
    M: serde::Serialize + serde::de::DeserializeOwned,
{
    let rx = inboxes
        .take_receiver(&session)
        .expect("session inbox receiver must exist");
    let counter = Arc::new(AtomicU64::new(0));
    let stream_participants: Vec<u16> = participants.to_vec();
    let stream = futures_util::stream::unfold(
        (rx, counter, stream_participants),
        |(mut rx, counter, participants)| async move {
            match rx.recv().await {
                None => None,
                Some(raw) => {
                    let id = counter.fetch_add(1, Ordering::SeqCst);
                    let sender = participants
                        .iter()
                        .position(|&k| k == raw.from)
                        .map(|p| p as u16);
                    let item: Result<Incoming<M>, std::io::Error> = match sender {
                        Some(sender) => serde_json::from_value::<M>(raw.msg)
                            .map(|msg| Incoming {
                                id,
                                sender,
                                msg_type: if raw.broadcast {
                                    MessageType::Broadcast
                                } else {
                                    MessageType::P2P
                                },
                                msg,
                            })
                            .map_err(|e| {
                                std::io::Error::new(
                                    std::io::ErrorKind::InvalidData,
                                    e.to_string(),
                                )
                            }),
                        None => Err(std::io::Error::new(
                            std::io::ErrorKind::InvalidData,
                            "message from non-participant",
                        )),
                    };
                    Some((item, (rx, counter, participants)))
                }
            }
        },
    );

    let sink_session = session.clone();
    let sink_participants: Vec<u16> = participants.to_vec();
    let sink = futures_util::sink::unfold(net, move |net: PeerNet, out: Outgoing<M>| {
        let session = sink_session.clone();
        let participants = sink_participants.clone();
        async move {
            let value = serde_json::to_value(&out.msg)
                .map_err(|e| std::io::Error::new(std::io::ErrorKind::InvalidData, e.to_string()))?;
            let destinations: Vec<u16> = match out.recipient {
                MessageDestination::AllParties => participants
                    .iter()
                    .copied()
                    .filter(|&i| i != net.me)
                    .collect(),
                MessageDestination::OneParty(j) => vec![*participants
                    .get(j as usize)
                    .ok_or_else(|| std::io::Error::other("recipient out of range"))?],
            };
            let broadcast = matches!(out.recipient, MessageDestination::AllParties);
            for to in destinations {
                let env = InboxEnvelope {
                    session: session.clone(),
                    from: net.me,
                    broadcast,
                    msg: value.clone(),
                };
                net.post_inbox(to, &env)
                    .await
                    .map_err(|e| std::io::Error::other(e))?;
            }
            Ok::<PeerNet, std::io::Error>(net)
        }
    });
    (Box::pin(stream), Box::pin(sink))
}

/// Explicit-envelope bus used by the FROST session logic.
pub struct FrostBus {
    net: PeerNet,
    rx: UnboundedReceiver<RawIncoming>,
    session: String,
}

impl FrostBus {
    /// Create a bus bound to `session`, taking the inbox receiver.
    pub fn new(net: PeerNet, inboxes: &InboxRegistry, session: String) -> SvcResult<Self> {
        let rx = inboxes
            .take_receiver(&session)
            .ok_or_else(|| format!("no inbox for session {session}"))?;
        Ok(Self { net, rx, session })
    }

    /// Broadcast a payload of the given kind to all other parties.
    pub async fn broadcast(&self, kind: &str, payload: serde_json::Value) -> SvcResult<()> {
        let msg = serde_json::json!({"kind": kind, "payload": payload});
        for to in 0..self.net.peers.len() as u16 {
            if to == self.net.me {
                continue;
            }
            self.net
                .post_inbox(
                    to,
                    &InboxEnvelope {
                        session: self.session.clone(),
                        from: self.net.me,
                        broadcast: true,
                        msg: msg.clone(),
                    },
                )
                .await?;
        }
        Ok(())
    }

    /// Send a payload of the given kind to one party.
    pub async fn send_to(
        &self,
        to: u16,
        kind: &str,
        payload: serde_json::Value,
    ) -> SvcResult<()> {
        self.net
            .post_inbox(
                to,
                &InboxEnvelope {
                    session: self.session.clone(),
                    from: self.net.me,
                    broadcast: false,
                    msg: serde_json::json!({"kind": kind, "payload": payload}),
                },
            )
            .await
    }

    /// Receive the next envelope as (sender, kind, payload).
    pub async fn recv(&mut self) -> SvcResult<(u16, String, serde_json::Value)> {
        let raw = self
            .rx
            .recv()
            .await
            .ok_or_else(|| "session inbox closed".to_string())?;
        let kind = raw
            .msg
            .get("kind")
            .and_then(|k| k.as_str())
            .ok_or("envelope missing kind")?
            .to_string();
        let payload = raw.msg.get("payload").cloned().unwrap_or(serde_json::Value::Null);
        Ok((raw.from, kind, payload))
    }
}
