# Module Responsibility Map — Custodium

| Field | Value |
|---|---|
| Phase | Phase 0 design |
| Status | Planned — modules named here are the intended boundaries |

## 1. How to read this map
Each module owns its models, service functions and invariants. Other modules
call its service interface — they do not import its models for writes, join
across its tables for business logic, or replicate its rules. Shared rules:
integer base-unit amounts, tenant scoping, audit on sensitive actions,
idempotency on external-effect operations, append-only ledger/audit.

## 2. Core modules — `waas/modules/`

### 2.1 `identity`
- Owns: User accounts, credentials, sessions, MFA readiness.
- Does: authentication for console, password hashing, session revocation.
- Does not: tenant authorisation (organisations/permissions), API-key auth.

### 2.2 `organizations`
- Owns: Organization, Membership, Role, Permission, role-permission grants.
- Does: tenant boundary, member invite/remove, permission evaluation helpers.
- Does not: project content, wallets, billing.

### 2.3 `projects`
- Owns: Project, Environment.
- Does: project lifecycle, environment separation (testnet/mainnet), scoping
  root for keys, wallets, webhooks, ledger accounts.
- Does not: network definitions, user membership.

### 2.4 `api_credentials`
- Owns: APIKey (id, hash/secret handling, scopes, status, expiry).
- Does: key creation (secret shown once), HMAC verification support, rotation,
  revocation, last-used tracking feeding metering.
- Does not: user sessions, domain authorisation decisions beyond key scope.

### 2.5 `networks`
- Owns: BlockchainNetwork, NetworkEndpoint.
- Does: network registry, endpoint health/priority, confirmation policy config.
- Does not: RPC calls (rpc_providers), scanning (indexing/scanners).

### 2.6 `assets`
- Owns: Asset, TokenMetadata.
- Does: native/USDT/token registry, decimals, on-chain identifiers, enabling
  an asset on a network for a project.
- Does not: balances (ledger), price data (no pricing in scope).

### 2.7 `wallets`
- Owns: MPCWalletGroup, MPCParticipant, KeyShareReference, Wallet.
- Does: wallet group lifecycle via MPC gateway, wallet creation per network
  family, wallet status.
- Does not: hold share bytes, derive addresses locally, sign anything.

### 2.8 `addresses`
- Owns: WalletAddress, AddressAssignment, ExternalCustomerReference.
- Does: address registration/derivation requests, assignment to end-customer
  references, address history queries (with indexing support).
- Does not: detect deposits (indexing/deposits), move funds.

### 2.9 `transactions`
- Owns: BlockchainTransaction, BlockchainTransfer, TransactionAddressRelation,
  CustodyOperation (base record), TransactionAttempt.
- Does: normalised on-chain transaction/transfer records, operation state
  machine shared by deposits/withdrawals/sweeps, attempt/broadcast tracking.
- Does not: ledger posting (ledger), chain parsing (chains/indexing).

### 2.10 `indexing`
- Owns: IndexingCheckpoint, scanner cursors, raw observation intake.
- Does: per-network scan progress, backfill, reorg markers, handing normalised
  transfers to event processors.
- Does not: credit deposits, decide finality policy (networks + deposits).

### 2.11 `deposits`
- Owns: Deposit.
- Does: deposit lifecycle pending → confirmed → credited / reversed,
  confirmation counting, credit instruction to ledger via deposit workflow.
- Does not: scan chains, post journals directly except through ledger service.

### 2.12 `withdrawals`
- Owns: Withdrawal, WithdrawalApproval.
- Does: withdrawal lifecycle, approval collection, destination validation +
  blacklist check request, reservation request, signing/broadcast coordination
  via workflow.
- Does not: sign (MPC), resolve sweep destinations, edit ledger balances.

### 2.13 `sweeps`
- Owns: SweepDestinationResolver (registration), SweepJob, SweepAttempt,
  ResolvedDestinationSnapshot.
- Does: sweep triggers/thresholds, resolver invocation at execution time,
  snapshot recording, sweep coordination via workflow.
- Hard rule: destinations ONLY from the tenant-registered HTTPS resolver
  returning plain-text address. Never from a sweep request or local files.
- Does not: accept destination addresses as input, treat sweeps as deposits.

### 2.14 `treasury`
- Owns: TreasuryOperation.
- Does: treasury-level movements (sweeps, consolidations, fee funding views),
  treasury balance reporting from ledger accounts.
- Does not: customer balances, ad-hoc transfers outside an operation record.

### 2.15 `ledger`
- Owns: LedgerAccount, JournalEntry, JournalLine, BalanceReservation.
- Does: double-entry posting (balanced, append-only, integer), balance
  derivation, reservation hold/release/consume, reversing journals.
- Does not: know about chains, RPC, MPC; it records economic truth only.
- Full design: `ledger-design.md` in this folder and `docs/domain/`.

### 2.16 `reconciliation`
- Owns: ReconciliationRun (+ break records linked to runs).
- Does: ledger↔chain balance comparison per wallet/address/asset, break
  reporting and resolution workflow (human-decided).
- Does not: silently adjust journals to match chain, or vice versa.

