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
| 3 | MPC Infrastructure | Implemented (evaluation) — merged to `main` 2026-11-12 (PR #4, merge `d7656b6`); cggmp21 REJECTED (see history); production signing still disabled, independent review NOT commissioned |
| 4 | Ethereum & BSC | Implemented — merged to `main` 2026-11-12 (PR #5, merge `5b04197`); live on-chain round-trip NOT verified (sandbox egress + no faucet funds; see history) |
| 5 | Blockchain Indexing & Lookup | Implemented — merged to `main` 2026-11-12 (PR #6, merge `2fe030f`); live-chain scanning NOT verified (sandbox egress; see history) |
| 6 | TRON | Implemented — merged to `main` 2026-11-12 (PR #7, merge `3f68a35`); live-node verification NOT done (sandbox egress; see history) |
| 7 | Solana | Implemented 2026-11-12 — Ed25519 port, message compiler, ATA, balance-delta indexing; live-cluster verification NOT done (sandbox egress; see history) |
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
- Outcome: snapshot push (13 paths) → branch commit
  `f6e68399ec9518ee6ec591faf4f540a59c09d7fc`; PR **#4** merged to
  `main`, merge commit `d7656b65a764cad89aeaefcf8b0582767d96dd4b`,
  verified via GitHub API (main = [P3 merge, P3, P2 merge, ...]).
  Sync record appended (4 entries). Local branches realigned; this
  note rides the Phase 4 commit. Next: Phase 4 (Ethereum & BSC) —
  note its address-generation/signing integration builds on the
  Phase 3 harness patterns, but production signing remains gated
  on the independent review; Phase 4 work must keep test-only keys
  clearly separated from any production path.

### 2026-11-12 — Phase 4 COMPLETE (Ethereum & BSC)
Full record: `docs/blockchains/evm-implementation.md`.
- **New backend module `waas/modules/evm/`**: pure-Python RLP;
  Keccak/address math + ecrecover (`keys.py`, no private keys
  anywhere); EIP-1559 + legacy builders for native and generic
  ERC-20/BEP-20 transfers (`transactions.py`); JSON-RPC provider
  with endpoint failover, **chain-id verification** (wrong chain
  fails closed), revert/nonce/replacement error taxonomy,
  idempotent broadcast, `trust_env=False` (no ambient proxy)
  (`provider.py`); chains bound to registry slugs ethereum(1) /
  ethereum-sepolia(11155111) / bsc(56) / bsc-testnet(97)
  (`chains.py`); dependency added: pycryptodome (Keccak-256,
  verified against canonical vectors).
- **Address integration**: `register_wallet_evm_addresses` derives
  the EVM address from a wallet's MPC group public key and records
  it on all 4 EVM networks via `record_derived_address`. Wallet
  activation semantics unchanged (still review-gated).
- **Withdrawal pipeline** (`service.py` + `EvmTransaction` model):
  reserve → build → sign → broadcast → confirm → settle;
  idempotency keys at the row and every ledger call; blacklist
  check before any state is created; reservation scope = the
  wallet's customer scope; failure semantics incl. the safe one —
  broadcast-outcome-unknown ⇒ DROPPED with the reservation HELD
  (never auto-release: double-pay risk). Signing goes through
  `SignerPort`; the only wired implementation is the fail-closed
  `UnavailableSigner`, so production attempts abort cleanly at
  signing with funds restored (asserted by test). Pipeline is a
  synchronous service mapping 1:1 onto ADR 0003 Temporal
  activities; Temporal itself NOT wired this phase.
- **Cross-proof (the phase's centrepiece)**: Python-built Sepolia
  tx sighashes are pinned as fixtures on BOTH sides; the Rust
  harness signed both digests in ONE cggmp24 ceremony
  (`run_ceremony_for_digests`, `PrehashedDataToSign` — preimages
  are our own constructed transactions, the documented safe case)
  and proved `ecrecover == group-key address` for each. PASSED.
- **Bugs found & fixed**: EIP-55 checksum zip over a 64-char digest
  (mine); Phase 2's `FAMILY_BY_SLUG` said `sepolia` while the
  registry seeds `ethereum-sepolia` — would have broken Sepolia
  address recording in production; map corrected.
- VERIFIED (actually run): backend `pytest` **87 passed, 1
  skipped** (skip = the known PostgreSQL wei-scale case); ruff
  clean. Vectors: EIP-155 canonical sighash AND signed bytes match
  the EIP exactly; RLP wiki vectors; generator-point + EIP-155-key
  addresses. Pipeline tests (doubles): round-trip reconciles
  (trial balance 0), idempotent re-entry (one broadcast),
  signer-unavailable abort + release, insufficient funds,
  on-chain revert + release, blacklist rejection, ERC-20 build.
  Rust: `cargo test --workspace` **16 passed, 0 failed** (6
  harness incl. both ceremonies in 380.58 s, 3 transport, 7
  policy).
- NOT verified: **live RPC** — this sandbox's egress times out to
  every public RPC tried (publicnode ×4 chains, rpc.sepolia.org,
  Cloudflare, Binance seed; attempted directly) — provider covered
  by mock-transport tests instead; **funded testnet broadcast /
  on-chain deposit→withdraw round-trip** (no faucet access from
  here, and deposit indexing is Phase 5 by design); PostgreSQL
  execution; Docker; CI runs (connector cannot read Actions);
  replace-by-fee automation. The backlog's Phase 4 exit criterion
  is met except the on-chain round-trip, recorded as such in the
  implementation doc §6–7. No mainnet enablement.
- Outcome: first two snapshot-push attempts expired unapproved
  (30-min approval cards, 2026-11-12 afternoon); on William's
  retry the push succeeded → branch commit
  `faacd162f39c6bc9c54255a6f11618d9c79e9c08`; PR **#5** merged to
  `main`, merge commit `5b041971a1d6dbd22dcc6ba41fa57c9ece2f78f4`,
  verified via GitHub API (main = [P4 merge, P4, P3 merge, ...]).
  Sync record appended (5 entries). Local branches realigned; this
  note rides the Phase 5 commit. Next: Phase 5 (Indexing & Lookup).

### 2026-11-12 — Phase 5 COMPLETE (Indexing & Balance Lookup)
Full record: `docs/architecture/phase-5-indexing.md`.
- **New module `waas/modules/indexing/`**: `ChainCursor` +
  `ScannedBlock` (512-block hash window) + `ObservedDeposit`
  (uniqueness incl. block hash). Scanner (`services.scan_once`,
  one DB transaction per pass): reorg walk-back FIRST (orphaned
  blocks' deposits un-credited via ledger **reversals**, never
  edits), then block scan — native transfers receipt-verified,
  ERC-20/BEP-20 via Transfer logs through new EVM provider methods
  (`get_block`, `get_block_hash`, `get_logs`) — then confirmation
  pass. Lifecycle: DEPOSIT_OBSERVED at detection (custody_pending/
  customer_pending), one balanced 4-line DEPOSIT_CREDIT at the
  network's `confirmations_required`; scope = Phase 4 wallet
  scope. Blacklisted-sender deposits are **held** in pending for
  manual review, never auto-credited. Exactly-once = deposit
  uniqueness + deterministic ledger idempotency keys + status
  flips in-transaction (full-replay test proves it).
- **Worker**: `manage.py run_indexer` (separate from web;
  --network/--max-blocks/--until-caught-up; per-pass report incl.
  lag + reorg depth). Reconciliation report: expected custody
  (deposits − settled withdrawals) vs ledger custody per asset.
- **Lookup API replaces the Phase 1 501 gate** per the Phase 0
  normative design (`docs/api/transaction-lookup.md`): 422
  unknown network / malformed hash; tenant projection (full
  detail + tenant_record) for own transactions; **public
  projection** for other tenants' indexed transactions (raw
  on-chain data only, belongs_to_tenant=false — not an existence
  oracle); 404 unindexed; audit event per lookup; RPC fallback
  policy-gated OFF. Also `GET /wallets/{id}/deposits`
  (tenant-scoped). Dashboard: explorer view now works against the
  real endpoint (network list corrected to registry slugs; the
  Phase 1 `Transfer` type aligned to the implemented contract);
  client gains `listWalletDeposits` + `DepositRecord` type.
- **During the build I caught my own API bug**: `has_any_scope`
  is variadic, not list-taking — fixed in the indexing router
  before it shipped (machine-scope checks would have thrown).
- VERIFIED (actually run): backend `pytest` **96 passed, 1
  skipped** (known PostgreSQL wei case); ruff clean; frontend
  typecheck clean, vitest 9 passed, build OK. Indexing scenarios
  vs an in-memory forkable chain double: lifecycle balances per
  stage, token deposit, reverted tx ignored, full replay
  exactly-once, reorg before credit AND after credit (all
  balances return to zero, trial balance 0), blacklist hold,
  reconciliation balanced, lookup matrix + deposit-list tenant
  isolation. Phase 1 gate test updated deliberately (lookup 501 →
  real 422; sweep gate still 501). `run_indexer` command loads
  and executes its query path (dev DB here has no tables — the
  sandbox dev database was never migrated; noted, not a code
  defect).
- NOT verified: live-chain scanning (same sandbox egress block as
  Phase 4; scanner proven against the provider-surface double);
  Temporal reconciliation workflow (lifecycle is a synchronous
  service, same step boundaries); lag alerting wiring (Phase 12);
  on-chain balance cross-check endpoint (awaits RPC access);
  non-EVM scanners (land with Phases 6–8). No mainnet enablement;
  signing gate unchanged.
- Outcome: snapshot push (22 paths) → branch commit
  `50fa653a1b6b44194951dfb45423905f6c8e8be6`; PR **#6** merged to
  `main`, merge commit `2fe030ffd023b82641e04f41cee066ff8a284ed0`,
  verified via GitHub API (main = [P5 merge, P5, P4 merge, ...]).
  Sync record appended (6 entries). Local branches realigned; this
  note rides the Phase 6 commit. Next: Phase 6 (TRON).

### 2026-11-12 — Phase 6 COMPLETE (TRON)
Full record: `docs/blockchains/tron-implementation.md`.
- **New module `waas/modules/tron/`** (chains `tron`, `tron-nile`;
  19-confirmation registry policy): Base58Check addresses
  (checksum-verified, USDT pair `41a614f8…`↔`TR7NHqje…` tested
  both directions); minimal canonical protobuf encoder with field
  numbers **verified against the official tronprotocol/protocol
  sources fetched this session** (notably ref_block_num=3, not 2);
  TransferContract + TRC-20 TriggerSmartContract builders
  (txID = sha256(raw)); TronGrid-style provider (failover,
  idempotent broadcast by txID); withdrawal pipeline with Phase 4
  semantics (signer port signs the txID digest; signature r‖s‖v
  with v by trial recovery to the wallet's TRON address; unknown
  broadcast outcome → dropped + reservation HELD); TRON scanner
  on the Phase 5 framework (native from blocks, TRC-20 from
  tx-info logs; shared lifecycle via new public wrappers in
  indexing.services); lookup + reconciliation extended to TRON
  withdrawals; run_indexer dispatches by family.
- Two real bugs caught by tests mid-build: TRON hex form is
  canonical lowercase (EVM helper returns EIP-55 case — fixed at
  derivation), and the ledger reservation API's true signature
  (scope = reservation external_ref, returns BalanceReservation —
  my first TRON calls used invented kwargs; fixed to Phase 4's
  exact usage).
- VERIFIED (actually run): backend `pytest` **110 passed, 1
  skipped**; ruff clean. Golden-bytes test: expected raw TRX
  transaction hand-assembled from protocol field numbers equals
  the builder output byte-for-byte, txID = its sha256. Pipeline
  vs in-memory TronGrid double: TRX round-trip (broadcast
  signature recovers to the wallet TRON address), USDT trigger
  withdrawal, signer-unavailable abort, dropped-holds, blacklist
  refusal; indexing: TRX + TRC-20 deposits credited, replay-safe,
  reorg reversal with reconciliation balanced.
- NOT verified: live TronGrid/Nile interaction (egress), funded
  Nile round-trip (the backlog exit criterion is met only against
  the provider double), broadcast-JSON acceptance by a live node,
  recovery-id convention against java-tron, energy/bandwidth
  estimation & delegation, TRC-10. Signing gate unchanged.
- Outcome: snapshot push (21 paths) → branch commit
  `34ae02901dc1d946dfe54d563b11baf8d00417d8`; PR **#7** merged to
  `main`, merge commit `3f68a35d57e963d37a6803db3cf283e21289fecf`,
  verified via GitHub API (main = [P6 merge, P6, P5 merge, ...]).
  Sync record appended (7 entries). Local branches realigned; this
  note rides the Phase 7 commit. Next: Phase 7 (Solana).

### 2026-11-12 — Phase 7 COMPLETE (Solana)
Full record: `docs/blockchains/solana-implementation.md`.
- **New module `waas/modules/solana/`** (`solana`, `solana-devnet`;
  32-slot registry policy): base58 + Ed25519 address handling;
  **Ed25519 signer port** (whole-message; only fail-closed impl
  wired — FROST stays inside its Phase 3 ciphersuite and behind
  the review gate); legacy **message compiler** (shortvec,
  account-key dedup/order, header derivation) with SystemProgram
  transfer, SPL **TransferChecked**, ATA **create-idempotent**;
  **ATA/PDA derivation** with a from-the-equation Ed25519
  on-curve test (exact edge vectors: base point, (0,−1) ± sign,
  y ≥ p); JSON-RPC provider (failover, jsonParsed blocks);
  withdrawal pipeline with platform semantics (SPL = ATA-create +
  ATA→ATA TransferChecked, rent borne by the wallet fee payer);
  **balance-delta slot scanner** per the Phase 0 design §5.3
  (SOL pre/post balances; SPL pre/post token balances attributed
  by token-account OWNER; skipped slots handled; reorg walk-back
  anchored on real blocks). Lookup no longer lowercases base58
  hashes; reconciliation covers Solana withdrawals.
- **Cross-family bug the Solana reorg test caught**:
  `indexing._record_deposit` lowercased stored hashes/addresses —
  fine for hex, corrupting for base58; a Solana reorg orphaned
  the block but matched zero deposits to reverse (silent). Fixed
  at the root: scanners canonicalise, the recorder stores as
  given. Also fixed slot-0 falsy collapse in confirmation.
- VERIFIED (actually run): backend `pytest` **126 passed, 1
  skipped** (full suite incl. all prior phases after the shared
  recorder fix); ruff clean. Compilation parsed back byte-exact
  in tests; the pipeline's wire transaction signature **verifies
  with a standard Ed25519 implementation** against the wallet
  key; deposits/withdrawals/reorg vs an in-memory RPC double.
- NOT verified: live cluster/devnet round-trip (egress; exit
  criterion met against the double only), Token-2022, priority
  fees, ATA acceptance by a live cluster. Signing gate unchanged.

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
