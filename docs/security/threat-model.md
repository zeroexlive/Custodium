# Custodium — Threat Model (Phase 0)

> Status: Phase 0 design document. This system is **not production-ready**.
> No statement in this document claims production readiness, completed
> audits, or fitness to custody real funds. Threat modelling is an input
> to design and review, not a guarantee of security.

## 1. Purpose and scope

This document identifies threats to Custodium, an enterprise multi-chain
MPC Wallet-as-a-Service, classifies them in a STRIDE-style framework,
and records mitigations and residual risk for each threat.

In scope:

- Django / Django Ninja API and SaaS control plane.
- PostgreSQL ledger and tenant data, Redis, Temporal workflows.
- Rust threshold signing services: CGGMP threshold ECDSA and
  FROST Ed25519.
- Chain indexers and RPC clients for ETH, BSC, TRON, Solana, TON.
- Token support: USDT and arbitrary tenant-configured tokens.
- Sweep flows, deposit crediting, withdrawals, webhooks, SDKs.

Out of scope (explicitly):

- Custody of fiat, card payments, and exchange trading.
- AML/KYT, sanctions screening, and risk scoring (see
  `docs/blacklist/manual-blacklist.md`; only a manual blacklist exists).
- Security of a tenant's own systems beyond the API boundary.

## 2. Assets

| Asset | Why it matters |
|---|---|
| MPC key shares | Loss/compromise can mean irreversible loss of funds |
| Tenant API credentials (API key + HMAC secret) | Impersonation of a tenant/project |
| Ledger entries (double-entry, integer amounts) | Source of truth for balances |
| Deposit addresses and attribution data | Misattribution steals or strands deposits |
| Signing requests and approved payloads | Substitution diverts withdrawals |
| Sweep resolver configuration | Controls where swept funds go |
| Audit log | Forensics and accountability depend on its integrity |
| Webhook signing secrets | Forged events mislead tenant systems |
| RPC/indexer data | False chain state corrupts crediting decisions |

## 3. Actors

- External unauthenticated attacker.
- Authenticated tenant user abusing their own or another tenant's scope.
- Compromised tenant (their credentials or endpoint are attacker-run).
- Malicious or careless tenant insider.
- Compromised platform component (API, worker, signer, dependency).
- Colluding subset of MPC participants.
- Malicious token contract or malicious sweep resolver operator.

## 4. Trust boundaries

1. Internet -> API edge: all input untrusted, always authenticated.
2. API -> service layer: tenant/project context is established only here.
3. Service layer -> repositories/DB: tenant scoping must survive the call.
4. Control plane -> signer: signer trusts nothing from the caller except
   a validated, policy-checked, canonical signing request.
5. Platform -> chain RPC: RPC responses are untrusted data, not truth.
6. Platform -> tenant endpoints (webhooks, sweep resolver): untrusted,
   potentially hostile servers; SSRF controls apply.
7. Participant -> participant in MPC protocols: threshold assumptions
   hold only below the collusion threshold.

## 5. STRIDE summary

| Category | Example threats in this model |
|---|---|
| Spoofing | Compromised tenant API credentials, API replay |
| Tampering | Signing-request substitution, ledger corruption, RPC manipulation |
| Repudiation | Missing audit for withdrawals, sweeps, blacklist changes |
| Information disclosure | Cross-tenant leaks, share leakage, secret-bearing logs |
| Denial of service | RPC outage, webhook endpoint abuse, indexer lag |
| Elevation of privilege | Broken object-level authorization, compromised Django |

## 6. Threats, mitigations, and residual risk

### T-01 Compromised tenant API credentials

- Scenario: API key/HMAC secret leaks from tenant CI, logs, or phishing;
  attacker calls the API as that tenant/project.
- Mitigations: HMAC over method, path, timestamp, nonce, and body hash;
  short timestamp window; per-key scopes and IP allowlisting (optional);
  rotation and instant revocation; separate keys per environment/project;
  anomaly alerts on first-seen ASN, velocity, and new destinations.
- Residual risk: **High.** A validly signed request is indistinguishable
  from the tenant until behaviour or revocation catches it. Withdrawal
  policy limits and approvals reduce, not eliminate, impact.

### T-02 Broken object-level authorization (BOLA/IDOR)

- Scenario: tenant A guesses wallet/address/transaction IDs of tenant B.
- Mitigations: tenant/project derived from authentication, never body;
  every object lookup scoped by tenant + project; unguessable IDs are
  defence-in-depth only, never the control; negative authorization tests
  for every endpoint (see `tenant-isolation.md`).
- Residual risk: **Medium.** New endpoints can regress; mitigated by
  shared scoped querysets and mandatory cross-tenant test suites.

### T-03 Cross-tenant data leaks

- Scenario: leak via list endpoints, search, exports, webhooks, audit
  views, address lookup, or transaction-hash lookup returning another
  tenant's record.
