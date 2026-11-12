# System Overview — Custodium Architecture

| Field | Value |
|---|---|
| Phase | Phase 0 design; Phase 1 implements SaaS foundation only |
| Status | Planned (design document; no production claim) |
| Stack | Django / Django Ninja / PostgreSQL / Redis / Temporal; Vue 3 / TS / Tailwind; Rust MPC |

## 1. What Custodium is
An enterprise, multi-tenant, multi-chain MPC Wallet-as-a-Service.
Tenants integrate via API; Custodium handles MPC wallet creation, deposit
address assignment, chain indexing, a double-entry ledger, policy-gated
withdrawals, resolver-based sweeps, webhooks, audit and reconciliation
across Ethereum, BSC, TRON, Solana and TON, for native assets, USDT and
arbitrary registered tokens.

## 2. Design principles
- P-1 No complete private key ever exists in one place (threshold MPC only).
- P-2 No fake MPC: no key reconstruction shortcut, no marketing substitution.
- P-3 Ledger is truth for balances; chain is truth for settlement. Reconcile both.
- P-4 Exact integer money in base units; floats are forbidden in money paths.
- P-5 Append-only history: journals and audit events are never updated/deleted.
- P-6 Policy before signature: Django authorises, MPC independently enforces.
- P-7 Fail closed: resolver, blacklist, policy or quorum failure = no signing.
- P-8 Tenant isolation by default: every query is organisation/project scoped.
- P-9 Durable workflows: Temporal owns multi-step money movement, not requests.
- P-10 Observable by design: ids, metrics and audit on every money operation.

## 3. High-level components
| Component | Tech | Responsibility |
|---|---|---|
| Console | Vue 3 / TS / Tailwind | Tenant + platform admin UI; no secrets, no signing |
| Public API | Django Ninja | REST, OpenAPI, HMAC API-key auth, session auth for console |
| Core domain (`waas/`) | Django modules | Identity, orgs, projects, wallets, ledger, policies, etc. |
| PostgreSQL | — | System of record, ledger, checkpoints, outbox |
| Redis | — | Cache, rate limits, short locks, task fan-out hints |
| Temporal | — | Deposit crediting, withdrawal, sweep, recovery workflows |
| Workers | Django / Python | Chain scanners, event processors, webhook delivery, reconciliation |
| Chain adapters (`chains/`) | Python | Base interface + EVM, TRON, Solana, TON implementations |
| MPC gateway (`integrations/mpc_gateway`) | Python client | Authenticated client to Rust MPC cluster; no share material |
| MPC cluster | Rust | Key generation, threshold ECDSA (CGGMP), FROST Ed25519, policy enforcement |
| RPC providers (`integrations/rpc_providers`) | External | Node access per network/endpoint |
| Sweep resolver (`integrations/sweep_resolver`) | Tenant HTTPS endpoint | Returns plain-text sweep destination at execution time ONLY |
| Notifications (`integrations/notifications`) | External | Email / alert delivery, never money movement |

See `component-diagram.md` for the diagram and `module-responsibility-map.md`
for per-module ownership.

## 4. Request planes
### 4.1 Control plane
- Console + API for configuration: orgs, projects, keys, wallets, policies,
  webhook endpoints, resolver registration, token registration.
- Control-plane writes emit audit events and outbox events.

### 4.2 Data / money plane
- Indexing observes chain transfers; workflows move operations through states.
- Signing requests cross to the MPC cluster only via the MPC gateway, only
  after policy evaluation, blacklist check and (for withdrawals) approvals
  and balance reservation.

### 4.3 Delivery plane
- Outbox events → webhook deliveries (signed, retried) and notifications.
- Metering records API usage asynchronously; it does not gate ledger reads.

## 5. Multi-tenancy model
- Organisation = tenant. Project + Environment = isolation sub-scope.
- Every tenant-owned row carries `organization_id` (directly or via project).
- Service layer resolves tenant scope from the authenticated principal /
  API key — never from a client-supplied organisation id alone.
- Platform-global data is narrow: networks, global asset definitions,
  platform roles. Everything else is tenant-scoped.
