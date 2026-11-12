# Ledger Design (Architecture) — Custodium

| Field | Value |
|---|---|
| Phase | Phase 0 design |
| Status | Planned |
| Canonical domain version | `docs/domain/ledger-design.md` (same principles; cross-reference, do not diverge) |

## 1. Purpose
The ledger is the system of record for *economic* truth: who is owed what,
per tenant project, per asset. The blockchain is the record of *settlement*.
This document describes how the ledger is placed in the architecture; the
domain document describes its invariants in business terms. If the two ever
conflict, stop and reconcile them — do not pick one silently.

## 2. Core decisions
- LD-A1: Double-entry. Every JournalEntry has ≥2 JournalLines; per asset,
  total debits == total credits. Unbalanced journals cannot be committed.
- LD-A2: Append-only. JournalEntry / JournalLine rows are never UPDATEed or
  DELETEd by application code. Corrections are new reversing entries that
  reference the original.
- LD-A3: Exact integer money. Amounts are integers in the asset's smallest
  base unit (wei, lamports, sun, nanotons, token base units per decimals).
  No FLOAT / REAL / double anywhere; no Decimal conversion through float.
  Database type: BIGINT, with NUMERIC(78,0)-style headroom considered for
  assets whose supply/range exceeds int64 — decision recorded per asset.
- LD-A4: One asset per journal. Cross-asset value exchange is out of scope;
  fees in a different asset are separate journals linked by operation id.
- LD-A5: Balances are derived. A balance is SUM(journal lines) for an account
  (+ reservation effects). Cached balance columns, if ever added, are
  rebuildable projections — never independent truth.
- LD-A6: Tenant-scoped accounts. Every LedgerAccount belongs to a project
  (hence an organisation) and an asset. Journals cannot span projects.

## 3. Account model (typical)
| Account type | Meaning |
|---|---|
| `customer_available` | Credited, withdrawable customer funds (per project/asset, optionally per wallet/customer sub-account) |
| `customer_pending` | Observed but not yet final deposits |
| `custody_onchain` | Counterpart representing funds actually held in MPC wallets on chain |
| `withdrawal_reserved` | Funds held by BalanceReservations for in-flight withdrawals |
| `treasury_available` | Tenant treasury funds after sweeps / consolidations |
| `swept_out` | Counterpart for funds swept to resolver destinations |
| `fees_payable` / `fees_collected` | Platform/tenant fee accounting (if fees enabled) |
| `suspense` | Time-boxed holding for reconciliation breaks; must trend to zero, alerts on ageing |

Account granularity (per project vs per wallet vs per customer reference) is
a schema decision in `docs/database/erd.md`; the invariant is that any
granularity still derives balances from lines.

## 4. Posting patterns

### 4.1 Deposit credit
```
Dr  custody_onchain        +amount
    Cr  customer_available     +amount
```
Pending stage (optional, pre-finality): Dr custody_pending / Cr
customer_pending, then a second journal promotes pending → available.
A deposit that reorgs out before credit posts nothing; after credit, a
reversing journal is posted — history is preserved.

### 4.2 Withdrawal
Reservation (not a journal by itself unless implemented as one):
- BalanceReservation holds amount against customer_available.
Settlement after on-chain confirmation:
```
Dr  customer_available     +amount   (via reserved sub-state)
    Cr  custody_onchain        +amount
```
Plus a fee journal if fees apply. Failed-before-broadcast: reservation
released; no settlement journal. The reservation lifecycle and the journal
lifecycle are linked by the withdrawal operation id.

### 4.3 Sweep — explicitly NOT a customer deposit
```
Dr  custody_onchain (deposit wallets)   +amount
    Cr  swept_out / treasury path           +amount
```
Implemented precisely as treasury movement between custody/treasury
accounts per the domain ledger doc. Key properties:
- No Deposit row, no customer_available credit.
- Linked to SweepJob + ResolvedDestinationSnapshot ids.
- Destination came only from the tenant HTTPS resolver (architecture rule).

### 4.4 Reversals and corrections
- Reversal journal references `reverses_journal_id`, carries a reason and an
  actor/operation; original remains untouched.
- Reconciliation breaks do not auto-post; human-approved corrections follow
  the same journal path as any other posting.

## 5. Reservations
- BalanceReservation: account, amount (int > 0), operation ref, state
  (active / consumed / released / expired), expiry.
- Available balance = derived balance − sum(active reservations).
- Reservation creation is transactional with the availability check
  (SELECT … FOR UPDATE on the account row or equivalent serialisation) to
  prevent two withdrawals reserving the same funds.
- Expiry of a reservation for a live workflow requires workflow coordination;
  silent expiry under an in-flight signing session is forbidden.

## 6. Concurrency and integrity
- Posting service is the ONLY writer of journals (`ledger` module).
- Unique constraints: journal idempotency key per operation+posting type,
  so Temporal activity retries cannot double-post.
- Database CHECK constraints: line amount > 0; direction in (debit, credit);
  entry asset matches account asset (enforced via FK/service + tests).
- Serialisation point is the ledger account row / posting transaction, not
  Redis locks (Redis may optimise, never guarantees).

## 7. Fees and network costs
- Network fees are paid on-chain by wallets but accounted explicitly:
  fee journals or fee lines linked to the operation, in the fee asset.
- Fee estimation (adapters) ≠ fee accounting (ledger). Actual confirmed fee
  is what gets recorded; differences from estimates are visible, not hidden.

## 8. Interaction with other components
| Component | Interaction |
|---|---|
| deposits | Requests deposit credit / reversal postings |
| withdrawals | Requests reservation + settlement / release |
| sweeps / treasury | Requests treasury movement postings |
| reconciliation | Reads derived balances; compares to chain |
| Temporal workflows | Call posting activities idempotently; journal id stored on operation |
| API / console | Read derived balances only; never compute balances ad hoc |
| MPC / chains | No direct ledger access |

## 9. Reporting and audit
- Trial balance per project/asset must balance to zero (sum of all lines = 0
  per asset when accounts are viewed double-entry complete).
- Any auditor query is answerable from journals + operation links without
  application logs.
- Journal metadata: operation type/id, actor/service, timestamp, idempotency
  key, reversal link — no secrets, no key material.

## 10. Testing requirements (before status > Implemented)
- Property tests: random posting sequences keep debits==credits and derived
  balances consistent; reversals restore prior balances.
- Concurrency tests: parallel reservations cannot over-reserve.
- Retry tests: duplicate workflow activity execution posts exactly once.
- Migration tests: schema changes preserve append-only guarantees.

## 11. Forbidden patterns
- Updating a balance column as the only record of a movement.
- Float / round-half tricks in fee or amount code.
- Negative-amount journal lines as a substitute for correct debit/credit side.
- Deleting or editing a journal to fix a mistake.
- Posting a sweep as a deposit (or vice versa) for reporting convenience.
- Cross-project or cross-asset netting inside one journal.
