# Production Readiness Checklist — Custodium

The single gate list between the current state and a production
approval decision. Statuses are updated only with evidence; the
approval itself is a separate, named, dated, written decision by
the owner (last row). Current verdict: **NOT Production Approved.**

Updated: 2026-11-13 (production-readiness pass).

## Engineering verification

| Gate | Status | Evidence |
|---|---|---|
| Full backend suite on SQLite | ✅ Closed | 178 passed / 1 skipped (see AGENTS.md for the run of record) |
| Full backend suite on **PostgreSQL** (production vendor), incl. wei-scale ledger test and DB-level append-only triggers | ✅ Closed 2026-11-13 | Suite run against a real PostgreSQL (pgserver): **179 passed, 0 skipped**; trigger introspection test fixed to be vendor-aware after PG exposed its SQLite-only query |
| Django production deploy checks | ✅ Closed 2026-11-13 | `manage.py check --deploy` with production settings: **no issues** (HSTS preload added; SECRET_KEY minimum length enforced; proxy SSL header for the nginx topology) |
| Dependency vulnerability scan — Python | ✅ Closed 2026-11-13 | `pip-audit`: no known vulnerabilities |
| Dependency vulnerability scan — Rust | ⏳ Tooling | `cargo audit` run pending its build in the dev VM; pins unchanged since the Phase 3 CVE analysis (cggmp21 rejected; see review package) |
| Dependency vulnerability scan — npm | ⚠️ Blocked here | The sandbox's registry proxy refuses the npm audit endpoint; run `npm audit` in CI or any normal environment before launch |
| Secret scan (tree + full git history) | ✅ Closed 2026-11-13 | No credentials found (only third-party library fixtures inside the untracked local venv) |
| SBOMs produced | ✅ Closed 2026-11-13 | `docs/security/sbom/`: backend (CycloneDX), dashboard (CycloneDX), MPC workspace (cargo metadata graph) |
| SSRF socket-level DNS pinning (resolver + webhooks) | ✅ Closed 2026-11-13 | `waas/common/http_pinning.py`; validated IP is the connected IP, hostname preserved for Host/SNI/cert; unit + resolver-path tests |
| Solana priority fees | ✅ Closed 2026-11-13 | Median of recent prioritization fees, hard cap 500k micro-lamports/CU, ComputeBudget instruction prepended; graceful zero when the cluster reports none |
| CI green on `main` | ⚠️ Unverifiable here | Workflow exists (added by the owner via web UI); run results are not visible through the connected tooling — confirm in the GitHub UI |

## External evidence (owner actions — cannot be produced in-repo)

| Gate | Status | Notes |
|---|---|---|
| Independent threshold-crypto review (Engagement A) | ❌ Open | Package + sendable brief ready: `docs/mpc/review/` incl. `commissioning-brief.md`. **Gates production signing.** |
| Production signer implementation (transport, share storage, ceremony orchestration) + its implementation review | ⚠️ Built, review open | Implementation built 2026-11-13 (`services/mpc/crates/signer_service`, `docs/architecture/production-signer.md`) and locally tested; the implementation review (Engagement A scope) has not happened, and the Django activation gate stays off until it passes |
| Independent penetration test (Engagement B) | ❌ Open | Brief in the same commissioning document |
| Legal / compliance review | ❌ Open | Custody licensing per operating jurisdiction |
| Funded testnet soaks, all five chains (deposit → credit → withdrawal → sweep, reconciliation clean) | ❌ Open | Requires network egress + faucet funds; never executed from the dev sandbox |
| Live deployment rehearsal (installer + 6-server topology on real hosts), backup/restore + DR drills, key ceremony + share-restore drills | ❌ Open | Procedures written (`docs/operations/`); execution needs infrastructure |
| Temporal wiring (spec deviation) | ⚠️ Accepted deviation for now | Worker entrypoints are idempotent management commands on a schedule (deployment tutorials give the cadence); revisit before scale-out |
| TON Wallet V5, outbound Jetton bounce tracking, storage-fee drift accounting | ⚠️ Known limitations | Recorded in the TON implementation record; reconciliation halts are the compensating control for accounting drift |
| **Production approval decision** (named, dated, written) | ❌ Not granted | Only after every ❌ above closes |
