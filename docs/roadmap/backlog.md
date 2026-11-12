# Custodium Roadmap Backlog — Phases 0–12
- **Status date:** 2026-11-12
- **Branch context:** `wip-phase-0-phase-1` (Phase 0 / Phase 1 work)
- **Governing rule:** NEVER claim production-ready. No phase, feature,
  or document in this backlog is production-ready unless it has reached the `Production Approved` status defined below — and at
  the status date, nothing has.

## How to Read This Backlog

### Status taxonomy (use exactly these values)
| Status | Meaning |
|---|---|
| `Planned` | Specified, not started. |
| `In Progress` | Actively being built. |
| `Implemented` | Code/docs exist and run in development. |
| `Tested` | Implemented and covered by passing automated tests with recorded evidence. |
| `Security Reviewed` | Tested and passed an independent security review of the relevant scope. |
| `Production Approved` | Security Reviewed, hardened (Phase 12), and explicitly approved for production funds. |
Rules for the taxonomy:
- Status only moves forward on evidence (tests, review reports),
  never on elapsed time or optimism.
- A phase is only as mature as its least mature exit criterion.
- `Implemented` does NOT imply `Tested`; `Tested` does NOT imply
  `Security Reviewed`; nothing implies `Production Approved`.
- At the status date: **Phase 0 is In Progress. Phase 1 is Planned
  (foundation design fixed by ADRs). Phases 2–12 are Planned.**

### Cross-cutting constraints (apply to every phase)
- Stack: Django / Django Ninja / PostgreSQL / Redis / Temporal
  backend; Vue 3 / TypeScript / Tailwind frontend; Rust MPC services.
- Money is exact integer base units; ledger is double-entry,
  append-only, PostgreSQL (ADR 0007). No floats for money, ever.
- No fake MPC. No production signing before independent review
  (ADR 0004). No mainnet funds before Phase 12 gates pass.
- Sweep destinations ONLY via the tenant-registered HTTPS resolver
  returning a plain-text address (ADR 0006) — never in a sweep request, never from local files.
- Screening is manual blacklist only. No AML/KYT integration is in
  scope for any phase in this backlog.
- Every phase ships with tests and updated docs, or it is not done.
---

## Phase 0 — Architecture and Security Foundations
- **Status:** In Progress
- **Goal:** Fix the decisions every later phase depends on, in writing.

### Tasks
- [ ] ADR 0001: modular monolith + isolated MPC + workers.
- [ ] ADR 0002: Django 5.2 LTS on Python 3.12, uv, pinning policy.
- [ ] ADR 0003: Temporal for durable workflows; Redis is not a ledger.
- [ ] ADR 0004: cggmp21 and frost-ed25519 as candidates, pending review.
- [ ] ADR 0005: HMAC-SHA256 API authentication, shown-once secrets,
      envelope-encrypted recoverable storage.
- [ ] ADR 0006: sweep destination resolver rule (binding).
- [ ] ADR 0007: PostgreSQL double-entry ledger, integer money.
- [ ] This backlog and the Phase 1 acceptance document.
- [ ] Threat model v1: tenants, insiders, compromised credentials,
      SSRF via resolver, replay, double-spend, share compromise.
- [ ] Security rules of the house: secrets handling, logging hygiene,
      sandbox/production separation.

### Dependencies
- None. This is the root phase.

### Exit criteria
- All ADRs above exist, are internally consistent, and state
  `NOT Production Approved`.
- Threat model v1 reviewed by the team.
- Phase 1 acceptance criteria agreed (see `phase-1-acceptance.md`).
---

## Phase 1 — Repository and SaaS Foundation
- **Status:** Planned
- **Goal:** A working multi-tenant SaaS skeleton with auth, API keys,
  and HMAC — and no wallet, signing, or fund functionality at all.

### Tasks
- [ ] Repository layout: Django backend, Vue 3 frontend, Compose stack.
- [ ] Docker Compose: Django + PostgreSQL + Redis + Temporal + Vue.
- [ ] User registration, email verification, login, password reset.
- [ ] Organisations (tenants), memberships, roles, invitations.
- [ ] Projects with strict sandbox / production environment separation.
- [ ] API key creation: secret shown once, envelope-encrypted storage,
      revocation, fingerprint display (ADR 0005).
- [ ] HMAC-SHA256 request authentication with timestamp (300s window)
      and nonce anti-replay, plus reference test vectors.
- [ ] Tenant isolation enforced in service/query layers, with tests
      proving cross-tenant access fails.
- [ ] CI: lint, type-check, unit/integration tests on every change.
- [ ] Baseline audit logging for auth and key-management events.

### Dependencies
- Phase 0 ADRs 0001, 0002, 0003, 0005.

### Exit criteria
- All criteria in `docs/roadmap/phase-1-acceptance.md` pass with
  recorded test evidence.
- Explicit non-goals hold: no wallets, no signing, no mainnet funds.
---

