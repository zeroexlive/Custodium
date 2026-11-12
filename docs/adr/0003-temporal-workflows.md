# ADR 0003: Temporal for Durable Workflows

- **Status:** Proposed — Accepted for Phase 0/1, NOT Production Approved
- **Date:** 2026-11-12
- **Deciders:** Custodium architecture team
- **Phase scope:** Phase 0/1 design; workflow implementation from Phase 3 onward

## Status

Proposed and accepted as the working workflow choice for Phase 0 and Phase 1 only. This decision is NOT Production Approved. No workflow
in Phase 1 moves funds or invokes production signing.

## Context

Many Custodium operations are not single request/response calls. They are long-running, multi-step, failure-prone processes that span
external systems the platform does not control:

- **Withdrawals:** validate → reserve ledger funds → policy/approval
  checks → signing ceremony → broadcast → confirmation tracking.
- **Sweeps:** discover sweepable balances → resolve destination via
  the tenant resolver (ADR 0006) → sign → broadcast → confirm → ledger settlement.
- **Deposit reconciliation:** observe chain events → wait for the
  required confirmations → credit the ledger → handle reorgs.
- **Signing orchestration:** coordinate MPC participants (ADR 0004),
  handle participant timeouts, retries, and aborts safely.

Properties these processes require:

1. **Durability:** a process restart or deploy must not lose an
   in-flight withdrawal or double-execute a signing step.
2. **Exactly-once effect (via idempotency):** retries are inevitable
   with external chains and MPC participants; each step must be safe to retry and must not double-spend, double-credit, or double-sign.
3. **Visibility:** operators must be able to see where every workflow
   is stuck, for how long, and why — custody operations cannot be black boxes.
4. **Timers and waits:** waiting hours for confirmations, approval
   windows, or cooldowns must not hold a web process or a thread.
5. **Compensation:** when a later step fails permanently, earlier
   steps (for example a ledger reservation) must be released in a defined, auditable way.

Redis queues and ad-hoc Celery-style tasks provide none of this as a coherent model: they are task dispatch, not durable workflow state.
Using Redis as the workflow store or — worse — as any part of the ledger would conflate ephemeral infrastructure with the financial
system of record (see ADR 0007).

## Decision

Adopt **Temporal** as the durable workflow engine for Custodium.

1. **Workflows (Temporal Workflows)** own orchestration logic for:
   - Withdrawal lifecycle
   - Sweep lifecycle
   - Deposit detection → confirmation → reconciliation
   - Signing ceremony orchestration (invoking MPC services via Activities, never embedding key material in workflow code)
2. **Activities** are the only place side effects happen: database
   writes via the Django service layer, RPC calls to chains, calls to MPC services, calls to the sweep destination resolver, and
   notifications. Activities must be idempotent, keyed by stable idempotency keys derived from the workflow and business object.
3. **PostgreSQL remains the system of record** for business and
   financial state (ledger, wallets, workflow business status). Temporal's own persistence is workflow execution state, not a
   substitute for the ledger (ADR 0007).
4. **Redis is explicitly NOT a workflow engine and NOT a ledger.**
   Redis may be used for caching, rate limiting, and ephemeral coordination only. Losing all Redis data must cause, at worst,
   cache misses — never lost workflows or lost money state.
5. Workflow code must be deterministic (Temporal requirement):
   no direct clocks, randomness, I/O, or database access inside Workflow definitions; all such operations go through Activities.
6. Every workflow carries tenant, project, and business-object
   identifiers in its search attributes / memo (non-sensitive identifiers only — never secrets or addresses beyond what the
   operation itself requires) for operator visibility.
7. Phase 1 scope: Temporal is part of the Docker Compose stack and
   the deployment topology, with a smoke / example workflow proving worker connectivity. Fund-moving workflows arrive in later phases
   behind their own security gates.

## Consequences

### Positive

- Durable, replayable execution: crashes and deploys resume in-flight
  withdrawals and sweeps instead of stranding them.
- Built-in retries with backoff, timers, signals, and queries give
  approvals, timeouts, and confirmation waits a first-class model.
- Temporal UI / CLI provides the operator visibility custody
  operations require.
- Deterministic workflow code plus versioning support makes long-
  lived workflow evolution manageable.

### Negative

- Temporal is another stateful system to deploy, back up, secure,
  and upgrade (server, its database, workers, and UI).
- The deterministic-workflow programming model has a learning curve;
  mistakes (non-determinism, overly long histories) cause failures that plain task queues would not.
- Workflow history can grow large for very long-lived processes;
  Continue-As-New patterns are required for reconciliation loops.

### Neutral / mitigations

- Pin Temporal server and SDK versions (see ADR 0002 pinning policy),
  test upgrades in staging, and keep workflows versioned using Temporal's patching APIs when logic changes mid-flight.

## Alternatives Considered

### A. Celery / Redis task queues as the workflow layer — Rejected

- Excellent for fire-and-forget tasks; inadequate as the sole record
  of a multi-hour, multi-step custody process. Chaining tasks with database flags re-invents a workflow engine, badly and unaudited.

### B. Redis as ledger / workflow store — Rejected absolutely

- Redis persistence and data-model guarantees are not those of a
  financial system of record. See ADR 0007: the ledger is Postgres, double-entry, append-only, integer money.

### C. Database state machines hand-rolled in Django — Rejected as primary

- Feasible for simple states, but every new timer, retry policy,
  signal, and compensation multiplies bespoke code and operator tooling. Retained only for simple, non-fund-moving state where a
  workflow would be overkill, by explicit per-case decision.

### D. AWS Step Functions / other hosted orchestrators — Rejected

- Cloud-vendor lock-in for the core custody orchestration, awkward
  local development, and data-residency / deployment constraints. Temporal is self-hostable and matches the Compose-based Phase 1.

### E. Kafka / event streaming as orchestration — Rejected as primary

- Event logs are a transport and audit aid, not a workflow engine:
  no built-in timers, retries-per-step, or per-instance queries.

## Security Considerations

- Temporal namespaces / task queues are separated by environment
  (sandbox vs production) and, where needed, by sensitivity: signing orchestration workers are distinct from general workers.
- Workers authenticate to Temporal; in real deployments the Temporal
  frontend is not exposed to the public internet, and its UI is behind the same access controls as other operator tooling.
- Payloads: workflow and activity arguments must never contain
  complete private keys, key shares beyond the MPC service's own channel, API secrets, or HMAC secrets (ADR 0005). Use references
  (IDs) and let Activities fetch secrets from the secret store.
- Idempotency keys and activity design must assume an attacker or a
  bug can cause retries and duplicate deliveries: duplicates must be harmless, never double-effect.
- Signing Activities enforce allow-listed destinations and amounts
  from the business record, not from mutable workflow arguments alone.
- Full workflow history is sensitive operational data: access is
  restricted, audited, and retained per the audit policy.

## Review Triggers

Re-open this ADR if any of the following occurs:

- Temporal cannot meet a required scale, latency, or history-size
  profile in load testing for indexing / reconciliation volumes.
- A Temporal security advisory or breaking change affects the pinned
  server/SDK versions.
- A compliance requirement mandates a different orchestration or
  data-residency model.
- Workflow determinism or versioning incidents cause a custody-
  relevant failure in testing or staging.
- Before ANY production approval — re-review namespace separation,
  payload hygiene, worker credentials, and backup/restore of Temporal persistence in full.