- Mitigations: scoping at API, service, repository, and DB layers; row
  level security as defence-in-depth; lookup-by-hash/address resolves
  only inside the caller's tenant; webhook payloads contain only the
  owning tenant's data; blacklist entries of other tenants never shown.
- Residual risk: **Medium.** Side channels (timing, existence oracles)
  are reduced by uniform `404` responses for out-of-scope objects.

### T-04 Compromised Django / control plane

- Scenario: RCE or credential theft in the web tier gives attacker the
  ability to craft withdrawal and signing requests.
- Mitigations: signer independently validates policy, tenant, amount,
  destination, blacklist, and the canonical payload hash; control plane
  holds no key shares; least-privilege DB roles; egress allowlists;
  withdrawal approvals for high value; kill switch to suspend signing.
- Residual risk: **High.** A compromised control plane can still attempt
  social/policy attacks and cause denial of service; it must not be
  able to sign alone, and detection relies on signer-side logging.

### T-05 Compromised signer

- Scenario: one signing service/host is fully attacker-controlled.
- Mitigations: threshold signing — a single signer holds one share and
  cannot sign alone; shares in hardened, isolated hosts; signer accepts
  only canonical requests with platform authentication and policy proof;
  per-signer audit log shipped off-host; share refresh/proactive rotation.
- Residual risk: **High if threshold is reached, low otherwise.** Host
  compromise below threshold should leak no usable key material, but
  availability and protocol-abort attacks remain possible.

### T-06 Colluding MPC participants

- Scenario: `t` or more participants (CGGMP ECDSA or FROST Ed25519)
  collude or are co-compromised and reconstruct/sign arbitrarily.
- Mitigations: organisational and geographic separation of participants;
  distinct operators, clouds, and admin domains; threshold set so no
  single operator controls `t` shares; participant identity attestation;
  monitoring of signing sessions (participants, frequency, payloads).
- Residual risk: **High and irreducible by cryptography alone.** Above
  threshold, the scheme's assumption fails. Governance, separation, and
  monitoring are the only controls; document this honestly to tenants.

### T-07 Signing-request substitution

- Scenario: amount, destination, chain, token, or nonce in a request is
  swapped between tenant approval and signing (TOCTOU / confused deputy).
- Mitigations: sign exactly the canonical payload whose hash was
  validated and, where applicable, approved; payload hash bound into the
  signing session; signer re-derives chain transaction from canonical
  fields; any field change creates a new request ID and re-validation;
  blacklist re-check immediately before signing.
- Residual risk: **Medium.** Canonicalisation bugs are the main danger;
  require golden-vector tests for serialisation per chain.

### T-08 Malicious sweep endpoints

- Scenario: tenant-registered sweep resolver is compromised or malicious
  and returns an attacker address, or changes answers over time.
- Rule (non-negotiable): sweep destinations come **only** from a
  tenant-registered HTTPS resolver endpoint that returns a plain-text
  address. A destination is **never** accepted in a sweep request body
  and **never** read from local files.
- Mitigations: resolver URL registered out-of-band by tenant admins;
  HTTPS only; response is plain text, strictly parsed and normalised
  per chain; address re-validated and blacklist-checked per policy;
  resolved address recorded in audit with resolver response hash;
  sudden address change can require step-up confirmation per policy.
- Residual risk: **High for a compromised tenant resolver.** The platform
  cannot distinguish a legitimate rotation from a hostile one without
  tenant-side confirmation policy; the audit trail aids recovery only.

### T-09 SSRF and DNS rebinding

- Scenario: resolver/webhook URLs point at cloud metadata, internal
  services, or rebind from public to private IPs after validation.
- Mitigations: HTTPS only; deny private, loopback, link-local, and
  metadata IP ranges at connect time (not just DNS time); resolve once,
  pin the validated IP for the connection; no redirects, or re-validate
  every redirect hop; short timeouts and response-size caps; egress
  proxy with allowlist semantics for tenant endpoints.
- Residual risk: **Medium.** Novel rebinding/0.0.0.0-style bypasses occur;
  egress proxy and connect-time checks are defence-in-depth.

### T-10 Transaction replay (on-chain)

- Scenario: a signed transaction is rebroadcast, or a signature is
  reused on another chain/network.
- Mitigations: chain-appropriate replay protection (EIP-155 chain ID,
  account nonces, Solana recent blockhash, TRON expiration, TON seqno);
  platform-side nonce allocation with locking; signed payload bound to
  chain ID, network, and wallet; never sign the same payload twice —
  idempotent signing sessions keyed by request ID.
- Residual risk: **Low–Medium.** Cross-fork replay depends on chain
  behaviour after forks; monitor and pause on fork events.

### T-11 API replay

- Scenario: captured signed API request is re-sent to duplicate a
  withdrawal or mutation.
- Mitigations: timestamp window, per-key nonce store, body hash in the
  HMAC, and mandatory `Idempotency-Key` on mutations; replayed nonce or
  expired timestamp is rejected; idempotency returns the original result
  instead of executing twice.
