# AGENTS.md — Custodium Agent Record & History

> **Mandatory record-keeping (William, 2026-11-12):** Every agent working on
> this repository MUST update this file. Before finishing any work session:
> (1) update the Phase Status table, (2) append a dated entry to the History
> Log — what was done, what was *actually* verified (exact commands/tests),
> what was NOT verified and why, and what remains. Never rewrite or delete
> old history entries; correct them only by appending a new entry that says
> what it corrects. Never claim a test/build/review happened if it did not.
> This file is how any future agent reconstructs what happened here.

## Project

**Custodium** — Enterprise multi-chain MPC Wallet-as-a-Service (WaaS).
GitHub: `zeroexlive/Custodium`. Owner: William (GitHub `zeroexlive`).

- Backend: Python 3.12, Django **5.2 LTS** (supported to Apr 2028), Django Ninja, PostgreSQL, Redis, Temporal
- Frontend: Vue 3, TypeScript (strict), Vite, Tailwind CSS, Pinia, Vue Router, TanStack Vue Query
- MPC: Rust, threshold ECDSA (candidate: dfns/cggmp21, CGGMP21), threshold Ed25519 (candidate: ZF FROST `frost-ed25519`, RFC 9591) — candidates only, pending pinning + independent review
- Chains: Ethereum, BNB Smart Chain, TRON, Solana, TON — native assets, USDT, registered compatible tokens
- Full specification: William's Master Engineering Prompt (2026-11-12, in project chat/docs). Summaries in `docs/`.

## Non-negotiable rules

1. **Per-phase workflow (William):** develop each phase locally → verify →
   commit ALL of that phase's files in **one commit** → push → merge to `main`.
   No piecemeal commits, no unverified merges, keep `main` stable.
2. **No fake MPC.** No mock signers in production paths, no single-key or
   Shamir signing disguised as MPC, no private shares in Postgres app tables,
   logs, or API responses. Django can never sign unilaterally. Signing stays
   disabled until Phase 3 + independent cryptographic review.
3. **Never claim production-ready** without verification, independent crypto
   review, operational controls and realistic end-to-end testing. Use the
   status taxonomy: Planned / In Progress / Implemented / Tested /
   Security Reviewed / Production Approved.
4. **Sweep destinations** come ONLY from the tenant/project's registered
   HTTPS resolver endpoint (stored in PostgreSQL), which returns exactly one
   plain-text address. Never accept a destination in a sweep request, never
   read one from local files/config. Immutable snapshot per sweep, fail closed.
5. **Manual blacklist only.** No AML/KYT/sanctions/risk-scoring integrations,
   and never describe the blacklist as an AML system.
6. **Money is exact:** integer base units, double-entry append-only ledger,
   no floats for money, idempotent financial operations.
7. **Token identity ≠ symbol:** network + contract/mint/master (+ program).
   BSC USDT (`0x55d398326f99059fF775485246999027B3197955`, 18 dp) is
   Binance-Peg, **not** Tether-native. Verified USDT table lives in
   `docs/blockchains/capability-matrix.md`.
8. **Tenant isolation everywhere:** tenant/project context is derived from
   authenticated identity, never trusted from request bodies.
9. **Dashboard honesty:** no invented financial data/charts. Real API data,
   loading states, honest empty states only. UI design direction is in
   `apps/dashboard/DESIGN.md` (inspired by a reference William supplied —
   inspiration only, our own labels/content).

## Phase status — 13 phases (Phase 0 to Phase 12)

