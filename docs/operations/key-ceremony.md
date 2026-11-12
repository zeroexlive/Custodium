# Key Ceremony & Share Lifecycle Procedures

Status: Phase 12 (2026-11-12) — **procedures only**. No key
ceremony may be performed, and production signing stays
disabled, until the independent cryptographic review
(`docs/mpc/review/`) is commissioned and its findings are
closed. This document defines how a ceremony will be run when
that gate opens, so the process itself can be reviewed in
advance.

## Roles

- **Ceremony administrator** — runs the tooling; never a share
  holder.
- **Share holders (3)** — one per signer node/operator domain;
  no person holds two shares; no share holder is the
  administrator.
- **Witness/auditor** — observes, verifies fingerprints and
  transcripts, signs the ceremony record.

## Ceremony (per key family: ECDSA / Ed25519)

1. **Environment**: air-gapped or equivalently isolated
   ceremony machines; verified software artifacts (the pinned
   crates + lockfile from the Phase 3 harness or its reviewed
   successor); versions and hashes recorded in the ceremony
   transcript.
2. **DKG**: run the distributed key generation with all 3
   parties; no party ever sees another's share; the group
   public key is computed and its fingerprint read aloud /
   cross-checked by all participants and the witness.
3. **Verification**: a test signature over a ceremony nonce is
   produced by a 2-of-3 quorum and verified against the group
   key (the same cross-verification pattern the Phase 3/4
   harness tests codify) — on a test network only.
4. **Address registration**: derived addresses are registered
   through the platform's internal `record_derived_address`
   path; wallets move from `provisioning` only after the review
   gate for that deployment is satisfied.
5. **Transcript**: software hashes, public keys, fingerprints,
   participants, timestamps — signed by the witness and stored
   in the audit system of record (never share material).

## Share backup & restore

- Each share is backed up **only** in its operator domain's
  approved encrypted store (HSM/KMS per deployment policy);
  plaintext or cross-domain copies are prohibited.
- **Restore drill (quarterly)**: restore one share to a
  standby node, produce a test-network signature with a quorum
  including the restored share, verify, destroy the drill
  artifacts. Drill outcomes are recorded like a ceremony
  transcript.
- Loss of ≥2 shares = funds-recovery event: the remaining
  share cannot sign; recovery means re-keying is impossible
  for existing addresses — prevention (drills, domain
  separation) is the control; this risk is stated, not hidden.

## Rotation / re-key

Triggered by: suspected compromise, share-holder departure,
or scheduled rotation. cggmp24 (evaluated in Phase 3) has **no
key refresh**: rotation = new DKG + fund migration to new
addresses, planned as a maintenance window with the platform
halt active for the affected scope. FROST Ed25519 supports
share refresh in the standard; use it where the reviewed
deployment enables it.

## Prohibitions (unchanged from Phase 0)

No private key material, shares, or seeds in PostgreSQL, logs,
tickets, chat, or this repository — ever. Django never holds
signing material. Any tooling output that contains share bytes
is treated as a security incident (§2 of incident-response).
