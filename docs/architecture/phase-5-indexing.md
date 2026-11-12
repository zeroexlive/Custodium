# Indexing & Balance Lookup — Phase 5 Implementation Record

Status: **Implemented** (2026-11-12). Code:
`apps/backend/waas/modules/indexing/` (+ block/log reads added to
the Phase 4 EVM provider). Scope: the EVM chains enabled in
Phase 4. Other families get their scanners in their own phases
(6 TRON, 7 Solana, 8 TON) reusing this module's models and
lifecycle.

## 1. What was built

| Piece | Notes |
|---|---|
| `ChainCursor` + `ScannedBlock` | Per-network scan position and a trailing 512-block hash window — the evidence the reorg walk-back compares against the live chain. |
| `ObservedDeposit` | One row per chain deposit event; uniqueness `(network, tx_hash, occurrence, block_hash)`. |
| Scanner (`indexing/services.py`) | Reorg check → block scan (native transfers receipt-verified; ERC-20/BEP-20 via `Transfer` logs) → confirmation pass. Runs inside one DB transaction per pass. |
| Deposit lifecycle | Detection posts `DEPOSIT_OBSERVED` (Dr custody_pending / Cr customer_pending); at the network's `confirmations_required` one balanced `DEPOSIT_CREDIT` entry moves pending → on-chain custody and pending → available. Deposit scope matches the Phase 4 withdrawal scope (`external_customer_id` / `wallet:<id>`). |
| Reorg handling | Walk-back orphans blocks whose hashes no longer match; every deposit in an orphaned block is un-credited **via ledger reversal entries** (the journal is never edited), then the fork is rescanned. A transaction that reappears in the new fork starts a fresh lifecycle as a new row. |
| Blacklist hold | A deposit whose sender is on the manual blacklist is observed (funds visible in pending) but **held**: never auto-credited, flagged for manual review. |
| Worker entrypoint | `manage.py run_indexer [--network slug] [--max-blocks N] [--until-caught-up]` — a separate process from the web tier, printing a per-pass report (head, scanned range, detected, credited, reorg depth, lag). Scheduling is the deployment's job. |
| Reconciliation | `reconciliation_report(network)`: per asset, expected custody (observed deposits − settled withdrawals) vs ledger custody (Σ custody_onchain + custody_pending); `balanced` flag and exact difference. |
| Lookup API | `GET /transactions/lookup` — the Phase 1 501 gate is gone. Implements the Phase 0 design (`docs/api/transaction-lookup.md`): 422 for unknown network / malformed hash, tenant projection for own transactions, **public projection** for other tenants' indexed transactions (no platform metadata — not an existence oracle), 404 for unindexed hashes, audit event per lookup. RPC fallback (design step 6) is policy-gated OFF: local index only. |
| Deposits API | `GET /wallets/{id}/deposits` (tenant-scoped, 404 discipline). Dashboard client + types added; the Phase 1 Transaction Explorer view now works against the real endpoint (network list corrected to registry slugs). |

## 2. Exactly-once argument

Three independent layers, each tested:

1. Deposit uniqueness key includes the block hash → replaying the
   same block is a no-op (`get_or_create`).
2. Every journal posting carries a deterministic idempotency key
   (`deposit:<id>:observed|credit|reverse-*`) → even a crash
   between row creation and posting cannot double-post.
3. The confirmation pass only touches `pending` rows and flips
   status in the same transaction as the credit posting.

The replay test wipes cursor + scanned blocks and rescans the
whole chain: one deposit row, balances unchanged, trial balance 0.

## 3. Verification performed

Backend suite: see `AGENTS.md` for the exact count. Scenario tests
(in-memory chain double with fork support): native deposit
lifecycle pending → credited with per-stage balances; token
deposit via Transfer log; failed (reverted) transaction ignored;
full replay exactly-once; **reorg before credit** (observation
reversed, pending balances zeroed); **reorg after credit** (both
entries reversed, everything zeroed); blacklisted sender held;
reconciliation balanced; lookup matrix (owner full projection /
other tenant public projection / unindexed 404 / malformed 422)
and deposits-list tenant isolation. The Phase 1 gate test was
updated: lookup now answers 422 (project context required) instead
of 501; the sweep gate still 501s.

## 4. NOT verified / deferred

- **Live chain scanning**: same sandbox egress limitation as
  Phase 4 — the scanner is verified against the in-memory chain
  double implementing the provider surface, not against a live
  node. Re-run against Sepolia from an open network before any
  testnet enablement.
- **Deposit crediting via Temporal**: the backlog names a Temporal
  reconciliation workflow; the lifecycle here is a synchronous
  service with the same step boundaries (Temporal remains unwired,
  as in Phase 4).
- **Indexer lag alerting**: the pass report exposes lag per
  network; wiring it into an alerting system is an operations
  (Phase 12) concern.
- **Balance lookup combining on-chain checks**: the balances API
  (Phase 2) is ledger-only by design; the reconciliation report is
  where ledger-vs-chain divergence surfaces. A live on-chain
  balance cross-check endpoint awaits RPC access.
- Non-EVM families: scanners land with their chain phases.
