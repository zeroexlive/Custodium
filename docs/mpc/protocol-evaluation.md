# MPC Protocol Evaluation — Threshold ECDSA and FROST Ed25519

Status: Phase 0 — evaluation only. **No protocol in this document
is approved for production signing.** Both candidates below are
PENDING independent review. There is no production signing in
Phase 1 or Phase 2.

> **Phase 3 update (2026-11-12) — §2 is SUPERSEDED.** The executed
> evaluation (`docs/mpc/phase-3-evaluation.md`) **rejects
> `cggmp21`** as the ECDSA candidate (CVE-2025-66016 key
> reconstruction in < 0.6.3; RUSTSEC-2025-0127 presignature forgery
> unpatched in all cggmp21 versions) and evaluates its successor
> `cggmp24` 0.7.0-alpha.2 instead. §3 (FROST) stands, with the
> pinned version now `frost-ed25519` 3.0.0. Read §2 below as the
> Phase 0 historical record only.

## 1. Scope and method

Custodium needs two distinct signature families:

- **Threshold ECDSA** (secp256k1) for Ethereum, BSC, TRON, and
  Bitcoin-family style chains.
- **Threshold Ed25519 / Schnorr** for Solana and TON, which do
  not use ECDSA at all.

A single protocol does not cover both. This document evaluates
one candidate per family using **verified facts only**: claims
below are limited to what the named audits, RFCs, disclosures,
and upstream projects actually state. Anything not verifiable
from those sources is marked as an open question, not asserted.
Marketing claims by any vendor are not evidence.

## 2. Candidate A — CGGMP21 via `dfns/cggmp21` (ECDSA)

### 2.1 Verified facts

- `dfns/cggmp21` is a Rust implementation of the CGGMP21
  threshold ECDSA protocol (Canetti, Gennaro, Goldfeder,
  Makriyannis, Peled), providing DKG and threshold signing for
  secp256k1.
- The implementation was audited by **Kudelski Security**. The
  audit is a real, attributable engagement; its scope and
  findings are those in Kudelski's report, and no broader
  assurance may be inferred from it.
- **Key refresh is supported**: parties can refresh their key
  shares (proactive refresh) without changing the public key /
  wallet address, which is a lifecycle requirement in
  `key-management.md`.
- The predecessor generation matters: **GG18/GG20 were shown to
  have serious flaws by the BitForge research (Fireblocks),
  disclosed as CVE-2023-33241** (with related CVEs) — missing /
  insufficient range proofs and related proof failures that
  could allow key extraction under protocol abuse. Any design
  argument of the form "GG20-class protocols are proven, so
  CGGMP21 inherits that assurance" is invalid: the lineage
  contains a broken generation, which is precisely why the
  specific protocol version and the specific implementation
  both need their own evidence.
- **TSSHOCK**: the TSSHOCK attack research affected **some
  CGGMP21 implementations**. That a protocol paper is sound does
  not imply every implementation of it is; implementation-level
  choices (proof verification, session handling, abort
  behaviour) decide exploitability.

### 2.2 Consequences for Custodium

- Pin an exact `cggmp21` version / commit. Floating versions,
  silent upgrades, and downstream forks are forbidden.
- The pinned version must be specifically reviewed against the
  TSSHOCK findings and the Kudelski audit scope: does the audit
  cover this version, this DKG, this refresh path?
- **Version pinning + review is required** before any testnet
  signing milestone, and a fresh independent review of *our*
  integration (session transport, share storage, coordinator)
  is required separately — upstream's audit does not audit us.
- Identifiable-abort and rogue-party behaviour, presignature
  generation/storage, and nonce handling are explicit review
  items; presignatures, if used, are single-use secrets with
  the same custody class as shares.

## 3. Candidate B — Zcash Foundation FROST (Ed25519)

### 3.1 Verified facts

- The Zcash Foundation's FROST implementation provides Rust
  crates including **`frost-ed25519`**, implementing the FROST
  threshold Schnorr signature protocol.
- FROST is standardised as **RFC 9591** (published June 2024),
  which specifies FROST for several ciphersuites including
  Ed25519.
- **NCC Group audited the FROST implementation in 2023.** The
  audit's ciphersuite coverage was **ed25519, p256,
  ristretto255, and ed448**.
- **`frost-secp256k1-tr` was OUTSIDE that audit scope.** No
  assurance from the NCC Group audit may be claimed for the
  secp256k1 (Taproot) ciphersuite, and Custodium must not cite
  the audit as if it covered it.
- **FROST produces Schnorr / Ed25519 signatures — NOT ECDSA.**
  A FROST share set cannot sign an ECDSA transaction, and a
  CGGMP21 share set cannot sign an Ed25519 transaction. The two
  candidates are complements, never substitutes.

### 3.2 Consequences for Custodium

- Use `frost-ed25519` only, within the audited ciphersuite
  scope, pinned to a reviewed version.
- FROST signing is a two-round protocol with a coordinator;
  nonce commitment handling (binding values, hiding/binding
  nonces per RFC 9591) is a review item because nonce reuse or
  mishandling in Schnorr-family schemes leaks the key.