| Phase | Name | Status |
|---|---|---|
| 0 | Architecture & Security Research | Implemented (verified locally 2026-11-12; not Security Reviewed / Production Approved) |
| 1 | Repository & SaaS Foundation | Implemented — merged to `main` on GitHub 2026-11-12 (PR #2, merge `560c56c`); CI file added by William via web UI (commit `268b5c3`, verified byte-identical); not Security Reviewed / Production Approved |
| 2 | Wallet & Asset Foundation | Implemented — merged to `main` on GitHub 2026-11-12 (PR #3, merge `b0ba530`); not Security Reviewed / Production Approved |
| 3 | MPC Infrastructure | Implemented (evaluation) 2026-11-12 — candidates executed test-only; cggmp21 REJECTED (see history); production signing still disabled, independent review NOT commissioned |
| 4 | Ethereum & BSC | Planned |
| 5 | Blockchain Indexing & Lookup | Planned |
| 6 | TRON | Planned |
| 7 | Solana | Planned |
| 8 | TON | Planned |
| 9 | Financial Operations (deposits, withdrawals, ledger, webhooks) | Planned |
| 10 | Sweeping & Treasury | Planned |
| 11 | SaaS Product Completion | Planned |
| 12 | Hardening & Production Preparation | Planned |

## Environment notes (this dev VM, 2026-11-12)

- Python 3.12.3, Node v24 / npm 10, `uv` 0.13.7 installed at `~/.local/bin/uv`
- **Not available in VM:** cargo/rustc, docker, psql — Rust code and Docker
  Compose therefore cannot be executed/verified here until tooling exists;
  record that honestly wherever it applies.
- Local backend dev uses SQLite by default; PostgreSQL via `DATABASE_URL`
  / Docker Compose.

## History log (append-only, newest at bottom)

### 2026-11-12 — Project start
- GitHub connected as `zeroexlive`; repo cloned to `~/workspace/Custodium`.
  At clone: only initial commit `5ab07b4`, empty README, branches `main` and
  `wip-phase-0-phase-1` at the same commit.
- William supplied the Master Engineering Prompt (13 phases, Phase 0 → 12).
- William set the per-phase workflow: local dev → verify → ONE commit for
  all phase files → push → merge to `main`.
- Research verified: Django 5.2 LTS (5.2.19, 2026-11-03, supported to
  Apr 2028) chosen over 6.1; cggmp21 (Kudelski audit, key refresh; note
  TSSHOCK affected some CGGMP21 implementations) and ZF FROST (RFC 9591,
  NCC audit 2023; secp256k1-tr outside audit scope) recorded as candidates;
  USDT contract/mint/master addresses verified per network (see rule 7).

### 2026-11-12 — Phase 0 docs & MPC skeleton & dashboard (parallel work)
- Phase 0 documentation under `docs/` (PRD, architecture, diagrams, ERD,
  threat model, MPC evaluation, chain docs, ADRs, backlog) — in progress.
- Rust MPC workspace `services/mpc/` + `packages/proto/mpc/mpc.proto`:
  fail-closed scaffold. `signing_policy`/`secure_transport` contain real
  pure validation logic with unit tests **written but NOT executed**
  (cargo not installed). Threshold keygen/sign return `NotImplemented`.
  No fake signing anywhere.
- Vue dashboard `apps/dashboard/` (40 files): Phase 1 views wired
  (auth, organizations, projects, API keys with show-secret-once, assets,
  transaction lookup form, sweep-endpoint form); Phase 2+ views are
  labelled placeholders with no fake data. `npm install`/build/typecheck
  **not yet run** — required in Phase 1 verification.
- William supplied a dashboard design reference (Hintora-style). Applied
  as inspiration only: lavender canvas, floating white shell, grouped
  sidebar + dark-pill active item, black primary buttons, blue accents,
  KPI cards — in `tailwind.config.ts`, `style.css`, `DashboardLayout.vue`,
  `Card.vue`, `Button.vue`, `OverviewView.vue`; rationale in
  `apps/dashboard/DESIGN.md`.

### 2026-11-12 — Record-keeping rule + backend start
- William instructed: always write records in this agent file so any
  agent knows the history. This file was created in response; the rule is
  at the top and is binding on all future work.
- Phase 1 Django backend development started: directory/module skeleton
  created under `apps/backend/` (config/settings, waas modules, chains,
  integrations, tests). Implementation files follow in Phase 1 entries.

### 2026-11-12 — Phase 0 documentation COMPLETE (not yet committed)
- 45 files, 8,353 lines under `docs/`: PRD; architecture (system overview,
  component / trust-boundary / data-flow Mermaid diagrams, deployment,
  module responsibility map, ledger); domain (bounded contexts,
  invariants, ledger); database (ERD for the 42 conceptual entities,
  indexing strategy); API (auth/HMAC design, wallet API, transaction
  lookup, sweep resolver per spec §17 in full); MPC (protocol evaluation —
  cggmp21 + frost-ed25519 both PENDING independent review, key management,
  signer security); blockchains (capability matrix + per-chain docs with
  verified USDT identities; BSC = Binance-Peg, not Tether-native);
  security (STRIDE threat model T-01–T-19, tenant isolation, incident
  response); integrations (Python/TS SDK design, webhooks/outbox);
  operations (monitoring, reconciliation, disaster recovery); manual
  blacklist (explicitly NOT AML/KYT); ADRs 0001–0007; roadmap (backlog
  Phases 0–12, Phase 1 acceptance criteria).
- Verified by lead: `find docs -type f | wc -l` = 45, `wc -l` total 8,353;
  grep confirmed ETH USDT address in matrix + ethereum docs, Binance-Peg
  classification in matrix + BSC docs, no positive "production-ready"
  claim (only status-gate wording), Mermaid blocks present in 6 files.
- NOT verified: markdown lint, link checking, Mermaid rendering
  (diagrams structurally written, not rendered); external facts were
  supplied pre-verified by lead research and grep-checked, not
  re-researched by the docs author.
- Remaining for Phase 0: lead's final check of the MPC/proto skeleton,
  then the single Phase 0 commit → push → merge to `main`.

### 2026-11-12 — Phase 0 verification & skeleton completion
- Lead verified the MPC/proto skeleton: 36 fail-closed references
  (`NotImplemented` / `ProductionSigningDisabled`) across the Rust crates;
  grep found NO private-key/secret-key/raw-share/seed types or fields in
  `services/mpc/crates` or `packages/proto`; `mpc.proto` defines
  Coordinator + Signer services as specified; 10 Rust unit tests are
  written (7 signing_policy, 3 secure_transport) but **NOT executed —
  cargo/rustc are not installed in this VM**.
- Repository skeleton completed: `infrastructure/`, root `tests/`,
  `scripts/`, `.github/workflows/` placeholder directories added.
- Phase 0 is committed as ONE commit containing `docs/`, `AGENTS.md`,
  `services/`, `packages/`, `infrastructure/`, `tests/`, `scripts/`,
  `.github/` (the Phase 0 commit hash and merge result are recorded in
  the first Phase 1 history entry, since a commit cannot contain its
  own hash). Phase 1 files under `apps/` are deliberately NOT in the
  Phase 0 commit.

### 2026-11-12 — CORRECTION: Phase 0 is NOT on GitHub yet (push blocker)
- A `git push` of the Phase 0 commit reported success, but verification
  against the real GitHub API (`list_commits`, `get_file_contents`,
  `git ls-remote`) proved it did NOT persist: both remote branches are
  still at the initial commit `5ab07b4`. Plain `git push` from this VM
  has no GitHub credentials (`could not read Username`); public-repo
  clone/fetch work anonymously, pushes do not.
- The sanctioned write path is the GitHub connector snapshot push
  (`github push-files`, OAuth + approval). First attempt for the 85
  Phase 0 files failed: `403 Resource not accessible by integration`
  when creating a tree — the Muse GitHub App is not installed on this
  repository with write access (OAuth authorization alone is read-level
  here; the app-install/repository-selection step was never completed).
- Local state is safe: Phase 0 exists as a single local commit on
  `wip-phase-0-phase-1` (amended as entries were added). Nothing has
  been merged to `main` anywhere. Unblock: William installs the Muse
  GitHub App on `zeroexlive/Custodium`, then the lead retries the
  snapshot push → PR → merge, verifies remote `main`, and records the
  remote SHAs in the next entry.
- Retry on 2026-11-12 after William said "try now": same 403
  (`Resource not accessible by integration` at git/trees) — the app
  installation still does not cover this repository with write access.
  Most likely the install flow completed without selecting Custodium
  (e.g. a different account, or "only select repositories" without it).
- Meanwhile Phase 1 backend was implemented and verified locally
  (details in the Phase 1 entry): pytest 15 passed, ruff clean.

### 2026-11-12 — Phase 1 IMPLEMENTED & VERIFIED LOCALLY (push still blocked)
- Backend (`apps/backend/`, Django 5.2 LTS + Ninja 1.8, Python 3.12):
  custom email user; registration + email verification + login/logout
  (revocable hashed dashboard bearer tokens) + password reset; organizations
  & memberships (owner/administrator/developer/finance_operator/
  withdrawal_approver/viewer); projects (sandbox/production); API keys —
  create/list/rotate/revoke, secret shown once, Fernet-encrypted at rest,
  scopes validated; HMAC-SHA256 machine auth (canonical method/path+query/
  timestamp/nonce/body-SHA256, 300 s window, per-key nonce replay
  protection, constant-time compare) with tenant context derived from the
  credential; `/api/v1/machine/whoami` acceptance endpoint; network/asset
  registry + `seed_networks_assets` (10 networks, 15 assets — exact
  verified USDT identities, BSC = bridged_pegged, deposits/withdrawals
  disabled); audit log API; phase gates return 501 (tx lookup → Phase 5,
  sweep endpoint → Phase 10). Migrations generated for all 7 apps.
- Dashboard (`apps/dashboard/`): as recorded earlier + design system from
  William's reference; `tsconfig` include fix (config files belong to
  `tsconfig.node.json`, TS6305), Vite proxy target now env-configurable
  for Compose.
- Root/CI: README, CONTRIBUTING, SECURITY, .gitignore, .env.example,
  .editorconfig, Makefile, docker-compose (Postgres 17, Redis 7,
  Temporal dev server, backend, dashboard), Dockerfiles,
  `.github/workflows/ci.yml` (backend, dashboard, mpc-skeleton jobs).
- VERIFIED (actually run): backend `uv run pytest` → **15 passed**;
  `uv run ruff check .` → clean (migrations excluded by config);
  `manage.py check` → no issues; migrate + seed smoke on a temp SQLite
  DB → OK ("Seeded 10 networks, 15 assets"); frontend `npm install`,
  `npm run typecheck` → clean, `npm test` (Vitest) → **4 passed**,
  `npm run build` → success.
- NOT verified: Docker Compose stack (docker not installed in this VM);
  Rust cargo tests (cargo not installed; CI job exists); Temporal is
  provided as a Compose dev service only — no workflow code exists yet
  (workflows arrive with their phases); email delivery (dev/test expose
  tokens in responses by design; production settings refuse that).
- Phase 1 is committed locally as ONE commit (apps/, root files, CI,
  AGENTS.md update). Push/merge for BOTH phases awaits the same unblock:
  Muse GitHub App installation covering `zeroexlive/Custodium`.

### 2026-11-12 — GitHub unblocked; Phase 0 PUSHED & MERGED to main
- William set the Muse GitHub App installation to **all repositories**.
  The earlier snapshot 403 is resolved.
- Phase 0 push used the connector snapshot procedure (plain `git push`
  has no credentials in this VM): 84 paths (the deleted placeholder
  `.github/workflows/.gitkeep` was dropped from the manifest — it was
  superseded by the real CI workflow in Phase 1). Remote branch commit:
  `06173a53a0f6e3630bb220db3d7669a807d85ab6` on `wip-phase-0-phase-1`,
  verified via `list_commits`. Sync record written to
  `~/workspace/Custodium.muse-github-snapshot-sync.json` (outside repo).
- PR **#1** created and merged to `main` (merge commit
  `4e347749bcf5b645a8dbced332a27bec25627ae9`). Verified on remote `main`:
  commit list [merge, Phase 0, initial] and `docs/prd/product-requirements.md`
  readable. Phase 0 status: Implemented on GitHub `main`.