- Cross-tenant identifiers are treated as not-found, not forbidden-with-detail,
  to avoid enumeration.

## 6. Chain model
- `chains/base` defines: address validation, transfer parsing, fee estimation,
  broadcast, confirmation/finality, token metadata, reorg signals.
- `chains/evm` is shared by Ethereum and BSC; network config differentiates
  chain id, confirmations, explorer/RPC endpoints and USDT contract.
- `chains/ethereum`, `chains/bsc`: thin network specialisations over EVM.
- `chains/tron`: TRC-20, energy/bandwidth fee model, solidity confirmation.
- `chains/solana`: SPL tokens, slot/commitment finality, rent considerations.
- `chains/ton`: Jettons, workchain addresses, message-based transfers.
- Adapters never write ledger journals directly; they emit normalised
  transfers to indexing / event processing, which the domain validates.

## 7. MPC model (honest scope)
- Key generation is a distributed protocol among MPC participants; each
  participant stores only its share in its own secured store.
- Django stores `KeyShareReference` (opaque locator + metadata) — never shares.
- Threshold ECDSA: CGGMP-family protocol for secp256k1 (ETH/BSC/TRON).
- Threshold Ed25519: FROST for Solana/TON-family curves where applicable.
- Signing is a `SigningSession`: participants produce partial signatures;
  the coordinator assembles a valid signature without reconstructing the key.
- Until a protocol crate is Tested and Security Reviewed (PRD §3 taxonomy),
  it is described as Planned / In Progress — in code, docs and sales material.

## 8. Money movement summary
- **Deposit:** chain transfer → scanner → pending deposit → confirmations →
  Temporal deposit workflow → ledger credit → webhook.
- **Withdrawal:** API request → policy + approvals + blacklist → reservation →
  Temporal withdrawal workflow → signing session → broadcast → confirmation →
  ledger settlement → webhook.
- **Sweep:** trigger → resolver call (HTTPS, plain-text address) → snapshot →
  policy + blacklist → signing → broadcast → treasury ledger movement.
  A sweep is NOT a customer deposit. Destination NEVER comes from the sweep
  request or from local files — resolver only.
- Full sequences: `data-flow.md`. Ledger rules: `ledger-design.md`.

## 9. Consistency and failure model
- PostgreSQL transactions guard ledger + outbox writes (transactional outbox).
- Temporal retries activities with idempotency keys; duplicate delivery of
  chain events, webhooks or RPC responses must not double-credit or double-pay.
- Indexing checkpoints advance only after transfers are durably recorded.
- Reconciliation runs detect ledger↔chain divergence; humans resolve breaks.
- Redis is never the source of truth for balances, reservations or checkpoints.

## 10. Security posture (summary)
- Trust boundaries and controls: `trust-boundaries.md`.
- Blacklist: manual entries only; no AML/KYT provider, no automated scoring.
- HMAC API auth with timestamp + nonce replay protection.
- HTTPS-only for webhooks and sweep resolver; plain-text address response
  from the resolver is validated per-network before use.
- Audit events are append-only and cover security-sensitive actions.

## 11. Deployment summary
- Environments are isolated per deployment tier; secrets via a secrets manager.
- MPC participants are deployed separately from API/workers (see
  `deployment-topology.md`) so compromise of the web tier cannot reach shares.
- No mainnet funds, no production approval in Phase 0/1.

## 12. Phase mapping
| Phase | Delivers |
|---|---|
| Phase 0 | This document set: PRD, architecture, domain, database, security design |
| Phase 1 | SaaS foundation: auth, orgs, projects, API keys/HMAC, console shell, audit, metering skeleton |
| Later (not claimed) | MPC, indexing, deposits, withdrawals, sweeps, reconciliation — each gated by the PRD status taxonomy |

## 13. Related documents
- `docs/prd/product-requirements.md`
- `docs/architecture/component-diagram.md`, `trust-boundaries.md`,
  `deployment-topology.md`, `module-responsibility-map.md`, `data-flow.md`,
  `ledger-design.md`
- `docs/domain/bounded-contexts.md`, `domain-invariants.md`, `ledger-design.md`
- `docs/database/erd.md`, `indexing-strategy.md`
