# ADR 0004: CGGMP21 and FROST as Candidate MPC Protocols

- **Status:** Proposed — Accepted for Phase 0/1, NOT Production Approved
- **Date:** 2026-11-12
- **Deciders:** Custodium architecture team
- **Phase scope:** Candidates only. No production signing in Phase 1 or Phase 2.

## Status

Proposed and accepted for Phase 0/1 as CANDIDATES for evaluation only. This decision is NOT Production Approved. Both protocols are PENDING
independent Custodium-specific security review. No production signing is authorised in Phase 1 or Phase 2 under this ADR, under any reading.

## Context

Custodium needs threshold signing for two distinct signature families:

1. **ECDSA** over secp256k1 — required by Ethereum, BSC, TRON, and
   Bitcoin-family chains, plus USDT on those chains.
2. **Ed25519 / Schnorr-family signatures** — required by Solana
   (Ed25519), TON-adjacent uses, and other EdDSA chains.

These are different cryptographic problems. A single protocol does not cover both, and confusing them is itself a serious error — in
particular, FROST is a Schnorr signing scheme, NOT an ECDSA scheme.

Verified background (Phase 0 literature check, 2026-11-12):

### CGGMP21 (threshold ECDSA candidate)

- CGGMP21 is a threshold ECDSA protocol in the Canetti–Gennaro–
  Goldfeder lineage, supporting key generation, signing, and **key refresh** (proactive share rotation without changing the
  public key) — refresh is important for long-lived custody keys.
- The `cggmp21` Rust implementation lineage carries a **Kudelski
  Security audit** — a point in its favour, subject to verifying that the audited version matches the version actually pinned.
- History demands caution: **CVE-2023-33241** ("BitForge") affected
  GG18 / GG20 threshold ECDSA implementations, allowing key extraction in vulnerable implementations. GG18/GG20 are the
  predecessors in this family; the lesson is that implementation and version choice, not just protocol papers, determine safety.
- **TSSHOCK** research disclosed attacks affecting **some CGGMP21
  implementations**. Therefore "CGGMP21" as a protocol name is NOT a safety guarantee: the exact implementation, exact version, and
  its patch status against TSSHOCK-class issues must be pinned, verified, and re-checked continuously.

### FROST / frost-ed25519 (threshold Schnorr / Ed25519 candidate)

- FROST is standardised in **RFC 9591** (FROST: Flexible Round-
  Optimised Schnorr Threshold Signatures).
- The `frost-ed25519` Rust crate implements FROST for Ed25519
  (RFC 8032-compatible signatures as required by Solana et al.).
- The Zcash Foundation FROST implementation was audited by **NCC
  Group in 2023**. The audit scope covered the ciphersuites: **Ed25519, P-256, Ristretto255, and Ed448**.
- Critically, **secp256k1 with Taproot (secp256k1-tr) was OUTSIDE
  that NCC audit scope**. No audit assurance from the 2023 NCC review may be claimed for secp256k1-tr, and Custodium does not
  plan to use FROST for ECDSA chains in any case.
- FROST signs Schnorr-family signatures. It does NOT produce ECDSA
  signatures and cannot serve Ethereum/BSC/TRON. Any design that proposes FROST for an ECDSA chain is rejected on its face.

## Decision

1. **ECDSA candidate: `cggmp21` (Rust)** — designated the candidate
   implementation for threshold ECDSA evaluation, subject to:
   - Pinning an exact version and verifying its audit provenance (Kudelski audit version match) and TSSHOCK patch status.
   - Independent Custodium-specific security review before any use beyond isolated test environments with test keys / testnets.
2. **Ed25519 candidate: `frost-ed25519` (Rust, RFC 9591)** —
   designated the candidate for threshold Ed25519 evaluation, subject to independent review as above. Use is limited to
   Ed25519 ciphersuite claims supported by the NCC 2023 audit scope.
3. **No fake MPC.** Custodium will not ship, market, or describe any
   single-key, sham-MPC, server-side-reconstructed-key, or otherwise simulated threshold scheme as MPC. If threshold signing is not
   genuinely distributed, the feature does not ship.