- Phase 1 push follows immediately in the next entry (its snapshot
  carries this record).
- Phase 1 snapshot attempt (2026-11-12, twice): `push-files` failed at
  git/trees with the same 403. Diagnosis: the only path class not
  present in the successful Phase 0 push is `.github/workflows/ci.yml` —
  GitHub requires the **Workflows** permission for an integration to
  create workflow files, and the Muse app token apparently does not
  carry it, so the whole tree is rejected. Everything else in the
  manifest is ordinary content. Resolution chosen by William
  (2026-11-12): push the Phase 1 snapshot without `ci.yml`
  (160 paths), merge, and add `ci.yml` manually via the GitHub web UI
  once (its full content is in the local repo). Outstanding after the
  merge: William adds `.github/workflows/ci.yml` on GitHub; until then
  the repo has no CI — do not claim CI is active.
- Outcome: Phase 1 snapshot (160 paths) pushed cleanly in ~23 s once
  `ci.yml` was excluded — confirming the Workflows-permission diagnosis.
  Branch commit `db4a81994763e997eef100bc481f9fa499505775`; sync record
  appended. PR **#2** merged to `main`, merge commit
  `560c56c0d42b6138c6f45168277965100bd57da8`. Verified on remote `main`:
  commits [P1 merge, P1, P0 merge, P0, initial] and
  `apps/backend/pyproject.toml` readable. Local branches realigned to
  origin afterwards; this entry rides the Phase 2 commit.
