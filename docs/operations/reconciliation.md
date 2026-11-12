# Custodium — Reconciliation (Phase 0)

> Status: Phase 0 design document. This system is **not production-ready**.
> Reconciliation is the control that proves the ledger and the chains
> agree — or finds out, quickly, when they do not.

## 1. Definitions

- **Ledger**: the platform's append-only, double-entry ledger. Amounts
  are exact integers in the smallest unit; floats are forbidden.
- **Chain state**: balances and transactions observed via indexers and
  cross-checked RPC providers (chain data is input, not gospel — see
  threat model T-15).
- **Difference**: any mismatch between ledger expectation and verified
  chain observation that a rule cannot explain (e.g. in-flight tx).

## 2. What is reconciled

1. **Wallet balances**: sum of ledger accounts per wallet/asset vs.
   on-chain balance of the wallet's addresses (adjusted for pending).
2. **Deposits**: every on-chain credit to a registered deposit address
   has exactly one ledger credit; every ledger deposit credit has a
   confirmed on-chain source.
3. **Withdrawals**: every ledger withdrawal debit has exactly one
   broadcast/confirmed chain transaction with matching amount and
   destination.
4. **Sweeps**: sweep debits/credits, resolved destination, and chain
   transaction agree (Section 6).
5. **Ledger internal consistency**: per transaction, debits == credits;
   globally, the trial balance is zero.
6. **Fees**: gas/fee ledger entries vs. actual chain fees paid.

## 3. Run types and cadence (targets)

| Run | Cadence* | Scope |
|---|---|---|
| Continuous checks | every few minutes | Ledger trial balance, duplicate-deposit guards |
| Incremental run | hourly | New deposits/withdrawals/sweeps since last run |
| Full run | daily | All wallets, all chains, all assets |
| On-demand run | after incidents, reorgs, indexer repair | Affected chains/wallets/windows |

\* Cadence targets for design; actual values set per chain finality.

Each run is a recorded object: `run_id`, type, window, chain, started/
finished times, items checked, differences found, and outcome. Runs are
idempotent: re-running a window produces the same differences, never
new postings by itself.

## 4. How a run works

1. Snapshot ledger state at a ledger sequence number (no moving target).
2. Snapshot chain state at a block height/hash per chain, at or above
   the confirmation threshold used for crediting.
3. Compare per wallet/asset using integer arithmetic only.
4. Classify each mismatch (Section 5); auto-explain only the classes
   that are provably timing artefacts (in-flight, unconfirmed).
5. Open a difference record for everything unexplained, with severity
   by amount and age; alert per `operations/monitoring.md`.
6. Resolution is a separate, human-reviewed step (Section 7). A run
   never silently "fixes" the ledger.

## 5. Difference classes

| Class | Meaning | Default action |
|---|---|---|
| `in_flight` | Ledger and chain differ by a tx inside its confirmation window | Auto-clear when final |
| `missing_credit` | Confirmed deposit on-chain, no ledger credit | Investigate indexer/crediting; credit idempotently |
| `phantom_credit` | Ledger credit with no confirmed chain source | SEV-2; possible fraud/bug; freeze further crediting for scope |
| `amount_mismatch` | Both exist, integer amounts differ | Investigate token behaviour (fee-on-transfer etc.) |
| `missing_withdrawal_tx` | Ledger debit, no chain transaction | Investigate broadcast path; do not re-broadcast blindly |
| `unknown_chain_tx` | Chain spend from a wallet with no ledger debit | SEV-1 candidate; possible unauthorised signing |
| `duplicate_credit` | Two credits for one `(chain, tx_hash, index)` | Should be impossible (unique constraint); SEV-2 if seen |
| `reorg_removed` | Previously confirmed item reorged out | Reverse via reversing entry; notify tenant |

## 6. Idempotent crediting

Deposit crediting is designed so retries and re-runs are safe:

- Uniqueness key: `(chain, tx_hash, output_index_or_log_index)`.
- Crediting job: `INSERT ... ON CONFLICT DO NOTHING`-style semantics
  around the posting, with the double-entry posting and the deposit
  record committed in one transaction.
- Re-running the indexer over a window, restarting workers, or replaying
  Temporal activities therefore cannot double-credit.
- Credits are posted only after the chain's confirmation threshold and
  RPC cross-check; `deposit.detected` is never a credit.

## 7. Resolving differences

- Only corrections are **reversing/adjusting entries** that reference
  the difference ID and, where relevant, the incident ID. Ledger rows
  are never edited or deleted.
- Adjustments require a second operator's approval above a value
  threshold (thresholds are configuration, set before launch).
- `unknown_chain_tx` and `phantom_credit` block automatic resolution
  entirely: they are security events first (see incident response).
- Every resolution closes the difference with a reason code; monthly
  reporting counts differences by class, age, and root cause.

## 8. Sweep accounting

- A sweep is reconciled as a linked set: source wallet debit, chain
  transaction, destination credit (external), fee entries.
- The destination checked is the address actually resolved at execution
  time from the tenant-registered HTTPS resolver endpoint (plain-text
  response) — recorded in the sweep record and audit log. Destinations
  are never taken from a sweep request or local files, so reconciliation
  never compares against a caller-supplied address.
- Sweeps stuck between debit and broadcast beyond a time bound open a
  difference; sweeps must be resumable or reversible by entry, never
  stranded silently.
- Internal sweeps (same platform) must net to zero across wallets plus
  explicitly recorded fees.

## 9. Tenant visibility

- Tenants see reconciliation effects on their own data only: corrected
  deposits/withdrawals and explanatory audit events.
- Platform-wide difference statistics are internal; a tenant is never
  shown another tenant's differences, amounts, or addresses.

## 10. Failure handling

- A failed run (RPC outage, indexer lag) is reported as *no assurance*,
  not as success; consecutive failed runs alert.
- If a chain cannot be verified (all RPC providers divergent/down),
  crediting and withdrawals for that chain pause until a run passes.
- After any SEV-1/SEV-2 touching money, a full on-demand run with zero
  unexplained differences is a precondition for resuming withdrawals
  (see `security/incident-response.md`).

## 11. Metrics

- Runs completed/failed, duration, items checked per chain.
- Open differences by class, amount (integer base units), and age.
- Mean time to resolve, by class; repeat root causes tracked to fixes.
