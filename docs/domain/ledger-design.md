# Ledger Design (Domain) — Custodium

| Field | Value |
|---|---|
| Phase | Phase 0 design |
| Status | Planned |
| Architecture counterpart | `docs/architecture/ledger-design.md` — same principles, system view. This document is the domain view. Keep both in sync. |

## 1. Why a formal ledger
Tenant funds are other people's money. A mutable `balance` column cannot
answer “why is this the balance?”, cannot be audited, and races under
concurrency. Custodium therefore models money as a double-entry, append-only
ledger from day one — retrofitting a ledger after launch is not credible.

## 2. Domain vocabulary
| Term | Meaning |
|---|---|
| LedgerAccount | A named bucket in the chart of accounts for one project + asset (optionally per wallet/customer sub-scope) |
| JournalEntry | One balanced economic event: date, operation link, asset, memo, idempotency key |
| JournalLine | One debit or credit line: account, side, positive integer amount |
| BalanceReservation | A hold reducing available (not total) balance for an in-flight operation |
| Derived balance | Σ lines for an account; the only definition of balance |
| Reversal | A new journal that exactly negates a prior journal's lines |
| Suspense | Temporary account for unresolved differences; must clear to zero |

## 3. Principles (domain statement)
- DP-1 Double-entry: every economic event debits and credits equally.
  There is no single-sided “adjustment” operation in the vocabulary.
- DP-2 Append-only: history is never rewritten. Errors are reversed, visibly.
- DP-3 Integer base units: amounts are counts of the smallest unit. The
  domain does not know “1.5 USDT”; it knows 1_500_000 units at 6 decimals.
  Rendering decimals is a presentation act, never a storage act.
- DP-4 No floats, ever: parsing, arithmetic, JSON transport and storage all
  preserve integers. (INV-MON-02 in `domain-invariants.md`.)
- DP-5 One journal = one project, one asset, one operation (or one clearly
  identified sub-step of an operation).
- DP-6 Every journal is explainable: operation type + id, actor/service,
  timestamp, and where relevant the on-chain tx hash explain its existence
  without reading application logs.
- DP-7 Reservations are first-class: “available” and “total” are different
  domain concepts, and confusing them is a defect.
- DP-8 Sweeps are not deposits: the vocabulary, accounts and journals keep
  treasury consolidation distinct from customer credit (see §7).

## 4. Chart of accounts (per project + asset)
| Account | Normal side | Purpose |
|---|---|---|
| `custody_onchain` | Debit | Funds provably held in MPC wallets on chain |
| `custody_pending` | Debit | Observed deposits awaiting finality |
| `customer_available` | Credit | Customer funds available for withdrawal |
| `customer_pending` | Credit | Customer funds observed, not yet credited |
| `withdrawal_reserved` | Credit | Customer funds reserved for in-flight withdrawals (contra to available in reporting) |
| `treasury_available` | Credit/Debit per design | Tenant treasury funds under Custodium wallets |
| `swept_out` | Debit | Funds that left custody to resolver destinations |
| `network_fees` | Debit | Actual on-chain fees borne per policy |
| `platform_fees_payable` | Credit | Fees owed (only if a fee model is enabled) |
| `suspense` | Either | Unresolved reconciliation differences (temporary) |

Sub-accounts: where reporting needs per-wallet or per-customer granularity,
accounts are instantiated per (project, asset, wallet) or (project, asset,
external customer reference) using the same types — granularity changes
reporting, never the posting rules.

## 5. Canonical postings

### 5.1 Deposit observed (pre-finality, optional stage)
```
Dr custody_pending      amount
  Cr customer_pending     amount
```

### 5.2 Deposit credited (finality reached)
```
Dr custody_onchain      amount
  Cr customer_available   amount
(and, if 5.1 was used, a promoting journal clears the pending pair)
```
Exactly one credit sequence per deposit (INV-DEP-02).

### 5.3 Withdrawal reservation
Reservation record only (no journal required if reservations are tracked as
their own aggregate):
- available(customer) decreases by amount; total unchanged.
If an implementation chooses journal-backed reservations, the posting is:
```
Dr customer_available     amount
  Cr withdrawal_reserved    amount
```
and release/settlement are the mirror/continuation of that posting. Choose
one model per deployment and test it; do not mix both for one account.

