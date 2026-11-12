# Custodium — Product Requirements Document (PRD)

| Field | Value |
|---|---|
| Product | Custodium — Enterprise Multi-Chain MPC Wallet-as-a-Service (WaaS) |
| Phase | Phase 0 (architecture / security docs) and Phase 1 (SaaS foundation) only |
| Status taxonomy | See §3 |
| Current overall status | Planned — unless a requirement is individually marked otherwise |
| Production status | NOT production-ready. No production approval is claimed in this document. |
| Version | 0.1 — Phase 0 draft for review |
| Audience | Engineering, security reviewers, product, tenant platform teams |

> **Non-claim:** Nothing in this PRD asserts production readiness, completed MPC,
> completed audits, or live custody of funds. A feature is only what its status
> label says it is.

## 1. Purpose

Custodium provides tenants (exchanges, fintechs, payment processors, treasuries)
with API-first wallet infrastructure across multiple blockchains, without any
tenant — or any single Custodium component — ever holding a complete private key.

Tenants create organisations and projects, provision MPC wallets, assign deposit
addresses to their end users, observe deposits, request withdrawals under policy,
and sweep deposit balances to tenant-controlled destinations resolved at runtime.

## 2. Mandated stack

### 2.1 Backend
- Python, Django, Django Ninja (typed REST APIs, OpenAPI generation).
- PostgreSQL as system of record; Redis for cache, locks, rate-limit counters.
- Temporal for durable workflows (deposit crediting, withdrawal, sweep, recovery).
- Double-entry, append-only ledger; exact integer arithmetic in base units.

### 2.2 Frontend
- Vue 3, TypeScript, Tailwind CSS.
- Console for organisations, projects, API credentials, wallets, policies,
  transactions, ledger views, webhooks, audit and usage — never key material.

### 2.3 MPC / signing (Rust)
- Rust services, separate from Django.
- Threshold ECDSA based on CGGMP-family protocols for secp256k1 chains.
- FROST threshold Ed25519 for Solana / TON-family signing where applicable.
- **No fake MPC:** no single-process key reconstruction, no Shamir-split-then-
  recombine-in-one-service shortcut presented as MPC, no stored complete keys.
- If a protocol implementation is not finished and reviewed, its status is
  Planned / In Progress — never Implemented by assertion alone.

### 2.4 Chains and assets (target scope)
- Ethereum (ETH), BNB Smart Chain (BSC), TRON (TRX), Solana (SOL), TON.
- USDT on each supported network where USDT is natively issued.
- Arbitrary tokens: ERC-20 (ETH/BSC), TRC-20 (TRON), SPL tokens (Solana),
  TON jettons — registered by contract/mint/jetton-master address + decimals.
- Native assets and tokens share the same deposit / withdrawal / ledger model,
  parameterised by network and asset, not by per-token code forks.

## 3. Status taxonomy (used everywhere)

| Status | Meaning |
|---|---|
| Planned | Designed or intended; no implementation claimed. |
| In Progress | Active work; incomplete, not usable as finished. |
| Implemented | Code exists and behaves as specified in a dev environment. |
| Tested | Implemented plus automated / manual test evidence recorded. |
| Security Reviewed | Tested plus documented security review by a qualified reviewer. |
| Production Approved | Security Reviewed plus explicit production sign-off. |

Rules:
- Status only moves forward with evidence (tests, review record, sign-off).
- Phase 0 delivers documents. Phase 1 delivers SaaS foundation only (§10).
- No requirement in Phase 0/1 is Production Approved.
- Marketing, README and API docs must reuse these labels verbatim.

## 4. Personas

### 4.1 Tenant Organisation Admin
- Owns organisation, invites members, assigns roles, creates projects.
- Registers sweep destination resolver endpoints; cannot set sweep addresses
  directly in a sweep request (see FR-SWP-01).

### 4.2 Tenant Developer / Integrator
- Creates API keys, integrates HMAC-signed API calls, registers webhooks,
  registers tokens, creates wallets and address assignments via API.

### 4.3 Tenant Treasury Operator
- Views balances, initiates / approves withdrawals under signing policy,
  monitors sweeps and treasury operations, reviews reconciliation breaks.

### 4.4 Tenant End Customer (indirect)
- Not a Custodium user. Identified only by `ExternalCustomerReference`.
- Receives a deposit address assigned by the tenant; sends funds on-chain.

### 4.5 Platform Admin (Custodium operator)
- Operates networks, endpoints, global assets, metering, tenant suspension.
- Cannot unilaterally move tenant funds, bypass signing policy, or read key shares.

### 4.6 Security Reviewer / Auditor (read-oriented)
- Reads audit events, signing sessions, policy versions and ledger journals.
- Verifies invariants; has no operational write path to funds.

### 4.7 Approver (tenant, policy-defined)
- One of N approvers for withdrawals above thresholds / to new destinations.
- Approval is recorded as `WithdrawalApproval`; approval alone never signs.