- Phases 0 and 1 are now both complete on GitHub `main`. Next: Phase 2
  (Wallet & Asset Foundation).
- CI: William added `.github/workflows/ci.yml` via the web UI
  (commit `268b5c3` on `main`), verified byte-identical to the prepared
  file. CI run results are not visible through the Muse connector;
  the `mpc-skeleton` job runs the Rust tests for the first time
  anywhere — treat its first result as unverified until seen.

### 2026-11-12 — Phase 2 IMPLEMENTED & VERIFIED LOCALLY (Wallet & Asset Foundation)
- **Ledger (ADR 0007)** — `waas/modules/ledger/`: chart-of-accounts
  accounts per project+asset (+ optional wallet / customer sub-scope);
  journal entries + lines, amounts NUMERIC(78,0) exact integers;
  append-only at the model layer (update/delete raise; DB-trigger
  enforcement is Phase 12 hardening, not present yet); balanced-entry
  enforcement; idempotency keys with payload-hash conflict detection;
  journal-backed reservations (Dr customer_available /
  Cr withdrawal_reserved) with row-locked availability checks —
  double-spend of internal balances is structurally prevented;
  settle/release one-way state machine; reversals as negating entries;
  trial balance always exactly 0. Exit-criteria coverage: invariant,
  duplicate-delivery (idempotent replay) and domain worked-example
  (§11: deposit 100 → reserve/settle 30 → sweep 50, customer claim
  stays 70) tests all pass. True parallel-concurrency testing needs
  PostgreSQL (test DB is in-memory SQLite); protection rests on row
  locks + unique constraints, recorded honestly.