### 5.4 Withdrawal settled (confirmed on chain)
```
Dr customer_available / withdrawal_reserved   amount (+ fee handling)
  Cr custody_onchain                            amount
Dr customer_available (fee)                     fee
  Cr network_fees / fees_payable                fee
```
(Fee asset may differ from withdrawal asset; then the fee journal is a
separate journal in the fee asset, linked by operation id — DP-5.)

### 5.5 Withdrawal failed before broadcast
- Reservation released (or reservation journal reversed). No settlement
  journal. The customer balance is exactly as before the attempt.

### 5.6 Deposit reversal (post-credit reorg / proven error)
```
Reversing journal negating 5.2 exactly, referencing the original journal,
reason = reorg | error, linked to the deposit and the new chain evidence.
```
Customer available may go negative in *derived* terms only if product policy
explicitly allows overdraft handling via suspense; default: credit the
reversal against customer_pending/suspense workflow with an alert, and block
further withdrawals for that customer until resolved. The chosen handling
must be implemented as stated here or this section amended — no improvisation.

## 6. Reservations in depth
- Created transactionally with the availability check.
- Carry: account, amount, operation id, expiry, state machine
  active → consumed | released | expired (one-way).
- Consumed exactly when the settlement journal posts.
- A sweep, a second withdrawal, or a manual action must all respect the same
  available-balance definition — there is one definition (INV-LED-05).

## 7. Sweeps in the ledger
A sweep consolidates funds held in deposit wallets toward a tenant
destination obtained ONLY from the tenant-registered HTTPS resolver
(plain-text address, snapshotted per execution).
Domain posting on confirmation:
```
Dr swept_out            amount
  Cr custody_onchain      amount   (deposit-wallet custody accounts decrease;
                                     swept_out increases as the counterpart)
```
Presented in account terms: custody decreases, `swept_out` increases, total
per asset still balances. Treasury reporting may additionally classify the
movement under a TreasuryOperation.
Hard domain rules:
- No Deposit aggregate is created. No `customer_available` line exists.
  A customer did not deposit; the tenant's own funds moved internally→out.
- The journal references SweepJob id + ResolvedDestinationSnapshot id, so an
  auditor can trace amount → job → snapshot → resolver registration.
- Individual customer sub-account balances are NOT debited by a sweep unless
  the product model explicitly defines sweep debits per customer (e.g.
  omnibus vs segregated). Phase 0 default: custody is omnibus at wallet
  level; customer claims live in `customer_available` and are unaffected by
  the physical location of coins. Any change to this default is a product +
  accounting decision recorded here first.

## 8. Fees
- Estimated fees (adapters) are not ledger facts. Confirmed fees are.
- Who bears a fee (customer vs tenant treasury vs platform) is a policy/
  product attribute recorded on the operation, and the posting follows it.
- TRON energy, Solana rent/fees and TON message fees follow the same rule:
  actuals, in their native asset journal, linked to the operation.

## 9. Periods, reporting, reconciliation hooks
- Trial balance per (project, asset) at any timestamp: sum over accounts of
  derived balances must net to zero across the full double-entry set.
- Point-in-time balances are computable (lines have journal timestamps) —
  no “balance as of” feature may require mutable snapshots as truth.
- Reconciliation consumes custody account derived balances (§9 of invariants:
  INV-REC-*). Suspense postings require a break reference.

## 10. What the ledger never does
- Never talks to chains, RPC, MPC or webhooks.
- Never decides policy (it enforces balance/reservation arithmetic only).
- Never accepts an amount as string-float, JSON float or Decimal-via-float.
- Never nets two operations into one journal for convenience.
- Never hides a difference: unmatched amounts go to suspense with a break,
  not into a rounding account. There is no rounding in integer arithmetic.

## 11. Worked example (USDT, 6 decimals, ETH network)
1. Customer deposits 100 USDT → transfer of 100_000_000 base units observed.
2. Finality → journal J1: Dr custody_onchain 100_000_000 / Cr
   customer_available 100_000_000. Balance(customer_available)=100_000_000.
3. Customer withdraws 30 USDT → reservation 30_000_000; available becomes
   70_000_000, total still 100_000_000.
4. Broadcast confirms, fee 1 USDT-equivalent in ETH recorded separately.
   J2 settles 30_000_000 out of custody. customer_available total = 70_000_000.
5. Sweep of wallet funds: resolver returns tenant address; J3 moves
   50_000_000 custody → swept_out. customer_available stays 70_000_000 —
   the sweep moved coins, not customer claims. No deposit exists for J3.
This example is the acceptance story for ledger tests.