## 5. Problem statement
- Building multi-chain custody in-house forces each tenant to solve key
  management, chain indexing, reorgs, fee management, ledger correctness and
  reconciliation independently — high risk, slow, and error-prone.
- Single-key hot wallets create a single point of compromise.
- Ad-hoc ledgers (float balances, mutable rows) fail audits and reconciliation.

## 6. Goals and non-goals

### 6.1 Goals
- G-1: No complete private key exists in any one place at any time.
- G-2: One consistent API / ledger model across ETH, BSC, TRON, Solana, TON.
- G-3: Provable balances: every balance is derivable from journal lines.
- G-4: Policy-gated signing: no signature without a passing policy evaluation.
- G-5: Observable money movement: deposits, withdrawals, sweeps are distinct,
  auditable operation types — a sweep is never disguised as a customer deposit.

### 6.2 Non-goals (Phase 0/1 and general)
- NG-1: No retail wallet app, no direct end-customer accounts.
- NG-2: No exchange, swap, lending, staking-as-a-product, or fiat on/off-ramp.
- NG-3: No AML/KYT screening product. Blacklist is manual only (FR-BLK-01).
- NG-4: No support for chains beyond §2.4 without a new chain-adapter design.
- NG-5: No production custody claim until Production Approved per §3.

## 7. Functional requirements

### 7.1 Identity, organisations, projects
- FR-IDN-01 (Planned): Email/password + MFA-ready user accounts; sessions revocable.
- FR-IDN-02 (Planned): Users belong to organisations via Membership with a Role.
- FR-ORG-01 (Planned): Organisation is the tenant isolation boundary for all data.
- FR-ORG-02 (Planned): Roles carry Permissions; authorisation checks permission,
  not role name, at the service layer.
- FR-PRJ-01 (Planned): Projects belong to one organisation; Environments
  (e.g. testnet/mainnet separation) belong to one project.
- FR-PRJ-02 (Planned): All wallets, keys, webhooks and ledger accounts are
  scoped to a project/environment; cross-scope access must be denied and audited.

### 7.2 API credentials
- FR-API-01 (Planned): API keys are per project/environment, shown once at creation.
- FR-API-02 (Planned): API requests authenticated by key id + HMAC signature
  over method, path, body hash, timestamp and nonce; replay window enforced.
- FR-API-03 (Planned): Keys are revocable, rotatable, scoped by permission,
  and never accepted in query strings or logged in full.

### 7.3 Networks and assets
- FR-NET-01 (Planned): Platform-admin-managed BlockchainNetwork registry with
  chain identifiers, confirmation policy and NetworkEndpoints (RPC providers).
- FR-AST-01 (Planned): Asset registry for native assets and USDT per network.
- FR-AST-02 (Planned): Tenants/platform register arbitrary tokens by on-chain
  identifier + decimals; decimals are immutable once deposits exist.
- FR-AST-03 (Planned): Amounts are integers in base units everywhere in APIs
  that move money; decimal rendering is a presentation concern only.

### 7.4 Wallets and addresses
- FR-WAL-01 (Planned): MPCWalletGroup represents a threshold key group;
  MPCParticipant + KeyShareReference record where shares live — never share bytes.
- FR-WAL-02 (Planned): Wallet belongs to a wallet group + network family;
  WalletAddress is derived per network and may be assigned to an end customer.
- FR-WAL-03 (Planned): AddressAssignment links an address to an
  ExternalCustomerReference; an address is not silently reassigned while it
  holds a balance or has pending deposits.
- FR-WAL-04 (Planned): Address generation must not require exporting key material
  to Django; derivation goes through the MPC gateway.

### 7.5 Deposits and indexing
- FR-DEP-01 (Planned): Chain scanners track IndexingCheckpoints per network/
  endpoint and detect transfers to known WalletAddresses.
- FR-DEP-02 (Planned): A deposit is credited only after the network's
  confirmation / finality policy is met; pending and credited are distinct states.
- FR-DEP-03 (Planned): Reorg handling reverses un-credited observations and
  must never silently delete a credited journal — reversal is a new journal.
- FR-DEP-04 (Planned): Deposit credit posts a balanced double-entry journal.

### 7.6 Withdrawals
- FR-WDR-01 (Planned): Withdrawal is a CustodyOperation with amount (integer
  base units), asset, source wallet, destination address supplied by tenant,
  idempotency key and policy evaluation.
- FR-WDR-02 (Planned): Withdrawals above policy thresholds require the configured
  number of WithdrawalApprovals before a SigningSession is opened.
- FR-WDR-03 (Planned): Balance is reserved (BalanceReservation) before signing;
  insufficient available balance fails closed.
- FR-WDR-04 (Planned): Broadcast is a TransactionAttempt; confirmation updates
  the operation; failure releases or re-reserves per workflow rules, never
  double-spends the reservation.
- FR-WDR-05 (Planned): Blacklisted destinations are rejected before signing.

