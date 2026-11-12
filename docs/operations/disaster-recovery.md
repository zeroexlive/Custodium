# Custodium — Disaster Recovery (Phase 0)

> Status: Phase 0 design document. This system is **not production-ready**.
> All RPO/RTO figures below are **targets, not guarantees**. They become
> meaningful only after restore exercises prove them, repeatedly.

## 1. Scope and assumptions

Covered: PostgreSQL (ledger/tenant data), Redis, Temporal, signer
share recovery, RPC failover, configuration and secrets references.

Not covered by backups alone: funds on-chain. Chain state is recovered
by re-indexing from RPC providers; the ledger is recovered from
PostgreSQL backups/PITR; the two are then reconciled before service
resumes (see `operations/reconciliation.md`).

Fundamental rule: **no backup is trusted until a restore of it has
been performed and verified.** Backup success logs are not evidence.

## 2. Targets (placeholders to validate)

| System | RPO target* | RTO target* | Mechanism |
|---|---|---|---|
| PostgreSQL | <= 5 min | <= 4 h | PITR (WAL archiving) + daily base backups |
| Audit log export | <= 15 min | <= 4 h | Continuous export to object-lock storage |
| Redis | data loss acceptable | <= 1 h | Rebuild; Redis holds no source of truth |
| Temporal | <= 5 min | <= 4 h | Backed by its own PostgreSQL persistence |
| Signer shares | n/a (no single-copy) | <= 24 h | Threshold shares across independent hosts |
| Indexer state | <= 1 h | <= 8 h | Checkpoints + re-scan from chain |
| Configuration | <= 24 h | <= 4 h | Version-controlled config, secret references |

\* Targets, not guarantees, and not SLAs to tenants.

## 3. PostgreSQL backups and PITR

- Continuous WAL archiving to encrypted, versioned object storage in a
  separate account/region from the primary.
- Daily base backups; retention target: 35 days of PITR window, plus
  monthly snapshots retained 12 months.
- Backups are encrypted at rest; backup credentials cannot delete
  within the retention window (object lock / immutability).
- Restore procedure (summary):
  1. Provision an isolated instance; never restore over the primary
     until the incident commander authorises it.
  2. Restore base backup, replay WAL to the chosen point in time —
     typically the last ledger-consistent point before the incident.
  3. Verify: trial balance (debits == credits), row counts vs. audit
     export, tenant isolation spot checks.
  4. Run reconciliation against chain state before reopening writes.
- Ledger rule survives recovery: restored data is still append-only;
  post-restore corrections are new entries referencing the incident.

## 4. Redis

- Redis holds caches, nonce/replay windows, rate limits, and queues
  that are also durable elsewhere. It is **not** a source of truth.
- Recovery is rebuild-and-warm. Financial mutations fail closed while
  replay-protection state is unavailable (see threat model T-11).
- If queue contents are lost, Temporal/outbox state in PostgreSQL is
  authoritative for what must be re-driven.

## 5. Temporal

- Temporal's persistence (its PostgreSQL databases) is backed up and
  restored with the same PITR discipline as the application DB, to a
  consistent point.
- Workers are stateless and redeployed from version-controlled images;
  workflow code versions must remain replay-compatible with in-flight
  histories, or histories are terminated deliberately and re-driven
  from outbox/ledger state — never silently dropped.
- After restore: list workflows stuck in financial states (withdrawal,
  sweep) and reconcile each against ledger and chain before resuming.

## 6. Signer share recovery

- No signer host holds a complete key. Shares exist only as threshold
  shares (CGGMP ECDSA / FROST Ed25519) distributed across independent
  hosts/operators, plus encrypted share backups under split control.
- Loss of one signer host (< threshold): provision a replacement,
  re-share / refresh shares per the protocol's procedure, verify with
  a test signature on a zero-value/test payload, return to service.
- Loss at/above threshold, or suspected share compromise: **do not**
  restore shares into service. Follow the custody compromise playbook
  (`security/incident-response.md`): new wallets, fresh shares, migrate
  funds.
- Share backups are encrypted, access is dual-controlled and audited,
  and a share restore is a SEV-relevant, logged event.
- Share recovery material is never stored alongside database backups
  or in the same account/region blast radius.

## 7. RPC failover

- Each chain has multiple independent RPC providers configured.
- Health-based failover: a provider with elevated errors, latency, or
  head-block divergence is removed from rotation automatically.
- Crediting requires cross-provider agreement (see threat model T-15);
  if no quorum is available, the chain is paused, not degraded to a
  single trusted provider.
- Recovery re-entry: provider rejoins after sustained agreement with
  the median head; indexer re-scans any gap before crediting resumes.

## 8. Secrets and configuration recovery

- Secrets live in a dedicated secret manager; the DR environment
  references the same secret paths — secrets are never copied into
  backups, images, or this document.
- Tenant webhook secrets and sweep resolver URLs are tenant data in
  PostgreSQL (resolver URLs) / secret store, recovered with the DB;
  sweeps after recovery still resolve destinations only via the
  tenant-registered HTTPS resolver returning a plain-text address.
- Infrastructure is code (version-controlled); a region rebuild uses
  the same definitions as production, with DR-specific variables.

## 9. Recovery order

1. Declare incident; choose recovery point/time with the IC.
2. Identity, network, secret manager access.
3. PostgreSQL (app + Temporal) restore and verification.
4. Redis rebuild; Temporal workers; API in read-only mode.
5. Signer availability check (no signing yet).
6. Indexers catch up; reconciliation run to zero unexplained diffs.
7. Webhook/outbox relay resumes (expect duplicate deliveries; they are
   idempotent by design).
8. Sweeps and withdrawals resume last, staged, per incident response.

## 10. Exercises

| Exercise | Frequency* | Proves |
|---|---|---|
| Backup restore to isolated instance + trial balance | Monthly | PITR actually works |
| Full DR game-day (region loss simulation, staging) | Quarterly | RTO target realism |
| Signer host loss + share refresh | Quarterly | Custody recovery |
| RPC provider loss/divergence | Quarterly | Failover + pause logic |
| Temporal restore + stuck-workflow drill | Semi-annual | Workflow recovery |

\* Minimum frequencies once in operation; results, timings vs. targets,
and defects are recorded, and missed targets update this document —
targets are revised to match evidence, not wishful thinking.

## 11. Communication during recovery

- Follow `security/incident-response.md` communications: affected
  tenants get scope, suspension state, and next-update times.
- Recovery claims use measured language: "restored to HH:MM UTC,
  reconciliation in progress" — never "fully recovered" before the
  Section 9 order completes.

## 12. Honest limitations

- DR targets in this Phase 0 document are unproven placeholders until
  exercises measure real RPO/RTO.
- Backups do not protect against a logical attack that is faithfully
  replicated (e.g. fraudulent but well-formed ledger entries); PITR
  point selection and reconciliation are the controls there.
- Nothing here makes the system production-ready.
