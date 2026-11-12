# Domain Invariants — Custodium

| Field | Value |
|---|---|
| Phase | Phase 0 design |
| Status | Planned — invariants are requirements for implementation and tests |

## 1. How invariants are used
An invariant is a statement that must hold before and after every operation,
including under retries, concurrency, reorgs and partial failures. Each
invariant should map to at least one of: a DB constraint, a service-layer
check, a property test. An operation that cannot preserve an invariant must
fail closed. Numbering is stable — reference invariants in code reviews/PRs.

## 2. Tenancy and access
- INV-TEN-01: Every tenant-owned entity belongs, directly or transitively, to
  exactly one Organization. There are no orphan tenant rows.
- INV-TEN-02: A principal (user or API key) can read/write only within its
  organisation + project + environment scope. Cross-scope ids resolve as
  not-found.
- INV-TEN-03: Permission checks use Permission, not role-name string matching.
- INV-TEN-04: API keys authenticate exactly one project/environment scope;
  a key never grants console session privileges.
- INV-TEN-05: Revoked keys, removed memberships and suspended organisations
  deny new operations immediately; in-flight workflows re-check and halt
  money movement if scope was revoked for fraud/security reasons.

## 3. Money and ledger
- INV-MON-01: All amounts are integers > 0 in domain operations, expressed in
  asset base units. Zero/negative operation amounts are rejected (journal
  lines likewise carry positive amounts with a debit/credit side).
- INV-MON-02: No float is created, parsed or stored in any money path,
  including fees, exchange of units, and JSON (de)serialisation of amounts
  (amounts cross JSON as strings or integers, never binary floats).
- INV-LED-01: Every JournalEntry balances per asset: Σ debits == Σ credits.
- INV-LED-02: Journals and journal lines are append-only. No UPDATE/DELETE.
- INV-LED-03: A correction is a new journal referencing the original. The
  original's amounts and lines never change.
- INV-LED-04: Derived balance for an account equals Σ(credit lines) −
  Σ(debit lines) under the account's sign convention, at any point in time,
  reproducibly.
- INV-LED-05: Available balance = derived balance − active reservations,
  and available balance never goes negative due to a withdrawal or sweep.
- INV-LED-06: A journal belongs to one project and one asset; its lines'
  accounts share that project and asset.
- INV-LED-07: Posting with the same idempotency key and payload returns the
  original journal; same key with a different payload is an error, never a
  second posting.
- INV-RES-01: A BalanceReservation is in exactly one state: active, consumed,
  released or expired. Transitions are one-way out of active.
- INV-RES-02: Sum of active reservations on an account ≤ derived balance at
  reservation time and at consumption time (re-checked).

## 4. Wallets, keys and signing
- INV-KEY-01: No complete private key exists in Custodium at any time: not in
  DB, memory of a single service, logs, backups or MPC coordinator.
- INV-KEY-02: KeyShareReference contains no share bytes, seed or mnemonic.
- INV-KEY-03: Each MPCParticipant holds at most its own share; participant
  count and threshold are recorded on the MPCWalletGroup and are immutable
  for existing wallets except via a governed resharing/recovery operation.
- INV-KEY-04: A signature is produced only inside a SigningSession bound to
  one operation, one payload hash and one policy version.
- INV-KEY-05: No SigningSession is opened unless policy evaluation passed,
  required approvals exist (withdrawals), blacklist checks passed, and a
  reservation exists where funds move. MPC re-verifies policy independently.
- INV-KEY-06: If quorum is unavailable, signing does not degrade: no single-
  signer fallback exists.
- INV-WAL-01: A Wallet belongs to one MPCWalletGroup and one network family;
  a WalletAddress belongs to one Wallet and one BlockchainNetwork.
- INV-WAL-02: An address string is unique per network across the platform
  (same string on different networks is a different address record).
- INV-ADR-01: An address assigned to an ExternalCustomerReference is not
  reassigned to another customer while it has a non-zero derived balance,
  pending deposits, or unresolved reconciliation breaks.
- INV-ADR-02: Address derivation never requires exporting key material to
  the Django tier.

## 5. Deposits and indexing
- INV-DEP-01: A chain transfer is uniquely identified by (network, tx hash,
  transfer index). Duplicate observations never create duplicate deposits.
- INV-DEP-02: A deposit is credited at most once: exactly zero or one credit
  journal per deposit, enforced by idempotency key + unique constraint.
- INV-DEP-03: Credit requires the network's confirmation/finality policy.
  Pending and credited are distinct, observable states.
- INV-DEP-04: IndexingCheckpoint never advances past data that was not
  durably recorded. Re-scanning a range is always safe (idempotent).
- INV-DEP-05: A reorg before credit voids the pending deposit without a
  journal; a reorg after credit is handled by reversing journal + alert —
  never by deleting the deposit or its journal.
