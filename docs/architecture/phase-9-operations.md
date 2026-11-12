# Financial Operations — Phase 9 Implementation Record

Status: **Implemented** (2026-11-12). Code:
`apps/backend/waas/modules/operations/`. This phase adds the
operator-grade finance layer around the chain pipelines
(Phases 4–8): the withdrawal request lifecycle from the Phase 0
API design, the business policy engine, fee accounting,
reconciliation halts, exports, and the refund playbook.

## 1. The request lifecycle

`WithdrawalRequest` implements the design's status machine
verbatim: `pending_policy → approved → signing → broadcast →
confirming → completed | failed | rejected`.

- **Creation** (`POST /withdrawals`, machine scope
  `withdrawals:write` or a finance-capable dashboard role;
  `Idempotency-Key` header required, replay returns the stored
  request): asset/network consistency, the Phase 2 manual
  blacklist (checked at creation *and* again inside every chain
  pipeline), and the policy engine run before anything is
  persisted as actionable.
- **Policy engine** (`WithdrawalPolicy`: asset-specific row, else
  project default, else platform default of 1 approval):
  *hard limits* — `max_single_amount` and a daily velocity limit
  (sum of the wallet+asset's non-terminal requests today) —
  reject the request immediately with the reason recorded;
  *approval quorum* — `approvals_required`, waived for amounts
  at or below `auto_approve_below`.
- **Approvals** (`POST /withdrawals/{id}/approve|reject`,
  dashboard only): roles owner / administrator /
  withdrawal_approver. **Maker-checker**: a dashboard user who
  requested a withdrawal can never approve it; each approver
  decides at most once; one rejection is final; the quorum
  reaching `approvals_required` flips the request to `approved`.
  Business quorum is separate from the MPC threshold by design.
- **Dispatch** is worker-driven (`process_withdrawals` command),
  never API-triggered: approved requests are dispatched through
  the family adapter (`operations/dispatch.py`) into the
  Phase 4–8 pipelines and tracked (`refresh_withdrawal`) until
  they complete or fail. Production signer factories return the
  fail-closed unavailable signers, so in the platform's current
  state an approved request dispatches, reserves, fails honestly
  at the signing gate, and releases — the full accounting cycle
  is exercised without pretending signing exists. The operations
  layer also catches pipeline/provider exceptions so one bad
  request can never crash the worker batch.

## 2. Fee accounting

- **Service fee** (policy `service_fee_flat`, in the withdrawn
  asset): charged by journal at dispatch — before any chain
  execution — debiting the customer's available balance to
  `platform_fees_payable`; if the charge itself fails the
  dispatch aborts pre-chain. If the withdrawal later fails or
  reverts, the fee journal is **reversed** (`reverse_entry`), so
  fee income never survives a failed payout.
- **Network fee** is reported on completion as `actual_fee` with
  an explicit `fee_asset` (the network's native asset), captured
  from the chain record: EVM `gasUsed × effectiveGasPrice`
  (new `fee_wei` capture in the EVM confirm path), TRON
  `fee_sun`, Solana `meta.fee` lamports (new provider call,
  best-effort so fee reporting never blocks settlement), TON
  `total_fees`.

## 3. Reconciliation halt (fail closed)

`run_reconciliation` runs the Phase 5 reconciliation report for
every network and raises a `ReconciliationHalt` when any asset
is unbalanced. While a halt is active, **new withdrawals on that
network are refused** at creation and at dispatch; a clean
reconciliation clears it. Halt checks query the database fresh
(a cached relation kept a cleared halt alive in testing — fixed
and covered).

## 4. Refunds and exports

- **Refund playbook** (`POST /withdrawals/{id}/refund`, owner /
  administrator): credits a completed withdrawal back to the
  customer as an explicit **ADJUSTMENT** journal (the ledger
  reserves REVERSAL entries for true single-entry reversals via
  `reverse_entry`; a refund spans the settlement, so it is
  booked as its own balanced adjustment with a mandatory
  reason). Cumulative refunds can never exceed the withdrawn
  amount.
- **Finance export** (`GET /projects/{id}/finance/journal-export`,
  owner / administrator / finance_operator): the project's
  journal entries with all lines as CSV — integer amounts, ISO
  timestamps, full idempotency/operation linkage.

## 5. Dashboard

A Withdrawals view (sidebar): project-scoped request list with
status/reason/approvals/fees, a create form, approve/reject
actions on pending requests, and the project-default policy
editor. The API client's `request` helper gained optional extra
headers for the `Idempotency-Key`.

## 6. Verification performed

Backend suite: see `AGENTS.md` (operations tests cover: default
policy + role-gated approval, maker-checker, single/daily/
auto-approve policy matrix, create idempotency + blacklist +
halt guards, full EVM dispatch → fee journal → completion with
actual fee and zero trial balance, fail-closed default dispatch
reversing the service fee, refund bounds, halt raise/clear
cycle, journal export, and an end-to-end API test — HMAC machine
creation requiring the idempotency header, then dashboard
approval). Frontend typecheck, vitest, and production build all
pass.

## 7. NOT verified / deferred

- **Live testnet soak / zero-discrepancy exit criterion**: chain
  APIs are unreachable from this sandbox (standing egress
  limitation); the reconciliation machinery is verified against
  doubles and seeded ledgers, not a live soak.
- Temporal workflows remain unwired — `process_withdrawals` and
  `run_reconciliation` are the idempotent worker entrypoints a
  scheduler invokes, as with `run_indexer`.
- Per-asset policy rows are supported by the data model and
  resolution order; the dashboard editor manages the project
  default (asset-specific editing is API-only for now).