4. **Isolation:** whichever implementations survive review run as
   isolated Rust services (ADR 0001), orchestrated via Temporal (ADR 0003), never inside Django, never reconstructing a complete
   key on any single host.
5. **Phase gating:** Phase 1–2: evaluation, test vectors, testnet
   experiments with valueless keys only. Production signing requires a separate, later ADR superseding this one, backed by completed
   independent review — see Roadmap Phases 3 and 12.

## Consequences

### Positive

- Two well-studied, standards/audit-adjacent candidates give the
  evaluation a concrete, reviewable target instead of open-ended protocol shopping.
- Key refresh in CGGMP21, if validated, supports proactive custody
  hygiene without address changes.
- RFC 9591 standardisation of FROST aids interoperability, test
  vectors, and reviewer familiarity.

### Negative

- Both candidates carry implementation risk that only review and
  testing can reduce; Phase 3 timelines depend on review outcomes, not just engineering effort.
- Running two distinct threshold stacks (ECDSA + Ed25519) doubles
  the ceremony, backup, and incident-response surface.
- Pinning for audit fidelity conflicts with rapid patching when new
  issues (TSSHOCK-class) appear; both duties require active ownership.

### Neutral / mitigations

- Evaluation harnesses, test vectors, and ceremony transcripts are
  built so an alternative implementation can be substituted if a candidate fails review.

## Alternatives Considered

### A. GG18 / GG20 implementations — Rejected

- Directly implicated by CVE-2023-33241 (BitForge) in vulnerable
  implementations and superseded by CGGMP21. No reason to adopt a predecessor protocol family for new custody in 2026.

### B. Single private key in an HSM / KMS, described as custody — Rejected as "MPC"

- A single key, however well stored, is not threshold signing and
  must never be marketed as MPC. An HSM may still play a role protecting individual shares, by later design decision.

### C. FROST for all chains including ECDSA chains — Rejected (impossible)

- FROST is Schnorr, not ECDSA. It cannot produce valid ECDSA
  signatures for Ethereum/BSC/TRON. See Context above.

### D. Writing a novel threshold protocol in-house — Rejected absolutely

- Custodium does not invent threshold cryptography. Use studied,
  audited-lineage implementations and submit the integration to independent review.

### E. Centralised signing service holding complete keys — Rejected

- Defeats the threshold security model; a single compromise would
  expose complete keys. Incompatible with the product's claims.

## Security Considerations

- **PENDING independent review:** both candidates remain unapproved
  for production until Custodium's own reviewers assess the exact pinned code, ceremony design, share storage, and networking.
- Verify audit-to-version correspondence for the Kudelski (cggmp21)
  and NCC 2023 (FROST) reports; an audit of a different version is background reading, not assurance for the pinned version.
- Continuously monitor disclosures in the TSSHOCK / BitForge class;
  a new implementation CVE is a stop-the-line event for evaluation.
- Share generation, refresh, and signing ceremonies require
  authenticated, encrypted participant channels, transcript logging (without secret material), abort handling, and identifiable-abort
  behaviour where the protocol provides it.
- Shares are stored encrypted at rest, per-participant, with strict
  host separation in any realistic deployment; backups of shares follow the same threshold logic (no single backup reconstructs).
- Test keys and testnet keys are generated in the same ceremony code
  paths as any future production keys — no separate "toy" path that would leave the real path untested — but test material is clearly
  labelled and never co-mingled with value-bearing material.
- Side channels, nonce generation quality, and RNG provenance are
  explicit review items; threshold ECDSA is historically fragile exactly in nonce / presignature handling.

## Review Triggers

Re-open this ADR if any of the following occurs:

- Publication of a new vulnerability affecting the pinned cggmp21
  or frost-ed25519 versions (TSSHOCK-class, BitForge-class, or new).
- Completion — or failure — of the independent security review of
  either candidate; a failed review removes that candidate.
- Any proposed use of FROST secp256k1-tr, or any ciphersuite outside
  the NCC 2023 audit scope, is contemplated.
- RFC 9591 errata, new FROST standards work, or a new CGGMP audit
  materially changes the assurance picture.
- Before ANY production signing, mainnet funds, or external custody
  claim — a superseding ADR with completed review is mandatory.