- INV-DEP-06: Deposit amount credited equals the on-chain transfer amount in
  base units, minus only an explicitly recorded fee journal if fees apply.

## 6. Withdrawals
- INV-WDR-01: A withdrawal has exactly one destination address, validated for
  its network, recorded at creation, immutable thereafter (change = cancel +
  new withdrawal).
- INV-WDR-02: A blacklisted destination blocks the withdrawal before any
  signing session exists.
- INV-WDR-03: Required WithdrawalApprovals are distinct approvers satisfying
  the policy in force at creation; an approver cannot approve twice or
  approve their own request if policy forbids self-approval.
- INV-WDR-04: At most one successful broadcast pays a withdrawal: multiple
  TransactionAttempts may exist, but settlement journal posts exactly once,
  and a confirmed attempt precludes paying via another attempt.
- INV-WDR-05: A withdrawal in a terminal state (completed/failed/cancelled)
  never returns to a non-terminal state; corrections are new operations.
- INV-WDR-06: Client idempotency keys are unique per project; replaying a
  create returns the original withdrawal.

## 7. Sweeps and treasury
- INV-SWP-01 (absolute): A sweep's destination is obtained only by calling
  the tenant-registered HTTPS SweepDestinationResolver at execution time and
  receiving a plain-text address. No other source is valid: not the sweep
  request, not a file, not an env var, not a previous job's snapshot, not
  an admin field.
- INV-SWP-02: Every sweep execution stores a ResolvedDestinationSnapshot
  before signing. No snapshot → no signing → no sweep.
- INV-SWP-03: Resolver output failing validation (non-HTTPS source, non-plain-
  text, zero/multiple addresses, wrong network, blacklisted) fails the sweep
  closed with an audit event.
- INV-SWP-04: A sweep never creates a Deposit, never credits
  customer_available, and is journalled only as a treasury/custody movement.
- INV-SWP-05: Sweep source selection never sweeps funds reserved for
  withdrawals, pending-credit deposits, or amounts needed to keep available
  balances non-negative (INV-LED-05 applies).
- INV-SWP-06: A SweepJob's attempts are sequential per source wallet unless
  the design explicitly parallelises with per-wallet locks; total swept per
  job is reconcilable to its attempts' confirmed transfers.

## 8. Blacklist
- INV-BLK-01: BlacklistEntry records are created and removed only manually
  by authorised users, with actor + reason. No automated feed creates entries.
- INV-BLK-02: There is no AML/KYT provider, score or screening state in the
  domain. Code or copy implying otherwise is a defect.
- INV-BLK-03: Blacklist checks for withdrawals use the destination at
  creation AND at execution; for sweeps, the freshly resolved destination.

## 9. Policies, audit, webhooks, events
- INV-POL-01: SigningPolicy is versioned; an operation binds the version in
  force at its creation. Editing a policy creates a new version and never
  rewrites in-flight operations' rules silently.
- INV-POL-02: Policy evaluation is deterministic on recorded inputs; the
  inputs and result are stored with the operation for audit replay.
- INV-AUD-01: SecurityAuditEvent is append-only and written in the same
  transaction as the action it records, or the action does not commit.
- INV-AUD-02: Audit events never contain secrets, HMAC keys, share data or
  full API keys.
- INV-WHK-01: A WebhookDelivery is delivered to endpoints of the event's
  organisation only, signed, and carries a stable event id for deduplication.
- INV-WHK-02: Webhook failure never rolls back the domain operation.
- INV-OUT-01: Every committed domain change that other systems observe has
  exactly one OutboxEvent per aggregate event; processors are idempotent.

## 10. Reconciliation
- INV-REC-01: For every (wallet/address, asset), ledger-derived custody
  balance and observed on-chain balance are compared on each run; any
  difference is a break, never silently netted away.
- INV-REC-02: Reconciliation never writes journals directly. Resolutions go
  through the owning context (deposit/withdrawal/treasury) as new journals.
- INV-REC-03: Suspense balances trend to zero; aged suspense raises alerts.

## 11. Networks and assets
- INV-NET-01: Decimals for an asset with recorded transfers never change.
- INV-NET-02: A disabled network/asset accepts no new operations; in-flight
  operations are completed or explicitly failed by workflow, not stranded.
- INV-NET-03: Confirmation counts are measured against the network's stated
  finality model (blocks, solidity, slots/commitment, TON messages) — EVM
  assumptions are not copied to non-EVM networks.

## 12. Testing the invariants
- Each invariant lists its enforcement in the implementation PR (constraint /
  service check / test). PRs that weaken an invariant require an explicit
  invariant amendment in this file plus security review.
- Property-based tests target §3 and §5–§7 first: they protect money and keys.