### 2.17 `blacklist`
- Owns: BlacklistEntry.
- Does: manual entry create/remove with reason + actor, lookup by
  network/address for withdrawals and resolved sweep destinations.
- Explicitly: manual only. No AML/KYT integration, no scoring, no provider.

### 2.18 `signing_policies`
- Owns: SigningPolicy (versioned).
- Does: policy definition/evaluation — limits, approvals, velocity,
  destination constraints; supplies policy reference to MPC for re-check.
- Does not: sign, or override MPC-side enforcement.

### 2.19 `webhooks`
- Owns: WebhookEndpoint, WebhookDelivery.
- Does: endpoint registration/secrets, event → delivery creation, signing of
  payloads, retry/dead-letter state (delivery executed by workers).
- Does not: decide domain events (modules emit outbox events).

### 2.20 `audit`
- Owns: SecurityAuditEvent (append-only).
- Does: tamper-evident recording of security-sensitive actions, audit queries.
- Does not: business event analytics (metering), log shipping.

### 2.21 `metering`
- Owns: APIUsageRecord.
- Does: per-key/project usage counting, quota/billing inputs, abuse signals.
- Does not: authentication, rate-limit enforcement logic beyond counters
  shared with Redis at request time.

### 2.22 `platform_admin`
- Owns: platform-level administration surfaces (networks, global assets,
  tenant suspension, endpoint management).
- Does: operator actions with audit + dual-control readiness.
- Does not: tenant fund movement, share access, journal editing, sweep
  destination setting — these paths do not exist for admin.

## 3. Chain adapters — `chains/`
| Module | Owns / does |
|---|---|
| `chains/base` | Adapter interface: validate_address, parse transfers, estimate fee, broadcast, confirmations/finality, token metadata, error taxonomy. All adapters implement this contract. |
| `chains/evm` | Shared EVM logic: ABI/token transfers, gas, nonce, reorg depth, ERC-20. |
| `chains/ethereum` | Ethereum config binding over evm: chain id, USDT contract, confirmation policy defaults. |
| `chains/bsc` | BNB Smart Chain config binding over evm: chain id, USDT contract, faster block cadence. |
| `chains/tron` | TRON adapter: TRC-20, energy/bandwidth, account model, solidity blocks. |
| `chains/solana` | Solana adapter: SPL tokens, associated token accounts, slot/commitment finality. |
| `chains/ton` | TON adapter: jettons, workchains, message-based transfer parsing. |

Adapters emit normalised transfers and accept signed payloads for broadcast.
They never post journals, credit deposits or request signatures.

## 4. Integrations — `integrations/`
| Module | Owns / does | Must not |
|---|---|---|
| `mpc_gateway` | Authenticated client to Rust MPC cluster; DKG/signing session requests; session status mapping to SigningSession | Receive/store shares; bypass policy refs |
| `rpc_providers` | Endpoint selection, RPC client pooling, provider failover, response sanity checks | Decide deposit crediting; hold signing keys |
| `sweep_resolver` | HTTPS call to tenant-registered resolver at sweep execution; plain-text parsing; per-network address validation; snapshot hand-off to sweeps | Cache destinations as standing config; accept destinations from any other source |
| `notifications` | Email/alert sending for operational events (approvals requested, breaks, failures) | Send secrets; move money; replace webhooks |

## 5. Workflows — `workflows/` (Temporal)
| Workflow | Steps (summary) | Idempotency anchor |
|---|---|---|
| `deposit` | Confirm finality → post credit journal → emit webhook event → update deposit state | Deposit id + tx hash + transfer index |
| `withdrawal` | Re-check policy/blacklist/reservation → signing session → broadcast attempt → wait confirmation → settle journal | Withdrawal id + client idempotency key |
| `sweep` | Resolve destination → snapshot → blacklist/policy → aggregate sources → sign → broadcast → treasury journal | SweepJob id + attempt number |
| `recovery` | Participant/share recovery coordination, wallet group recovery drills/state | Recovery operation id |

Workflows orchestrate; domain modules decide; ledger records. Workflows hold
no balances and contain no secrets.

## 6. Workers — `workers/`
| Worker | Does | Consumes / produces |
|---|---|---|
| `chain_scanners` | Poll/stream each network via adapters; advance IndexingCheckpoint; record observations | RPC → indexing intake |
| `event_processors` | Consume outbox + normalised transfers; route to deposits/transactions; publish domain events | OutboxEvent → module services |
| `temporal_workers` | Execute Temporal workflows/activities for deposit, withdrawal, sweep, recovery | Temporal queues |
| `webhook_delivery` | Deliver signed WebhookDeliveries with backoff, dead-letter on exhaustion | WebhookDelivery rows |
| `reconciliation` | Run scheduled/on-demand ReconciliationRuns; report breaks | Ledger + chain balances |

## 7. Ownership and change rules
- A change crossing a module boundary updates this map in the same change set.
- New money movement types require: a CustodyOperation subtype, ledger
  accounts/journals defined, a workflow, audit events, and reconciliation
  coverage — or the feature is not ready to merge.
- Any new destination source for funds requires security review; for sweeps,
  the resolver is and remains the only permitted source.