## Phase 2 — Wallet and Asset Foundation
- **Status:** Planned
- **Goal:** Wallet/address data model and asset registry on top of
  the ledger design — without live signing.

### Tasks
- [ ] Asset registry: chains, native assets, USDT, arbitrary tokens,
      decimals / base-unit definitions per asset.
- [ ] Wallet model: tenant/project-scoped wallets, purposes, policies.
- [ ] Address records and derivation metadata (no key material in Django).
- [ ] Ledger implementation per ADR 0007: accounts, journal entries,
      postings, balance invariant, append-only enforcement.
- [ ] Reservations, reversals, and idempotency keys in the ledger service.
- [ ] Manual blacklist model and checks (addresses, destinations).
- [ ] Balance read APIs (ledger-derived, exact integers).

### Dependencies
- Phase 1 (tenancy, projects, API auth). ADR 0007.

### Exit criteria
- Ledger invariant tests (debits == credits per entry/asset) pass,
  including concurrency and duplicate-delivery cases.
- No code path stores or displays money as a float.
---

## Phase 3 — MPC Integration (Test-Only)
- **Status:** Planned
- **Goal:** Evaluate cggmp21 (ECDSA) and frost-ed25519 candidates in
  isolated Rust services, with test keys on testnets only.

### Tasks
- [ ] Rust MPC service skeletons, isolated from Django (ADR 0001).
- [ ] DKG / key-generation ceremonies for test wallets.
- [ ] Key refresh evaluation for cggmp21.
- [ ] Signing ceremonies via Temporal orchestration (ADR 0003).
- [ ] Version pinning + audit-provenance verification: Kudelski
      (cggmp21), NCC 2023 scope (FROST: ed25519/p256/ristretto255/ ed448; secp256k1-tr explicitly out of scope).
- [ ] CVE/disclosure watch: BitForge CVE-2023-33241 lessons,
      TSSHOCK-class issues for CGGMP21 implementations.
- [ ] Commission independent security review of both candidates.

### Dependencies
- Phase 2 (wallet model). ADR 0004 review process started.

### Exit criteria
- Testnet signing works end-to-end for evaluated suites.
- Independent review reports received; any failure removes the
  candidate. Still NOT Production Approved, regardless of outcome, until Phase 12.
---

## Phase 4 — Ethereum and BSC
- **Status:** Implemented (2026-11-12) — see
  `docs/blockchains/evm-implementation.md` for the record,
  including the parts of the exit criteria that remain open
  (on-chain testnet round-trip, Temporal wiring).
- **Goal:** First live chains (testnets first): ETH, BNB, USDT, and
  arbitrary ERC-20 / BEP-20 tokens.

### Tasks
- [ ] RPC provider integration, chain/network configuration.
- [ ] Address generation integration with Phase 3 MPC wallets.
- [ ] Transaction construction, gas estimation, nonce management.
- [ ] Withdrawal workflow (Temporal): reserve → sign → broadcast →
      confirm → settle, with idempotency at every step.
- [ ] EVM-specific failure handling: reverts, dropped/replaced txs,
      gas spikes.

### Dependencies
- Phases 2, 3. ADR 0003, ADR 0007.

### Exit criteria
- Testnet deposit→withdraw round-trip reconciles exactly in the ledger.
- No mainnet enablement in this phase.
---

## Phase 5 — Indexing and Balance Lookup
- **Status:** Planned
- **Goal:** Reliable deposit detection and balance lookup for the
  chains enabled so far.

### Tasks
- [ ] Block indexer workers (separate from web processes).
- [ ] Deposit detection with confirmation thresholds per chain/asset.
- [ ] Reorg handling: un-credit / re-credit via reversal entries.
- [ ] Deposit reconciliation workflow (Temporal) crediting the ledger.
- [ ] Balance lookup APIs combining ledger state and on-chain checks.
- [ ] Indexer lag / health metrics and operator alerting.

### Dependencies
- Phases 2, 4.

### Exit criteria
- Reorg and duplicate-event tests pass; no double-credits under
  replayed chain events.
- Reconciliation report: ledger external accounts == on-chain totals.
---

## Phase 6 — TRON
- **Status:** Planned
- **Goal:** TRON support: TRX, USDT-TRC20, and TRC-20 tokens.

### Tasks
- [ ] TRON RPC / TronGrid-style provider integration.
- [ ] Address format handling and validation for TRON networks.
- [ ] Energy/bandwidth resource model in fee estimation.
- [ ] Withdrawal and deposit flows reusing ledger + Temporal patterns.
- [ ] TRON indexing added to the Phase 5 framework.

### Dependencies
- Phases 3 (ECDSA signing), 4/5 patterns.

### Exit criteria
- Testnet round-trip for TRX and USDT-TRC20 reconciles exactly.
---

## Phase 7 — Solana
- **Status:** Planned
- **Goal:** Solana support: SOL and SPL tokens, signed via FROST Ed25519.

