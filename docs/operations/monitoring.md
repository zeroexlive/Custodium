# Custodium — Monitoring and Observability (Phase 0)

> Status: Phase 0 design document. This system is **not production-ready**.
> SLO numbers below are initial targets to be validated in operation,
> not guarantees to tenants.

## 1. Principles

1. Observe money, keys, and chains first; vanity metrics last.
2. Logs and traces must never contain secrets or key material.
3. Every alert is actionable, owned, and linked to a runbook.
4. Metrics are per-tenant-aware internally, but tenant-facing views
   show only that tenant's data (see tenant isolation).

## 2. Stack

- **Traces/metrics/logs pipeline**: OpenTelemetry (OTLP) from Django,
  workers, Temporal activities, indexers, and signer services.
- **Metrics store / dashboards**: Prometheus + Grafana.
- **Logs**: structured JSON, shipped to a central, access-controlled,
  retention-managed log store.
- **Alerting**: Prometheus Alertmanager -> paging for SEV-class alerts,
  chat for warnings. Alert definitions live in version control.

## 3. Structured logging rules

Log fields: `timestamp` (UTC), `service`, `level`, `event`, `request_id`,
`trace_id`, `tenant_id`, `project_id`, `actor_type`, `outcome`,
`error_code`, `duration_ms`.

**Never log:**

- API secrets, HMAC signatures beyond a short prefix for correlation,
  webhook secrets, passwords, session tokens.
- MPC key shares, share fragments, seed material, or signing-session
  secrets — in any field, at any level, including debug.
- Full destination/resolver data beyond what audit requires; audit
  records go to the audit log, not application logs.
- Raw request bodies for financial mutations (log IDs and hashes).

Redaction is enforced by logging middleware with an allowlist of
fields, plus CI tests that scan sample log output for secret patterns.

## 4. Tracing

- One trace per API request, extended across Temporal workflows and
  signer calls with propagated context (tenant ID is a tag, never a
  credential).
- Signer spans record request ID, payload hash, policy result, and
  duration — never the payload's sensitive fields or share data.
- Sampling: 100% for financial mutations and errors; head-based
  sampling is acceptable for read-only traffic.

## 5. Key signals and metrics

### API and platform

- Request rate, error rate, latency (p50/p95/p99) per endpoint class.
- HMAC failures, nonce replays rejected, idempotency conflicts.
- DB connection saturation, slow queries, RLS-denied attempts.
- Redis queue depth; Temporal workflow/task-queue latency and failures.

### Indexer and chains

- **Indexer lag**: blocks (or seconds) behind chain head, per chain.
- Reorgs detected per chain and depth; re-scan duration.
- Deposit detection -> credit latency.
- **RPC health**: per-provider error rate, latency, head block delta
  vs. the provider median; provider divergence alerts (see threat
  model T-15).

### Signing and custody

- **Signer health**: per-signer liveness, signing-session success /
  abort rate, session latency, participant availability per wallet.
- Policy rejections at validation and immediately before signing.
- Blacklist hits (validation stage and pre-signing stage separately).
- Withdrawal pipeline stage durations and suspension-switch state.

### Money correctness

- Ledger balance check: total debits == total credits, continuously.
- Reconciliation differences open, by age and chain (see
  `operations/reconciliation.md`).
- Duplicate-deposit constraint violations attempted (should be zero
  successes; attempts indicate indexer bugs).

### Webhooks

- Delivery success rate, retry counts, endpoint latency.
- **Webhook DLQ depth** and oldest DLQ age, per subscription/tenant.
- Outbox unpublished age (event created but not yet delivered).

## 6. SLOs (initial targets)

| Service | Indicator | Target* |
|---|---|---|
| API reads | successful responses | 99.9% / 30 days |
| API mutations | accepted & durably recorded | 99.95% / 30 days |
| Deposit crediting | detection -> credit after threshold | p95 < 15 min |
| Webhook delivery | first attempt within | p95 < 1 min |
| Indexer | lag per chain | p99 < 5 min |
| Signing | session completion once started | 99% |

\* Targets, not guarantees; error budgets govern release decisions,
and burning the budget pauses feature work on that service.

## 7. Alerts (examples)

| Alert | Condition | Sev |
|---|---|---|
| Ledger imbalance | debits != credits at any check | SEV-1 page |
| Signer down | any signer unhealthy > 2 min | SEV-2 page |
| Signing aborts spike | abort rate > 5% / 10 min | SEV-2 page |
| Indexer lag | lag > threshold for 10 min, per chain | SEV-2/3 |
| RPC divergence | providers disagree on head by > N blocks | SEV-2 |
| Reconciliation difference | unexplained diff older than 1 run | SEV-2 |
| Webhook DLQ | oldest entry > 1 h or depth spike | SEV-3 |
| Outbox stuck | unpublished age > 5 min | SEV-2 |
| Suspension active | any withdrawal suspension > 30 min | notify IC list |
| HMAC failure spike | possible credential attack | SEV-3 |

Every page links a runbook: first checks, safe mitigations (including
suspension), escalation path, and the incident-response entry point
(`security/incident-response.md`).

## 8. Dashboards

- **Overview**: SLO burn, SEV alerts, suspension state, chain health.
- **Money**: ledger checks, reconciliation status, deposit/withdrawal
  volumes in integer base units per asset (aggregated, no floats).
- **Custody**: signer health, sessions, policy/blacklist rejections.
- **Chains**: per-chain lag, RPC providers, reorgs, confirmations.
- **Delivery**: webhooks, outbox, DLQ, Temporal queues.

## 9. Health endpoints

- Liveness: process-only; must not depend on DB/RPC (avoids cascades).
- Readiness: DB + Redis for API; signer readiness additionally requires
  its HSM/share store and participant connectivity checks.
- Health responses contain no versions, secrets, or topology details
  beyond a coarse status for unauthenticated callers.

## 10. Retention and access

- Metrics: high-resolution 15 days, downsampled 13 months (target).
- Logs: hot 30 days, archive 1 year (target); audit log retention is
  governed separately and is longer by policy.
- Access to observability is role-based and itself audit-logged;
  production data access is a SEV-relevant event when anomalous.

## 11. Exercises

- Game-day quarterly: kill a signer, stall an indexer, poison an RPC
  provider (in staging), fill a webhook DLQ — verify the alert fires,
  the dashboard explains it, and the runbook works.
- An alert that fires without a runbook, or a runbook step that fails,
  is filed as a defect before the exercise ends.
