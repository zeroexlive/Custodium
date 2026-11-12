# Incident Response Runbooks

Status: Phase 12 (2026-11-12). Every procedure uses mechanisms
that exist in the codebase today; anything requiring tooling
that does not exist yet is marked **[GAP]** and must be closed
before production approval.

## 0. Universal first move — stop the money

1. **Activate the platform halt** (kill switch):
   `POST /api/v1/operator/platform-halt` (staff only)
   `{"active": true, "reason": "<incident id>"}`.
   Effect: withdrawal and sweep creation refuse; dispatch and
   sweep processing fail closed. Indexing and deposits continue
   (crediting is safe; it does not move money out).
2. Announce the halt reason + incident id in the audit trail —
   the halt call itself is audit-logged
   (`operator.platform_halt_changed`).
3. Preserve evidence: audit log export
   (`GET /api/v1/audit-logs/export`), journal export per
   project, worker logs. The ledger and audit tables are
   DB-append-only, so history cannot be rewritten by an
   attacker with application access alone.

## 1. Suspected key compromise (tenant API key)

1. Platform halt if scope is unclear (step 0).
2. Revoke the API key (console → API Keys, or revoke endpoint).
   Revocation is immediate for HMAC auth (status checked per
   request).
3. Review the audit log + journal for the key's project:
   filter `api_key_id`; every machine action is attributable.
4. Rotate: create a replacement key, have the tenant switch,
   confirm the old secret no longer authenticates.
5. If withdrawals left under the key: they required policy
   approvals per Phase 9; enumerate them from the withdrawal
   list and reconcile against chain state via the lookup API.

## 2. Suspected MPC / signer compromise

1. Platform halt. **Do not** attempt any signing.
2. Custodium's Django tier cannot sign unilaterally and holds
   no shares; the exposure surface is the MPC service tier.
   Follow `docs/mpc/` procedures; production signing remains
   disabled until the Phase 3 independent review is complete,
   so a live compromise of this class presupposes a post-review
   deployment.
3. Post-incident: re-key (new DKG) and migrate funds to fresh
   addresses before unhalting — never resume signing with
   suspect shares. Note the Phase 3 finding: cggmp24 has no key
   refresh, so re-key + migrate is the only path.

## 3. Chain reorganization beyond parameters

Symptoms: reconciliation halts raised by `run_reconciliation`,
deposits flipping to `reorged_out`.

1. The affected network halts automatically
   (ReconciliationHalt) — withdrawals on it refuse.
2. Inspect the reconciliation report (`run_reconciliation`
   output; per-asset expected vs ledger custody).
3. Confirm the reorg depth against an independent explorer /
   second provider. The indexer reverses credited deposits via
   ledger REVERSAL entries; verify trial balance returns to 0
   and no customer was allowed to withdraw un-credited funds
   (reservations only draw on `customer_available`).
4. Clear the halt only after the report is clean for a full
   confirmation window: re-run reconciliation, then deactivate
   the network's halt row (operator action, audited via the
   reconciliation command's own logging).

## 4. Provider outage / divergence

1. EVM provider fails over across configured endpoints and
   fails **closed** on chain-id mismatch — a wrong-chain
   endpoint can never be signed against.
2. If all endpoints for a network are down: indexing cursors
   stop advancing (no data loss; scanners resume from the
   stored cursor), withdrawals for that network cannot
   broadcast and remain in their pre-broadcast states.
3. Do not hand-edit cursors or transactions. Restore provider
   access, watch the scanner catch up, then reconcile.

## 5. Sweep-resolver compromise (tenant endpoint)

1. The tenant (owner/administrator) disables or replaces the
   endpoint in the console — history rows preserve the hash
   timeline for forensics.
2. Sweeps not yet approved re-resolve against the *current*
   endpoint at processing time; sweeps already approved carry
   immutable snapshots: **review every `awaiting_approval` /
   `resolved` sweep's snapshot destination** before processing
   resumes, and reject any whose destination is not expected.
3. A completed sweep to a wrong destination is a chain-level
   loss: follow §1 evidence steps and the tenant's own
   incident process. This is precisely why approval quorum
   defaults and snapshot review exist.

## 6. Webhook endpoint abuse / secret leak

Disable the endpoint (deliveries stop), create a new endpoint
(new secret), replay only deliveries the tenant confirms as
missed. Event ids make replays safe for idempotent receivers.

## 7. Unhalting

All of: root cause identified; reconciliation clean on every
network; a second operator reviews the halt reason + evidence;
deactivate via the same operator endpoint (audited). Record
the incident timeline in the incident ticket, not in code.