### Tasks
- [ ] Solana RPC integration, address / account model mapping.
- [ ] SPL token registry entries and associated token accounts handling.
- [ ] frost-ed25519 signing integration (post Phase 3 review gates).
- [ ] Deposit indexing for Solana's account/slot model.
- [ ] Fee and rent considerations in transaction construction.

### Dependencies
- Phase 3 FROST evaluation outcome; Phases 2, 5.

### Exit criteria
- Testnet SOL + one SPL token round-trip reconciles exactly.
- No use of FROST outside its reviewed ciphersuite scope.
---

## Phase 8 — TON
- **Status:** Planned
- **Goal:** TON support: TON native asset and jettons.

### Tasks
- [ ] TON provider integration and wallet-contract model mapping.
- [ ] Jetton registry and transfer handling (comment/forward payloads).
- [ ] Ed25519 signing integration per Phase 3 gates.
- [ ] Deposit detection for TON's asynchronous message model.
- [ ] Ledger mapping for TON fees and storage costs.

### Dependencies
- Phases 2, 3, 5 patterns.

### Exit criteria
- Testnet TON + one jetton round-trip reconciles exactly.
---

## Phase 9 — Financial Operations
- **Status:** Planned
- **Goal:** The operator-grade finance layer across all enabled chains.

### Tasks
- [ ] Withdrawal policy engine: limits, approval quorums, velocity checks.
- [ ] Manual blacklist enforcement on all outflows (no AML/KYT scope).
- [ ] Fee accounting: chain fees, service fees, exact integer postings.
- [ ] Reconciliation dashboards and discrepancy halt (fail closed).
- [ ] Financial reporting / exports per tenant and project.
- [ ] Refund / reversal operational playbooks using reversal entries.

### Dependencies
- Phases 4–8 (at least one chain live on testnet), ADR 0007.

### Exit criteria
- End-to-end reconciliation across all enabled testnet chains passes
  for a defined soak period with zero unexplained discrepancies.
---

## Phase 10 — Sweeping and Treasury
- **Status:** Planned
- **Goal:** Automated sweeping to tenant treasury destinations —
  obtained ONLY via the registered resolver (ADR 0006).

### Tasks
- [ ] Resolver registration UI/API: HTTPS URL stored in PostgreSQL,
      audited changes, tenant notifications.
- [ ] Resolver client with full SSRF defences (ADR 0006 §4):
      private-IP rejection, no default redirects, strict timeouts, single plain-text address parsing, network validation.
- [ ] Sweep workflow (Temporal): discover → resolve → snapshot
      destination immutably → reserve → sign → broadcast → settle.
- [ ] Fail-closed behaviour on any resolution/validation failure.
- [ ] Sweep policies: thresholds, schedules, gas-aware batching.
- [ ] Tests proving a sweep request cannot carry a destination and
      no local-file destination path exists.

### Dependencies
- ADR 0006 (binding), Phases 4/5, 9.

### Exit criteria
- Penetration-style tests for SSRF and destination-substitution all
  fail closed. Test-resolution tool works in the console.
---

## Phase 11 — SaaS Completion
- **Status:** Planned
- **Goal:** The commercial SaaS surface around the custody core.

### Tasks
- [ ] Plans, quotas, and usage metering per organisation/project.
- [ ] Billing integration and invoicing (fiat billing only; custody
      ledger remains the crypto system of record).
- [ ] Webhooks: signed event delivery with retries and replay tools.
- [ ] Console completion: reporting, team management, audit exports.
- [ ] Public API docs, SDK examples, HMAC signing test vectors.
- [ ] Support tooling with least-privilege, fully audited access.

### Dependencies
- Phase 1 foundation; Phases 9–10 for complete event/webhook surface.

### Exit criteria
- A new tenant can self-serve from signup to testnet operations
  using only published docs.
---

## Phase 12 — Hardening and Production Preparation
- **Status:** Planned
- **Goal:** Prepare — not declare — production readiness. This phase
  produces evidence for a separate production approval decision.

### Tasks
- [ ] Independent security review / penetration test of the full
      system, including MPC integration and the resolver client.
- [ ] Remediation and re-test of all critical/high findings.
- [ ] Key ceremony procedures, share backup/restore drills, and
      incident-response runbooks (compromise, reorg, provider outage).
- [ ] Load, chaos, and disaster-recovery testing (including Temporal
      and PostgreSQL restore drills).
- [ ] Secrets/KMS hardening: HMAC KEK custody (ADR 0005), MPC share
      storage, provider credentials.
- [ ] Compliance and legal review for target jurisdictions.
- [ ] Phased mainnet rollout plan: limits, allow-listed tenants,
      kill switches, monitoring and on-call.

### Dependencies
- All prior phases at `Tested` or better for in-scope features.

### Exit criteria
- Review reports with no open critical/high findings.
- A named, dated, written production approval decision — separate
  from this backlog — for a defined scope. Without that decision, Custodium remains NOT Production Approved, whatever else is true.
