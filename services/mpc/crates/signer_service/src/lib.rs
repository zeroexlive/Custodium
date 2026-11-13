//! Custodium production MPC signer service (library part).
//!
//! One process per threshold participant. Each node holds exactly
//! one encrypted share per key; shares are never written to the
//! application database, never logged, and never leave the node.
//! Participant nodes exchange protocol messages directly with each
//! other over an authenticated HTTP transport; any node can act as
//! the *coordinator* for a ceremony (starting sessions on peers and
//! collecting public results) without ever seeing other nodes'
//! shares.
//!
//! Status: Implemented + Tested locally (2026-11-13). NOT Security
//! Reviewed and NOT Production Approved: activation in the Django
//! wiring stays behind an explicit default-off gate until the
//! independent cryptographic review (docs/mpc/review/) passes.

pub mod api;
pub mod config;
pub mod ecdsa;
pub mod frost;
pub mod node;
pub mod store;
pub mod transport;

/// Errors surfaced by the signer service (stringified at the API
/// boundary; internal error types of the threshold libraries are
/// not exposed to clients).
pub type SvcResult<T> = Result<T, String>;

/// Stringify any debug-formattable error.
pub fn err<E: std::fmt::Debug>(e: E) -> String {
    format!("{e:?}")
}