- DKG for FROST (trusted dealer vs. distributed key generation)
  must be chosen explicitly: a trusted-dealer mode concentrates
  the full key in one place at generation and needs a separate,
  strong justification and ceremony; the default assumption in
  `key-management.md` is a DKG with no party ever holding the
  complete key.

## 4. Chain compatibility caveats

### 4.1 Solana

- Solana uses Ed25519 natively, so `frost-ed25519` output is in
  principle compatible: a FROST aggregate signature verifies as
  an ordinary Ed25519 signature under the group public key.
- Caveats: Solana addresses are the raw Ed25519 public key;
  there is no chain-level notion of a threshold account, so all
  threshold behaviour is off-chain and Custodium-side.
- Program-derived addresses (PDAs) are *not* Ed25519 keypairs
  and cannot be MPC signers; token accounts owned by a wallet
  are distinct from the signing keypair (see `../blockchains/`).

### 4.2 TON

- TON accounts/wallets commonly use Ed25519, but TON wallet
  contracts (v3/v4/v5 families) sign *internal* message payloads
  with wallet-specific seqno / subwallet / valid-until logic; the
  signature is over a constructed cell hash, not a raw tx hash.
- Compatibility therefore depends on the exact wallet contract
  version and on constructing the signable payload through the
  TON adapter — "Ed25519 works" is necessary, not sufficient.
- TON remains a caveated integration: no signing claim is made
  until the adapter + FROST path is reviewed and testnet-proven
  for the specific wallet contract version in use.

### 4.3 ECDSA chains

- Ethereum/BSC (secp256k1, EIP-155 / typed transactions) and
  TRON (secp256k1 over its transaction hash) are in CGGMP21's
  family, subject to per-chain signature encoding (v/r/s,
  recovery id) handled by adapters, never by the MPC layer.

## 5. HD derivation limitations (both candidates)

- Classic BIP32 public derivation assumes a single public key
  with a chain code and non-hardened derivation. Threshold keys
  are not a single held key: **hardened derivation is not
  publicly derivable**, and non-hardened derivation against a
  threshold key requires protocol-specific support that neither
  candidate should be assumed to provide.
- Therefore Custodium MUST NOT promise per-index HD addresses
  from one threshold key as a default. Options, in order of
  preference: (a) one DKG per wallet with addresses produced by
  an explicitly reviewed derivation extension, if the pinned
  library supports it for the needed path types; (b) separate
  key generation ceremonies per address family; (c) chain-
  native account models (e.g. TON wallet contracts, Solana
  token accounts) that do not need HD derivation at all.
- Extended public keys (`xpub`-style) for threshold wallets are
  never exposed as if they were ordinary single-key xpubs.

## 6. Comparison summary

| Dimension | cggmp21 (Candidate A) | frost-ed25519 (Candidate B) |
|---|---|---|
| Signature | ECDSA secp256k1 | Ed25519 Schnorr (FROST) |
| Chains | Ethereum, BSC, TRON | Solana, TON (caveats §4) |
| Standard / paper | CGGMP21 protocol | RFC 9591 (June 2024) |
| Implementation | dfns/cggmp21 (Rust) | Zcash Foundation FROST (Rust) |
| Audit on record | Kudelski Security | NCC Group, 2023 |
| Audit caveat | TSSHOCK hit some CGGMP21 impls | secp256k1-tr outside audit scope |
| Key refresh | Supported | Per FROST refresh design; verify in pinned version |
| Status | PENDING independent review | PENDING independent review |

## 7. Recommendation

1. **Adopt `cggmp21` (dfns, Rust) as the candidate for
   threshold ECDSA**, pinned to a specific version, conditional
   on review against TSSHOCK and the Kudelski audit scope.
2. **Adopt `frost-ed25519` (Zcash Foundation) as the candidate
   for threshold Ed25519**, pinned, used only within the
   NCC-audited ciphersuite scope.
3. **Both are PENDING independent review** of the pinned code
   *and* of Custodium's coordinator, transport, share storage,
   and signing-policy integration. Audit citations in §2–§3 are
   inputs to that review, not substitutes for it.
4. **No production signing in Phase 1–2.** Phases 1–2 may build
   SaaS foundation, APIs, ledger, and indexing with signing
   disabled / testnet-only behind explicit gates. Any mainnet
   signing before the review in (3) completes is out of scope
   for this roadmap and must not be represented as planned.
5. No fake MPC: Custodium never describes a single-server key,
   a database-held seed, or a Shamir-split-then-reconstructed
   key as "MPC" in product, docs, or marketing. If a component
   reconstructs a full key, it is not the design in this doc.

## 8. Open questions for the independent review

- Exact pinned versions and their audit coverage mapping.
- Presignature strategy for CGGMP21 (if any) and its custody.
- FROST DKG variant selection and coordinator trust model.
- Abort/identifiability behaviour and DoS by a malicious or
  offline signer; liveness policy for 2-of-3.
- Side-channel posture of the Rust implementations on our
  signer hosts; memory handling for share material.
