# ADR 0007: PostgreSQL Double-Entry Ledger with Integer Money

- **Status:** Proposed — Accepted for Phase 0/1, NOT Production Approved
- **Date:** 2026-11-12
- **Deciders:** Custodium architecture team
- **Phase scope:** Phase 0/1 design; ledger implementation in Phase 2 onward

## Status

Proposed and accepted as the working ledger design for Phase 0 and Phase 1 only. This decision is NOT Production Approved. The ledger
is a Phase 2+ implementation item; Phase 1 establishes the rules, models the accounts needed for foundation testing, and must not
contradict this ADR.

## Context

Custodium tracks other people's money across many chains and assets. The internal ledger — not any single blockchain — is what tenants
see as balances, what withdrawal checks rely on, and what auditors will reconcile against on-chain reality. Ledger errors are therefore
existential: a rounding drift, a lost update, or a one-sided entry is indistinguishable from lost or stolen funds until reconciled.

Non-negotiable properties:

1. **Double-entry:** every movement of value is recorded as balanced
   debits and credits. Money never appears or vanishes in one entry.
2. **Append-only:** history is never rewritten. Corrections are new,
   reversing entries that reference the original — never UPDATEs or DELETEs of posted entries.
3. **Exact integer money:** amounts are integers in the asset's
   smallest base unit (wei, satoshi-equivalent, sun, lamports, etc.). Floating point is forbidden for money, everywhere, without
   exception. A single float in a balance path invalidates the design.
4. **One system of record:** PostgreSQL (ADR 0001, ADR 0003) holds
   the ledger. Redis, Temporal history, chain indexers, and caches are never the ledger.
5. **Tenant and asset correctness:** every account is scoped to a
   tenant / project / wallet purpose and a single asset. Cross-asset or cross-tenant "netting" inside one entry is forbidden.

Assets differ in decimals (for example 18 for ETH, 6 for USDT on several chains, chain-specific values elsewhere). Integers in base
units make those differences explicit and exact: the asset registry records the decimals / base-unit definition, and display formatting
happens only at presentation edges, never in stored amounts.

## Decision

### 1. Store of record: PostgreSQL

- Ledger tables live in the same PostgreSQL system of record as the
  rest of the control plane (ADR 0001), enabling transactional consistency between business state (withdrawal status, sweep
  status) and financial state.

### 2. Model: accounts, journal entries, postings

- **Accounts:** typed ledger accounts, for example per wallet/asset:
  `available`, `reserved` (pending withdrawal/sweep), `pending_deposit` (unconfirmed), plus system accounts such as `external_chain`
  (the counterparty representing on-chain movement) and fee accounts. Each account: tenant, project, asset, purpose, and currency-unit
  definition. Account creation is explicit and audited.
- **Journal entries:** one business event = one journal entry, with
  a unique idempotency key, a type (deposit credit, withdrawal, sweep, fee, reversal, adjustment), references to the originating
  business object (deposit tx, withdrawal id, sweep id), and metadata.
- **Postings (lines):** two or more postings per entry, each a debit
  or a credit of a positive integer amount in base units against one account. **Invariant: sum(debits) == sum(credits) per entry, per
  asset.** Enforced in the service layer AND by database constraints / transactional checks before commit.
- Amount columns are PostgreSQL `BIGINT` where range is provably
  sufficient, or `NUMERIC(78,0)`-scale integer types where an asset's total supply / wei magnitudes exceed 64 bits (notably ETH-family
  wei amounts). The choice per column is deliberate and documented in migrations — never `DOUBLE PRECISION`, `REAL`, or float types,
  and never application-side floats. Python amounts are `int` (arbitrary precision); serialisation preserves exact integers.

### 3. Append-only enforcement

- Posted journal entries and postings are immutable: database
  permissions / triggers reject UPDATE and DELETE on posted rows.
- Corrections use reversal entries linked to the original entry,
  with a mandatory reason and actor. The pair nets to zero and the full history remains visible.

### 4. Reservations for pending outflows

- Withdrawals and sweeps first **reserve**: a balanced entry moves
  value `available -> reserved` for the wallet account. Only then may signing / broadcast proceed (via Temporal, ADR 0003).
- On broadcast success + required confirmation: settle
  `reserved -> external_chain` (plus fee postings). On permanent failure / abort: release `reserved -> available` via a linked
  entry. At no point can the same funds be reserved twice: account balance checks and the reservation write occur in one serialisable
  (or row-locked) transaction.