- Residual risk: **Low.** Window/nonce-store outages must fail closed
  for financial mutations.

### T-12 Incorrect attribution

- Scenario: deposit credited to the wrong wallet/tenant/user because of
  address reuse, memo/tag confusion, or indexer parsing errors.
- Mitigations: one deposit address per tenant/project/purpose mapping
  recorded at creation; attribution only from the address/memo registry,
  never from transaction contents guesses; ambiguous deposits are held
  uncredited for manual review; indexer data cross-checked (see T-16).
- Residual risk: **Medium.** Tenant-side address sharing by end users
  can still misattribute at their layer; platform records are auditable.

### T-13 Duplicate deposits

- Scenario: indexer restart, re-scan, or webhook redelivery credits the
  same deposit twice.
- Mitigations: uniqueness on `(chain, tx_hash, output_index/log_index)`;
  idempotent crediting job; double-entry postings keyed by an external
  reference that can be posted once; reconciliation detects duplicates.
- Residual risk: **Low.** Design makes duplication a constraint violation,
  not a silent balance error.

### T-14 Ledger corruption

- Scenario: bug, bad migration, or attacker writes unbalanced or
  mutated ledger entries; balances drift from chain reality.
- Mitigations: append-only double-entry ledger; every transaction's
  debits equal its credits; amounts are exact integers in the smallest
  unit — floats are forbidden anywhere in money paths; DB constraints
  and posting service as the only writer; corrections only as reversing
  entries; periodic reconciliation (see `operations/reconciliation.md`).
- Residual risk: **Medium.** A privileged DB attacker can still damage
  data; backups, PITR, and off-platform audit exports bound the loss.

### T-15 RPC manipulation

- Scenario: compromised/malicious RPC returns false balances, fake
  confirmations, or omits transactions.
- Mitigations: multiple independent RPC providers per chain; quorum /
  cross-check for confirmations and balances used in crediting; verify
  block headers/checkpoints where the chain supports it; never credit
  on a single provider's unconfirmed view; alert on provider divergence.
- Residual risk: **Medium.** Coordinated eclipse of all providers is
  unlikely but possible; confirmation depth is the economic backstop.

### T-16 Malicious tokens

- Scenario: fee-on-transfer, rebasing, pausable, honeypot, or spoofed
  USDT-like token causes wrong crediting or traps funds.
- Mitigations: tokens are explicit per-chain contract/mint registrations;
  credit by measured balance delta, not by transfer-event amount alone;
  decimals read from the registered token, not the event; quarantine
  new tokens behind tenant opt-in; simulation/dry-run for withdrawals.
- Residual risk: **Medium–High for arbitrary tokens.** Tenants enabling
  arbitrary tokens accept contract risk the platform cannot remove.

### T-17 Reorgs

- Scenario: credited deposit or sent withdrawal is reorged out.
- Mitigations: per-chain confirmation thresholds before crediting;
  indexer tracks block hashes and detects reorgs; credits in the reorg
  window are reversible states, not final; withdrawal monitoring until
  finality threshold; automatic re-scan from the fork point.
- Residual risk: **Medium.** Deep reorgs beyond thresholds are a chain
  security failure; thresholds price that risk, they do not erase it.

### T-18 Unauthorized withdrawals

- Scenario: any path that moves funds without valid tenant authority:
  stolen credentials, BOLA, insider abuse, policy bypass.
- Mitigations: layered — authenticated tenant/project, scoped keys,
  withdrawal policy (limits, destinations, approvals), manual blacklist
  checks at validation and immediately before signing, signer-side
  policy enforcement, idempotency, full audit, suspension kill switch.
- Residual risk: **High.** This is the platform's central risk; no single
  control suffices, and residual risk stays material even when layered.

### T-19 Supply-chain compromise

- Scenario: malicious dependency, base image, CI action, or SDK release.
- Mitigations: pinned dependencies with lockfiles and hash checking;
  SBOM generation; signed builds and provenance; dependency review for
  crypto, HTTP, and serialisation libraries; isolated build workers;
  no secrets in CI beyond scoped, short-lived credentials.
- Residual risk: **Medium.** Transitive compromise is hard to exclude;
  pinning and review reduce exposure and improve response time.

## 7. Cross-cutting controls

- Structured audit log for every security-relevant action, append-only.
- Secrets never in logs; key shares never leave signer boundaries.
- Fail closed on financial mutations when auth, nonce, policy, or
  blacklist subsystems are unavailable.
- Regular cross-tenant, replay, and idempotency test suites in CI.

## 8. Review cadence

- Revisit this model on every new chain, token class, signing change,
  or sweep-policy change, and at least quarterly.
- New threats get an ID, an owner, mitigations, and a residual-risk
  statement before the related feature ships.

## 9. Honest limitations

- Threshold cryptography, HMAC, and isolation controls reduce risk;
  none of them, alone or together, make this system production-ready.
- Independent security review, penetration testing, MPC protocol
  review, and operational exercises are still required before any
  real-funds use.
