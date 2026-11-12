# Gas Station — automatic native-coin top-ups (post-roadmap module)

**Status:** Implemented and tested locally (2026-11-13). Not Security
Reviewed / Production Approved — the standing gates are unchanged, and
top-ups ride the same fail-closed signer factories as every transfer,
so in the platform's current state a top-up aborts honestly at the
signing step exactly like a withdrawal does.

## Why

Every chain pipeline pays the network fee from the sending wallet's
own native balance. A deposit wallet holding USDT but no ETH could
not be swept or withdrawn from until someone funded it with native
coin by hand. The gas station automates that funding.

## Design

`waas/modules/gasstation/`:

- **`GasStation`** — one per (project, network): a `funding_wallet`
  owned by the *same project* (a tenant funds its own wallets; the
  platform never subsidises gas across tenants), `enabled`,
  `min_native_balance` (threshold, native base units), `topup_amount`,
  `max_topups_per_day` (safety cap).
- **`GasTopUp`** — one record per operation (`operation_key` = the
  transfer's idempotency key, `wd:<id>` / `swp:<id>`), with the chain
  transaction id/hash and a pending → broadcast → confirmed/failed
  lifecycle.

**Preflight.** The shared `operations.dispatch.execute_transfer`
calls `gasstation.services.preflight_transfer` before any family
pipeline runs:

1. Native-asset transfers, projects without an enabled station, and
   the funding wallet itself pass through untouched.
2. The wallet's on-chain native balance is read through the family
   provider (`get_balance` on EVM/Solana/TON; TRON derives it from
   its account read). An unreadable balance **never blocks** a
   transfer — the station cannot make money movement less reliable
   than it was without one.
3. Balance ≥ threshold → proceed (an in-flight top-up is advanced
   via the normal confirm path, which also settles the funding
   wallet's ledger reservation, and marked confirmed).
4. Balance < threshold → a top-up of `topup_amount` is broadcast
   from the funding wallet to the wallet's address **through the
   ordinary pipeline** (`gas:<operation_key>` idempotency) — same
   signer gates, blacklist checks, reservation accounting and
   confirmation tracking as any transfer; journaled in the funding
   wallet's own ledger scope. No special money path exists.
5. `GasTopUpPending` is raised and the caller **defers, never
   fails**: withdrawal dispatch returns the request to `approved`
   with reason `awaiting gas: …` and reverses the service-fee
   charge; sweep execution returns the sweep to `resolved` with
   its destination snapshot untouched (no re-resolution). The next
   worker pass proceeds once the balance has landed. A daily cap
   hit also defers (with the reason recorded), and a top-up whose
   transaction reverted is retried on a later pass subject to the
   cap; a confirmed top-up that still leaves the balance below the
   threshold defers with a manual-review reason instead of looping.

**Configuration.** Dashboard-only API (`GET/PUT /gas-stations`,
`GET /gas-stations/topups`), owner/administrator role; the funding
wallet must belong to the same project (422 otherwise). The
dashboard gains a **Gas Station** view: station form, configured
stations, and recent top-ups. Machine (HMAC) configuration is
deliberately not offered — funding-wallet selection is an operator
decision.

## Verification

- `tests/integration/test_gasstation.py` (6 tests): the full EVM
  deferral cycle (USDT withdrawal defers with exactly one send —
  the top-up — service fee reversed; after the balance lands and
  the receipt confirms, the withdrawal broadcasts, the top-up is
  confirmed, the funding reservation settles for exactly the
  top-up amount, native trial balance zero), native pass-through,
  disabled-station and funded-wallet pass-through, daily-cap
  deferral with no top-up, the sweep deferral cycle resuming from
  the same snapshot, and API validation (cross-project funding
  wallet rejected 422).
- Full suite after the module: backend **173 passed / 1 skipped**,
  ruff clean; frontend typecheck, vitest (9) and build green.

## Not verified / limitations

- Live-chain top-ups were not executed (sandbox egress; the cycle
  is proven against the provider double like every other family).
- Balance reads for TRON use the account endpoint's `balance`
  field; frozen/energy nuances of TRX fee payment are the
  operator's threshold choice, not modelled separately.
- Top-up confirmation tracking reuses each family's confirm path
  when the owning operation is retried; a top-up for an operation
  that is never retried stays `broadcast` in the list view (its
  chain transaction still settles through the same row).
