//! Phase 3 evaluation harness — **TEST-ONLY**.
//!
//! This crate exists to evaluate threshold-cryptography candidates
//! (FROST for Ed25519, the CGGMP family for ECDSA) with ephemeral test
//! keys generated in memory, inside a single process, over in-memory
//! message routing. It is the evidence-gathering tool for the Phase 3
//! protocol evaluation — it is **not** a signer, holds no production
//! keys, persists nothing, and must never be linked into a production
//! binary or exposed to a network.
//!
//! Every ceremony here runs with keys that are born and die inside
//! the test process. The production crates remain fail-closed
//! (`NotImplemented` / `ProductionSigningDisabled`) until an
//! independent cryptographic review of the pinned versions and of
//! the eventual production integration is complete.

#![forbid(unsafe_code)]

pub mod ecdsa_eval;
pub mod frost_eval;