- **SQLite caveat (found by testing):** Django adapts DecimalField
  through float on SQLite, so wei-scale amounts lose exactness there
  (raw sqlite3 INTEGER storage is exact; the ORM path is not). A
  `ledger.W001` system-check warning now fires on SQLite, the
  >64-bit wei test is PostgreSQL-only (skipped on SQLite), and
  PostgreSQL remains the only money-safe database. This is a test/dev
  environment limitation, not a ledger-design change.
- **Wallets** — project-scoped MPC wallet records; status starts
  `provisioning` and CANNOT be activated via API (409) — activation
  happens only when MPC key generation completes (Phase 3); freeze /
  unfreeze / archive transitions with role checks; idempotency-key
  replay on create; machine API with `wallets:write/read` scopes;
  tenant isolation (404, no oracle). Address records are created ONLY
  by the internal `record_derived_address` service (Phases 3-4 will
  call it after real derivation); `POST /wallets/{id}/addresses`
  returns an honest 501 until then. `POST /addresses/resolve` is
  tenant-scoped.
- **Manual blacklist** — platform/tenant scopes per
  `docs/blacklist/manual-blacklist.md` (tenant-admin roles for tenant
  entries, staff for platform, soft-disable only, reasons required,
  expiry honoured); per-chain normalisation in
  `waas/common/address_normalization.py` (EVM lowercase, TRON
  Base58Check→canonical hex, Solana base58/32-byte, TON friendly→raw
  with CRC16 verification); check endpoint returns only
  blacklisted + matched scopes, never reasons. It is a manual list —
  not an AML/KYT system, and is not described as one anywhere.
- **Balances API** — `GET /projects/{id}/balances` and
  `GET /wallets/{id}/balances`: ledger-derived, amounts as integer
  strings, never floats, never chain RPC.
