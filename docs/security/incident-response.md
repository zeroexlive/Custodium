# Custodium — Incident Response (Phase 0)

> Status: Phase 0 design document. This system is **not production-ready**.
> This plan must be exercised with tabletop drills before any real-funds
> use; an untested plan is a hypothesis.

## 1. Principles

1. Protect funds first: pausing withdrawals is always acceptable.
2. Preserve evidence before remediation destroys it.
3. The double-entry ledger and append-only audit log are evidence;
   never edit them to "fix" an incident.
4. Communicate early with what is known, unknown, and next update time.
5. One incident commander (IC) decides; specialists advise.

## 2. Roles

| Role | Responsibility |
|---|---|
| Incident Commander | Severity, decisions, timeline, stand-down |
| Custody / Signing Lead | Signer state, withdrawal suspension, key actions |
| Platform Lead | API, DB, workers, Temporal, RPC failover |
| Forensics Lead | Log/evidence preservation, scoping |
| Communications Lead | Tenant, internal, and public communications |
| Scribe | Timestamped incident record |

One person may hold two roles in a small incident, except IC and
Forensics Lead should differ when compromise is suspected.

## 3. Severity levels

| Sev | Definition | Examples | Response target* |
|---|---|---|---|
| SEV-1 | Funds at risk/lost, key compromise, cross-tenant breach | Signer compromise, collusion suspected, unauthorised withdrawal executed | Immediate, all-hands |
| SEV-2 | Security control failure without confirmed fund loss | Tenant credential compromise at scale, ledger imbalance found | < 1 hour |
| SEV-3 | Contained security event or major availability loss | Single tenant key leaked and revoked, prolonged RPC failure | Same business day |
| SEV-4 | Minor event, suspicious activity, near miss | Repeated failed HMAC checks, single malicious-token attempt | Triage queue |

\* Targets are planning targets, not guarantees or SLAs.

## 4. Detection sources

- Monitoring/alerts (see `operations/monitoring.md`): signer health,
  ledger-balance checks, reconciliation differences, webhook DLQ.
- Tenant reports of unknown withdrawals or deposits.
- MPC participant reports of unexpected signing sessions.
- Blacklist hits immediately before signing.
- External reports (researchers, RPC providers, chain incidents).

## 5. First actions (any SEV-1/SEV-2)

1. Declare the incident, assign IC and Scribe, open the incident record.
2. Snapshot state: time (UTC), affected tenants/projects/chains, last
   known-good reconciliation and ledger-balance check.
3. If funds may move: suspend withdrawals and signing (Section 6).
4. Preserve evidence (Section 8) before rotating or restarting anything.
5. Start a single communications channel; no side-channel decisions.

## 6. Withdrawal and signing suspension

- **Levels**: per-tenant, per-chain, per-asset, or global suspension.
  Prefer the narrowest level that stops the suspected loss.
- Suspension blocks: new withdrawal validation, signing sessions, and
  sweep execution. Deposits may continue to be observed/indexed, but
  crediting can be paused if attribution or ledger integrity is in doubt.
- The suspension switch is platform-admin only, dual-controlled for
  lifting a global SEV-1 suspension, and fully audit-logged.
- Sweep destinations are never improvised during an incident: sweeps
  still resolve only via the tenant-registered HTTPS resolver endpoint
  returning a plain-text address, or they do not run.
- Record who suspended, when, scope, and the lifting criteria at the
  moment of suspension.

## 7. Custody / key compromise playbook

Treat as SEV-1 if any of the following is credible:

- A signer host/share is exfiltrated or accessed by an outsider.
- MPC participants at/above threshold may be colluding/compromised.
- Signing sessions occurred that no valid request explains.

Actions:

1. Globally suspend signing and withdrawals immediately.
2. Isolate signer hosts (network quarantine) **without** wiping them;
   capture disk/memory images where feasible for forensics.
3. Revoke signer credentials, API tokens, and inter-service secrets
   that a compromised host could hold.
4. Inventory: which wallets/shares lived on affected signers, which
   signing sessions ran in the exposure window, what was signed.
5. Do **not** attempt to reuse possibly-compromised shares. Plan wallet
   migration: generate new wallets under fresh shares/participants and
   move funds to them once a clean signing path exists.
6. Assume any transaction signed in the window is hostile until its
   payload hash is matched to an audited, tenant-valid request.
7. Notify affected tenants per Section 9 before resuming any signing.

## 8. Credential compromise (tenant or platform)

1. Revoke the specific API keys/HMAC secrets immediately; revocation is
   per key, per project, or per tenant depending on scope evidence.
2. Rotate webhook signing secrets for affected subscriptions.
3. Review audit log for actions taken with the compromised key:
   withdrawals, resolver-URL changes, blacklist changes, key creation.
4. Resolver URL changes in the window are treated as hostile until the
   tenant confirms them out-of-band.
5. Issue new credentials only through the normal secure channel; never
   send secrets by email or chat.

## 9. Forensics — preserving audit and ledger

- Export and hash: audit log segment, ledger entries, signer session
  logs, API access logs, Temporal histories, indexer state, DB WAL /
  PITR point. Store copies in write-once / object-lock storage.
- Ledger rule: **no updates or deletes, ever.** Corrections after the
  incident are new reversing entries referencing the incident ID.
- Maintain chain of custody: who exported what, when, hash values.
- Clock discipline: record all times in UTC; note any host clock skew.
- Legal hold: once litigation/regulatory action is plausible, deletion
  and rotation of evidence stops until counsel clears it.

## 10. Communications

- **Internal**: status updates at a cadence set by the IC (e.g. hourly
  for SEV-1), in the incident record only.
- **Affected tenants**: notify promptly with: what happened (known
  facts), whether their funds/keys are affected, what we suspended,
  what we need from them (e.g. credential rotation, resolver
  confirmation), and the next update time. Do not speculate on cause
  or attribute blame before forensics supports it.
- **Unaffected tenants**: notify if a global suspension affects them,
  with scope and expected review cadence — without disclosing another
  tenant's details, including their blacklist entries or balances.
- **Public/regulatory**: only via Communications Lead with legal review.
- Never include secrets, key-share material, or other tenants' data in
  any incident communication.

## 11. Recovery

1. Entry criteria are written before recovery starts: root cause or a
   bounded scope, compromised material replaced, controls verified.
2. Restore services in order: read-only API -> indexing/reconciliation
   -> deposit crediting -> sweeps -> withdrawals/signing (last).
3. Re-run reconciliation for the full exposure window; zero unexplained
   differences (see `operations/reconciliation.md`) before withdrawals
   resume.
4. Lift suspensions in stages (per-chain, then per-tenant), dual
   controlled for SEV-1, with heightened monitoring at each stage.
5. Migrated wallets (Section 7) are verified by test transactions of
   minimal value before balances move, using exact integer amounts.

## 12. Postmortem

- Due within 5 business days of stand-down for SEV-1/SEV-2.
- Blameless, timestamped, evidence-linked: timeline, root cause,
  detection gap, response gap, tenant impact, fund impact.
- Action items have owners and dates; security action items are tracked
  to completion and referenced from the threat model.
- Update this plan, the threat model, and runbooks with what was learned.
- Share a tenant-appropriate summary with affected tenants.

## 13. Exercises and maintenance

- Tabletop exercise quarterly, rotating scenarios: signer compromise,
  tenant credential leak, malicious sweep resolver, ledger imbalance,
  deep reorg, RPC manipulation.
- Verify contact lists, suspension switches, and evidence export steps
  during each exercise — switches that are never tested are assumed broken.
- Review this document after every incident and every exercise.