### 5. Balances

- An account's balance is the exact integer sum of its postings.
  A materialised balance (cached column / summary table) may be maintained transactionally for performance, but it is a derived
  value: it must be recomputable from postings, checked by periodic reconciliation jobs, and any divergence is a critical incident.
- Available balance for spending decisions is computed as
  `available` postings minus nothing hidden: reservations are real postings (see §4), not side flags, so concurrent withdrawals
  cannot both "see" the same unreserved funds.

### 6. Idempotency and external references

- Every journal entry carries a unique idempotency key derived from
  its business event (for example deposit chain + tx hash + log index, withdrawal id + step). Re-processing the same chain event
  or retrying the same Temporal Activity cannot create a second entry — the unique constraint rejects it and the existing entry
  is returned. On-chain identifiers are stored on the entry for reconciliation against indexers.

## Consequences

### Positive

- Exact, auditable money: balances can be proved from postings, and
  every unit is traceable to a balanced, referenced business event.
- Concurrency safety by construction: reservations as postings plus
  transactional checks prevent double-spend of internal balances.
- Reconciliation (Phase 5, Phase 9) has a precise target: ledger
  external-account totals must equal observed on-chain balances, per wallet / asset, at defined checkpoints.
- Integer base units eliminate an entire class of rounding, float
  representation, and decimals-mismatch defects.

### Negative

- Double-entry modelling is more work than a mutable `balance`
  column: every feature must think in entries and counter-accounts.
- Balance reads need the materialised-balance strategy to stay fast
  at scale; maintaining and reconciling it is ongoing work.
- Large-magnitude integer types and per-asset decimals require care
  in migrations, API schemas (amounts as strings or integers, never JSON floats), and the frontend display layer.

### Neutral / mitigations

- Provide a single ledger service module (ADR 0001) through which
  all entries are posted — no feature writes postings directly — with the balance invariant enforced centrally and in the database.

## Alternatives Considered

### A. Mutable balance column per wallet — Rejected

- No history, no proof, lost-update prone, and corrections destroy
  evidence. This is the anti-pattern the ledger exists to replace.

### B. Single-entry bookkeeping — Rejected

- One-sided entries cannot prove conservation of value; errors and
  fraud become undetectable by construction.

### C. Float / decimal-string amounts without base-unit discipline — Rejected

- Floats are forbidden outright. Decimal types are exact but invite
  per-call-site scale mistakes; integer base units with an explicit asset registry are the project's single money representation.

### D. Event-sourcing platform / Kafka as the ledger — Rejected as store of record

- Event logs may feed indexing and audit, but the ledger requires
  relational constraints, transactions with business state, and SQL reconciliation. Postgres is the mandated, sufficient store.

### E. Redis / in-memory balances with periodic flush — Rejected absolutely

- See ADR 0003: Redis loss must never be money loss. Never a ledger.

## Security Considerations

- Ledger write access is restricted to the ledger service identity;
  application roles used by read paths cannot insert postings.
- Append-only enforcement at the database layer (not just app code)
  limits damage from application bugs and compromised app credentials: history cannot be quietly rewritten with the app's own role.
- Every entry records actor / origin (user, API key, workflow,
  indexer) for audit; manual adjustments require privileged roles, a reason, and are alarmed as high-sensitivity events.
- Tenant isolation: accounts and entries are tenant-scoped; ledger
  queries always filter by tenant/project, covered by isolation tests.
- Manual blacklist and policy checks happen before reservation, so
  blacklisted destinations never reach the signing path.
- Reconciliation discrepancies halt the affected wallet/asset's
  outflows (fail closed) until resolved — the ledger never "catches up later" silently.

## Review Triggers

Re-open this ADR if any of the following occurs:

- Any reconciliation divergence between ledger and on-chain state
  in testing, staging, or (later) production-like environments.
- An asset is onboarded whose base-unit magnitude or decimals do not
  fit the chosen column types / registry model.
- Performance testing shows posting-sum balance reads or the
  materialised-balance strategy cannot meet required throughput.
- Auditors require a chart-of-accounts structure, subledger split,
  or a separate ledger database/service.
- Before ANY production approval — re-review constraints, append-only
  enforcement, reservation flows, and reconciliation evidence in full.