- **Dashboard** — Wallets / Addresses / Blacklist views wired to the
  real APIs (typed client + types, project/org selectors, status
  badges, confirm-gated status actions, raw base-unit balance tables,
  honest 501 notice on Addresses, "not an AML system" copy on
  Blacklist); 5 new client tests.
- VERIFIED (actually run): backend `uv run pytest` → **54 passed,
  1 skipped** (PostgreSQL-only wei-scale branch); `ruff check` clean;
  Django check → only the deliberate `ledger.W001` SQLite warning;
  frontend `npm run typecheck` clean, `npm test` → **9 passed**,
  `npm run build` → success (lead re-ran all frontend checks after
  the dashboard work landed).
- NOT verified: ledger on PostgreSQL (no Postgres/Docker in this VM;
  Compose + CI are the path), threaded concurrency, Docker stack,
  CI run results (see above).
- Phase 2 is committed locally as ONE commit on top of the Phase 1
  snapshot commit; push uses the snapshot procedure (remote wip head
  must be `db4a819...`). Local branches need realigning with origin
  after the merge (origin/main also carries William's ci.yml commit
  `268b5c3`, which the wip branch does not contain — merges handle
  this; the file must not be added to snapshot manifests).
- Outcome: snapshot push (43 paths) → branch commit
  `cecb411b946678a75e1cf90699fc1872899f3928`; PR **#3** merged to
  `main`, merge commit `b0ba530130ca12e8217ef948951dcd6fbb1bba81`.
  Verified on remote `main`: commits [P2 merge, P2, ci.yml, P1 merge,
  ...] and `apps/backend/waas/modules/ledger/services.py` readable.
  Sync record appended (3 entries). Local branches realigned to
  origin; this note rides the Phase 3 commit. Next: Phase 3
  (MPC Integration, test-only) — note it requires the Rust toolchain
  and an independent-review process; neither exists in this VM yet,
  so expect environment work before code.
- Phase 3 prep (2026-11-12): Rust toolchain installed in the dev VM
  (rustup, stable, **rustc/cargo 1.99.1**, minimal profile — the
  rustfmt/clippy components fail to install on this VM's filesystem
  with EPERM, so `cargo fmt`/`cargo clippy` are unavailable here).
  First-ever execution of the MPC skeleton tests:
  `cargo test --workspace` in `services/mpc/` → **10 passed, 0
  failed** (7 signing_policy + 3 secure_transport), workspace
  compiles clean. This closes the Phase 0 "Rust tests written but
  not executed" gap. No Phase 3 feature code yet: DKG/signing
  evaluation and the independent-review track start on William's
  go-ahead.

### 2026-11-12 — Phase 3 EVALUATION COMPLETE (MPC Integration, test-only)
Full record: `docs/mpc/phase-3-evaluation.md`. Production crates
unchanged and still fail-closed; the only new code is the test-only
harness `services/mpc/crates/eval_harness/` (+ env-gated `mpc-eval`
binary, refuses to run without `CUSTODIUM_MPC_EVAL=1` — verified:
exit 2 with refusal message).
- **FROST Ed25519 — pin `frost-ed25519 =3.0.0`.** Real DKG (2-of-3,
  keys::dkg parts 1–3) + threshold signing by all three quorums;
  below-threshold fails; tampered message fails; group signature
  verifies with independent `ed25519-zebra` (standard Ed25519, as
  Solana/TON require). 4 harness tests pass. NCC 2023 audit covers
  an earlier release line — lineage evidence only, 3.0.0 is not
  the audited artifact.
- **ECDSA — Phase 0 candidate REJECTED, successor evaluated.**
  `cggmp21` is not adopted at any version: CVE-2025-66016 /
  RUSTSEC-2025-0129 (critical — missing ZK check in <0.6.3 lets one
  malicious signer reconstruct the full private key; fixed 0.6.3)
  and RUSTSEC-2025-0127 presignature forgery with NO patched
  cggmp21 version; upstream's fix path is `cggmp24`. Evaluated
  instead: **`cggmp24 =0.7.0-alpha.2`** — aux-info generation +
  threshold DKG (2-of-3) + signing by parties {0,2} executed over
  the round-based simulated network; identical signature from all
  parties; verified by the library and independently by k256 as a
  standard secp256k1 ECDSA signature. Ceremony ≈377 s in a debug
  build on this 1.5-vCPU VM (safe-prime generation dominates; not
  a production performance claim).
