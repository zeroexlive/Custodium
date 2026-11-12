# Hardening & Production Preparation — Phase 12 Record

Status: **Implemented (preparation scope)** (2026-11-12).

**Custodium is NOT Production Approved.** Per the backlog's own
exit criteria, production approval requires a named, dated,
written decision — separate from this record — after an
independent security review with no open critical/high
findings. That review has not happened. This phase prepares
evidence and closes the code-level hardening items that were
deferred to it; it does not declare readiness.

## 1. What was built in this phase

- **Database-level append-only enforcement** (deferred from
  Phase 2, ADR 0007): migration `ledger.0003` installs
  triggers — shared `custodium_forbid_change()` function on
  PostgreSQL, RAISE(ABORT) triggers on SQLite — forbidding
  UPDATE and DELETE on `ledger_journal_entry`,
  `ledger_journal_line`, `audit_audit_event`, and
  `sweeps_resolveddestinationsnapshot`. The model-layer rules
  remain; history now cannot be rewritten even with raw SQL or
  console access. Verified: raw UPDATE/DELETE statements
  against all guarded tables raise, appends still work, and
  the full suite passes with triggers active.
- **Platform kill switch** (`PlatformHalt`): a single global
  halt, staff-operator controlled via
  `GET/POST /api/v1/operator/platform-halt` (activation
  requires a reason; every change audit-logged). While active:
  withdrawal creation and dispatch refuse, sweep creation
  refuses, sweep processing fails closed — complementing the
  per-network reconciliation halts from Phase 9.
- **Health/readiness probes**: `/healthz` (liveness) and
  `/readyz` (database-checked readiness) for orchestrator
  gating.
- **Runbooks** (all procedures reference mechanisms that exist
  in code): `docs/operations/incident-response.md`
  (compromise, MPC compromise, deep reorg, provider outage,
  resolver compromise, webhook leak, unhalt procedure),
  `docs/operations/key-ceremony.md` (roles, DKG verification,
  backup/restore drills, re-key reality for cggmp24),
  `docs/operations/mainnet-rollout-plan.md` (preconditions,
  staged caps, standing controls, rollback).

## 2. Readiness assessment against the Phase 12 exit criteria

| Criterion | Status |
|---|---|
| Independent security review / pentest, incl. MPC + resolver | **OPEN — not commissioned** (review package ready since Phase 3, `docs/mpc/review/`; William's action) |
| Remediation of critical/high findings | Cannot start until the review exists |
| Key ceremony procedures + restore drills | Procedures written (this phase); **drills not executed** (no production signer deployment exists to drill against) |
| Load / chaos / DR testing (Temporal, PostgreSQL restore) | **OPEN** — Temporal was never wired (worker commands are the entrypoints); PostgreSQL restore drills require deployment infrastructure that does not exist in this environment |
| Secrets/KMS hardening | Partially in place by design: Fernet envelope encryption for API/webhook/sweep secrets, production settings refuse placeholder keys; **KEK custody (ADR 0005) is a deployment decision, not code** |
| Compliance / legal review | **OPEN** — outside engineering scope |
| Phased rollout plan | Written (this phase) |
| Live-chain verification (all phases) | **OPEN** — every chain verified against local doubles + differential proofs; no funded testnet round-trip has run (sandbox egress) |
| Production approval decision | **NOT GRANTED** — Custodium remains **Implemented/Tested** for in-scope features, **not Security Reviewed, not Production Approved** |

## 3. Verification performed for this phase

Backend suite, frontend checks, Rust workspace tests, and a
fresh migration run: see `AGENTS.md` for the exact numbers.
The trigger migration was applied to a fresh database and the
full test suite runs with triggers active (SQLite path); the
PostgreSQL trigger/function SQL is written for the production
vendor but **not executed against a live PostgreSQL in this
environment** — it must be smoke-tested at deployment time
(`migrate`, then attempt an UPDATE on a journal row in a
scratch database and confirm rejection).

## 4. Standing gates (unchanged, restated for the final record)

- Production signing: **disabled** (only fail-closed signers
  are wired) until the independent review lands.
- Wallets remain `provisioning`; address derivation stays
  behind the Phase 3 gate.
- The platform is a faithful, tested implementation of the
  Phase 0 design against local doubles; the gap to production
  is evidence (reviews, live-chain soaks, drills), not
  features.