### 7.7 Sweeps
- FR-SWP-01 (Planned) — **Sweep destination rule (absolute):** Sweep destinations
  are obtained ONLY by calling a tenant-registered HTTPS resolver endpoint
  (`SweepDestinationResolver`) at sweep execution time. The resolver returns a
  plain-text address. A sweep destination must NEVER be supplied in the sweep
  request, in local files, in environment variables, or in console form fields.
- FR-SWP-02 (Planned): Each resolution is stored as a ResolvedDestinationSnapshot
  (resolver id, resolved address, timestamp, response hash) for audit.
- FR-SWP-03 (Planned): If the resolver is unreachable, returns non-HTTPS,
  non-plain-text, malformed or blacklisted output, the sweep fails closed.
- FR-SWP-04 (Planned): A sweep is a TreasuryOperation / SweepJob moving funds
  from deposit wallets toward the resolved destination. It is NOT a customer
  deposit and must not create customer deposit records or credits.
- FR-SWP-05 (Planned): SweepJobs have thresholds, schedules/triggers and
  SweepAttempts; partial failures are retried by Temporal, not by duplicate jobs.

### 7.8 Ledger and reconciliation
- FR-LED-01 (Planned): Every money movement is a balanced JournalEntry with
  ≥2 JournalLines; debits equal credits per asset.
- FR-LED-02 (Planned): Journals are append-only; corrections are reversing journals.
- FR-LED-03 (Planned): No floats anywhere in money paths (see ledger design docs).
- FR-REC-01 (Planned): ReconciliationRuns compare ledger-derived balances with
  on-chain balances per wallet/address/asset; breaks are reported, not auto-fixed.

### 7.9 Blacklist
- FR-BLK-01 (Planned): Blacklist is **manual only** — entries are created by
  authorised tenant/platform users with a reason. There is NO AML/KYT provider,
  no automated screening, no third-party risk scoring in scope.
- FR-BLK-02 (Planned): BlacklistEntry is checked for withdrawal destinations
  and resolved sweep destinations before signing.

### 7.10 Signing policies, webhooks, audit, metering
- FR-POL-01 (Planned): SigningPolicy versions govern amount limits, approval
  counts, destination constraints and velocity; the MPC signer enforces policy
  independently of Django (defence in depth).
- FR-WHK-01 (Planned): WebhookEndpoints receive signed WebhookDeliveries for
  deposit, withdrawal, sweep and wallet events; deliveries are retried with
  backoff and are replayable by id.
- FR-AUD-01 (Planned): SecurityAuditEvents are append-only for auth, key,
  policy, wallet, withdrawal-approval and admin actions.
- FR-MET-01 (Planned): APIUsageRecords meter requests per key/project for
  quotas, billing input and abuse detection; metering never blocks ledger reads
  retroactively.

## 8. Non-functional requirements
- NFR-SEC-01: Tenant isolation enforced in queries, object permissions and tests.
- NFR-SEC-02: Secrets (API HMAC secrets, RPC credentials, share references)
  are stored via a secrets manager / encrypted fields; never in logs or repos.
- NFR-SEC-03: All external callbacks (webhooks, sweep resolver) are HTTPS only.
- NFR-REL-01: Temporal workflows survive worker restarts; no money step relies
  on in-memory state alone.
- NFR-REL-02: Indexing is resumable from IndexingCheckpoint after outage.
- NFR-OBS-01: Structured logs, metrics and traces carry organisation/project/
  operation ids — never secrets, never complete key or share material.
- NFR-PERF-01: Address-history and tx-hash lookups are indexed (see
  `docs/database/indexing-strategy.md`); full scans are not an access pattern.
- NFR-ACC-01: Every balance shown in console/API is reproducible from journals.
- NFR-COMP-01: Audit events retained per tenant policy; export must not leak
  cross-tenant data.

## 9. Phase 1 scope (SaaS foundation)
In scope: auth, organisations, memberships/roles/permissions, projects,
environments, API keys + HMAC verification, platform network/asset registry
(read models), console shell, audit events, metering skeleton.
Out of scope for Phase 1: live MPC signing, live indexing, live withdrawals/
sweeps, production RPC credentials, any mainnet funds.

## 10. Acceptance criteria (Phase 0)
- AC-1: Architecture, domain, database and security docs exist and cross-reference.
- AC-2: Every module in the module responsibility map has an owner boundary.
- AC-3: ERD covers all entities named in the data model list.
- AC-4: Sweep resolver rule and manual-blacklist rule appear consistently.
- AC-5: No document claims Implemented/Tested/Security Reviewed/Production
  Approved status without evidence.

## 11. Risks and open questions
- R-1: CGGMP / FROST implementation and audit timelines gate all signing claims.
- R-2: TON and TRON finality/reorg semantics differ from EVM; per-network
  confirmation policies must be validated on testnets first.
- R-3: Resolver availability is tenant-side; sweep SLAs must state fail-closed.
- OQ-1: Quorum sizes / participant placement per tenant tier — undecided.
- OQ-2: Fee-payer model for TRON energy / Solana rent / TON — undecided.