- cggmp24 risks recorded, not waived: ALPHA line; NO key refresh
  (neither threshold nor non-threshold — cggmp21 had non-threshold
  refresh; compensating control = re-key + migrate, undecided);
  no identifiable abort; t-of-n is the implementers' extension of
  a non-threshold paper; Kudelski audit covers the cggmp21
  codebase, not this alpha; rug/GMP backend mandatory (build needs
  C toolchain + m4; m4 was built from source into ~/tools/m4
  because the VM lacks it and apt has no package lists).
- **Alpha-drift finding:** Cargo resolved `paillier-zk` /
  `cggmp24-keygen` to alpha.4 (breaking API changes) despite the
  alpha.2 requirement — remedied with exact pins + committed
  `services/mpc/Cargo.lock`. In the alpha line the lockfile is
  part of the pin; lockfile updates are security-relevant changes.
- **Review:** package prepared at `docs/mpc/review/` (scope,
  evidence checklist, candidate firms) — **NOT commissioned**
  (William's action). Phase 3 exit criterion (b) is therefore
  open: production signing stays disabled, wallets stay
  `provisioning`, address generation stays gated, nothing may be
  described as reviewed/production-ready. `docs/mpc/
  protocol-evaluation.md` §2 marked superseded accordingly.
- Temporal: ceremony→workflow mapping documented as design only
  (evaluation §6); no Temporal MPC workflow implemented.
- VERIFIED (actually run): `cargo test -p
  custodium-mpc-eval-harness` → **5 passed, 0 failed** (4 FROST +
  1 ECDSA ceremony, 377.11 s total); `cargo build` of the `mpc-eval`
  binary + env-gate refusal check; full-workspace `cargo test
  --workspace` before the Phase 3 commit → **15 passed, 0 failed**
  (5 harness + 3 secure_transport + 7 signing_policy).
- NOT verified: release-build performance, networked/multi-host
  ceremonies (single-process simulation only), FROST refresh
  execution, presignature flows (deliberately untouched),
  HD derivation (feature off).

### 2026-11-12 — Phase 1 verification re-run (dashboard build now verified)
- Re-verified 2026-11-12 ~15:52 local (12:22 UTC), on `wip-phase-0-phase-1`,
  uncommitted Phase 1 work still in the working tree (see status below):
  backend `uv run pytest -q` = **15 passed**, `ruff check .` = clean;
  dashboard `npm run build` (vue-tsc --noEmit + vite build) = **passed**
  (120 modules, built in ~7s) — this closes the earlier "npm install /
  build / typecheck not yet run" gap; dashboard `npm test` (vitest) =
  **4 passed** (2 files). `apps/dashboard/dist/` is gitignored, so the
  build left no stray files.
- NOT verified: dashboard `npm run lint` (eslint) was not run; Rust tests
  still unexecuted (no cargo); Docker Compose / PostgreSQL still not
  runnable in this VM; no Phase 1 commit exists yet — the single Phase 1
  commit → push → merge still waits on the GitHub App write-access
  blocker above (no new retry attempted in this run; remote state could
  NOT be re-checked — `git ls-remote origin` failed with a network error,
  curl 56, so the last confirmed remote state remains 5ab07b4).
- Local branch note for the next agent: local `main` already holds its own
  Phase 0 commit `b86ee8e` (15:43) while `wip-phase-0-phase-1` holds
  `87120ee` (15:51); the two trees differ ONLY in AGENTS.md (27 lines).
  Do NOT treat local `main` as pushed — remote is still at the initial
  commit per the last successful check — and reconcile the duplicate
  Phase 0 history before any merge to `main`.
- NOTE: no formal "Phase 1 entry" exists in this log yet despite the
  correction entry above referring to one; the Phase 1 implementation
  details (endpoints, HMAC auth, registry seeding) still need a proper
  dated entry when the Phase 1 commit is made.
