# Review Scope — Threshold Cryptography & MPC Integration

## A. Pinned upstream artifacts (exact versions in the pin record)

1. `cggmp24` 0.7.0-alpha.2 (+ its `cggmp24-keygen`, `paillier-zk`,
   `fast-paillier` with the rug/GMP backend, `generic-ec`,
   `round-based` dependencies as locked) for threshold ECDSA
   (secp256k1).
2. `frost-ed25519` 3.0.0 / `frost-core` 3.0.0 for FROST Ed25519
   (RFC 9591).

## B. Questions the review must answer

### Upstream usage
1. Is each library used within its documented security assumptions
   (execution-ID uniqueness, signer-index agreement, reliable
   broadcast requirements, aux-info reuse rules for CGGMP)?
2. For `cggmp24`: what is the security status of the alpha line —
   which changes relative to the Kudelski-audited `cggmp21` code are
   security-relevant, and does the RUSTSEC-2025-0127 presignature
   issue class apply to this version's signing paths (with and
   without presignatures)?
3. For `frost-ed25519` 3.0.0: what changed, security-relevantly,
   between the NCC-audited release line and 3.0.0? Is the DKG
   (Pedersen/Feldman VSS with the crate's proof-of-knowledge)
   used correctly, including identifier assignment?
4. Backend choice: `fast-paillier` rug/GMP vs num-bigint — timing /
   side-channel posture for signer deployments.

### Custodium integration (design-stage review in Phase 3;
### implementation review when the production path is built)
5. Transport: mutual authentication, per-message encryption,
   replay protection, and session binding for round-based message
   delivery between coordinator and signers.
6. Signer isolation: process/host separation, share storage
   (encryption at rest, HSM/KMS envelope options), memory hygiene.
7. Policy binding: how a signing intent (chain, address, amount,
   destination, tenant) is bound to a ceremony so signers cannot be
   made to sign a different payload than the one policy approved.
8. Ceremony orchestration: Temporal workflow design (ADR 0003) —
   idempotency, timeout/abort semantics, partial-ceremony cleanup,
   coordinator compromise behaviour (coordinator holds no shares;
   verify that claim in the design).
9. Key lifecycle: DKG ceremony procedure, share backup/recovery
   model, refresh/rotation story (note: `cggmp24` alpha has **no**
   key refresh — the review must assess the compensating controls),
   wallet decommissioning / share destruction.
10. Failure and abuse cases: malicious signer (identifiable abort
    is NOT implemented in the pinned ECDSA candidate — assess),
    malicious coordinator, network adversary, tenant-level abuse.

## C. Out of scope

- Django/dashboard application security (separate review track).
- Chain-specific transaction construction (Phases 4–8 reviews).
- Anything described as "production approval" for versions other
  than the pinned ones.

## D. Deliverables expected from the reviewer

- Written report with severity-rated findings, each mapped to the
  questions above.
- An explicit statement of what was NOT examined.
- A re-test / remediation-verification pass after fixes.
