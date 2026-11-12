# Custodium MPC Services — SCAFFOLD ONLY (Phase 0)

**Status: SCAFFOLD ONLY — skeleton / Phase 0 repository structure.**

- **No threshold signing is implemented.** Every key-generation and signing
  entry point in this workspace returns `Err(NotImplemented)`.
- **Production signing is disabled** and must stay disabled until a reviewed
  threshold implementation, independent cryptographic review, signer
  deployment review, and realistic end-to-end testnet testing are complete.
  Nothing in this workspace is production-ready and nothing here should be
  used to custody real assets.
- No fake/mock signing, no Shamir secret sharing presented as MPC, and no
  single-key signing disguised as MPC exists in — or may be added to — this
  workspace as a placeholder.

## Intended topology (design only, not deployed)

- **2-of-3** threshold topology as the initial configuration to be validated
  for the selected implementations, with future configurable policies.
- Three independent signer participants, each in a **separate security
  domain** (separate host / account / network controls / custody of its
  share), plus an MPC coordinator that orchestrates sessions but holds no
  share and cannot sign alone.
- Threshold ECDSA (secp256k1) for Ethereum / BSC / TRON; threshold
  Ed25519-compatible signing (FROST, RFC 9591 family) for Solana / TON.

## Non-negotiable boundaries

- **Django can never sign unilaterally.** The Django API has no key shares,
  no signer credentials, and no code path that bypasses independent signer
  policy validation.
- **Key shares are never** stored in PostgreSQL application tables, never
  written to logs, and never returned through any API (dashboard, REST, or
  gRPC — see `packages/proto/mpc/mpc.proto`, which has no field that can
  carry a private share).
- Shares are referenced only by opaque `ShareHandle` identifiers in this
  codebase. Raw private key material types are deliberately absent.
- Every signing request is bound to an approved `SigningIntent` (tenant,
  wallet, network, asset, destination, amount, fee bound, payload hash,
  policy version, expiry). Signers must independently evaluate policy
  against that intent before participating.
- A complete private key is never reconstructed on any participant.

## Candidates pending review (not dependencies yet)

- Threshold ECDSA: the CGGMP protocol family (`cggmp21` crate candidate).
- Threshold Ed25519: FROST (`frost-ed25519` crate candidate, RFC 9591).
- Pinned versions + independent review are required before enablement —
  see the commented placeholders in the workspace `Cargo.toml`.

## Crates

| Crate | Responsibility |
|---|---|
| `shared` | `SigningIntent`, `MpcError`, `ShareHandle`, shared types |
| `signing_policy` | Pure, real policy evaluation for a signing intent |
| `threshold_ecdsa` | ECDSA entry points — fail closed, not implemented |
| `threshold_ed25519` | Ed25519 entry points — fail closed, not implemented |
| `coordinator` | Session orchestration structs — refuse production |
| `signer` | Signer participant structs — refuse production |
| `key_management` | Share-handle lifecycle metadata — no secret material |
| `secure_transport` | mTLS channel configuration validation — no transport yet |

## Verification note

`cargo` is not installed in the current development VM, so `cargo build` /
`cargo test` have **not** been run for this skeleton. Unit tests exist in
`crates/signing_policy` (pure logic) and `crates/secure_transport`; they are
unexecuted until a Rust toolchain is available.
