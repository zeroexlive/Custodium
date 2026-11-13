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
   *Amendment (2026-11-13, William's explicit direction; ADR 0006 as
   amended):* a project may instead run in STATIC destination mode, using a
   tenant-registered static hot-wallet address per network (dashboard API,
   owner/administrator, audited). Every other clause of this rule stands —
   never in a request, never from files, snapshot before approval, fail
   closed, no fallback between modes.
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
| 3 | MPC Infrastructure | Implemented (evaluation) — merged to `main` 2026-11-12 (PR #4, merge `d7656b6`); cggmp21 REJECTED (see history); production signing still disabled, independent review NOT commissioned. Post-roadmap 2026-11-13: production signer service IMPLEMENTED (see history + `docs/architecture/production-signer.md`); activation still gated off pending the review. Wallet provisioning wired to the signer behind the same gate + full rehearsal passed (2026-11-13, see history) |
| 4 | Ethereum & BSC | Implemented — merged to `main` 2026-11-12 (PR #5, merge `5b04197`); live on-chain round-trip NOT verified (sandbox egress + no faucet funds; see history) |
| 5 | Blockchain Indexing & Lookup | Implemented — merged to `main` 2026-11-12 (PR #6, merge `2fe030f`); live-chain scanning NOT verified (sandbox egress; see history) |
| 6 | TRON | Implemented — merged to `main` 2026-11-12 (PR #7, merge `3f68a35`); live-node verification NOT done (sandbox egress; see history) |
| 7 | Solana | Implemented — merged to `main` 2026-11-12 (PR #8, merge `1dae8c9`); live-cluster verification NOT done (sandbox egress; see history) |
| 8 | TON | Implemented — merged to `main` 2026-11-12 (PR #9, merge `7800470`); differentially verified vs @ton/ton + tonsdk; live-network verification NOT done (egress; see history) |
| 9 | Financial Operations (deposits, withdrawals, ledger, webhooks) | Implemented — merged to `main` 2026-11-12 (PR #10, merge `4eacf6a`); live-testnet soak NOT done (egress; see history) |
| 10 | Sweeping & Treasury | Implemented — merged to `main` 2026-11-12 (PR #11, merge `0a7b7fb`); live tenant-endpoint interop NOT verified (egress; see history) |
| 11 | SaaS Product Completion | Implemented — merged to `main` 2026-11-12 (PR #12, merge `824ddd7`); live webhook delivery NOT verified (egress; see history) |
| 12 | Hardening & Production Preparation | Preparation scope implemented — merged to `main` 2026-11-12 (PR #13, merge `878fa4f`). **Custodium is NOT Production Approved** (independent review/pentest/legal/soaks open; see history) |

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
- Outcome: snapshot push (22 paths) → branch commit
  `b05300dbe3d8236590301b4ac5aca2daaabe9cf6`; PR **#8** merged to
  `main`, merge commit `1dae8c9b9b15c1db75324dcf5e83b51377c273df`,
  verified via GitHub API (main = [P7 merge, P7, P6 merge, ...]).
  Sync record appended (8 entries). Local branches realigned; this
  note rides the Phase 8 commit. Next: Phase 8 (TON).

### 2026-11-12 — Phase 8 COMPLETE (TON)
Full record: `docs/blockchains/ton-implementation.md`.
- **New module `waas/modules/ton/`** (`ton`, `ton-testnet`):
  cells/BoC from scratch (builder/slice, repr hashing, CRC32C);
  raw↔friendly addresses (CRC16, testnet-flag discipline,
  masterchain destinations rejected); **wallet V4R2** (code cell
  verbatim from the official @ton/ton SDK; StateInit derivation;
  signed-transfer builder; seqno always from chain; per-wallet
  send serialisation under the row lock; signer key checked
  against the derived contract address); toncenter provider
  (v2 + v3 transactionsByMessage confirmation; Jetton
  `get_wallet_address` resolved once and cached); withdrawal
  pipeline with platform semantics (Jetton sends attach 0.05 TON,
  recorded); per-account **`lt`-cursor deposit scanner** (native
  at the wallet; Jetton from `internal_transfer` payloads at the
  Jetton wallet; notifications/excesses/bounces filtered by
  design). Lookup + reconciliation cover TON withdrawals.
- **Differential verification (this phase's highlight)**: the
  @ton/ton spec's written address expectation proved STALE (the
  upstream test is it.skip'd) — so the shipped **@ton/ton package
  and tonsdk were both executed locally** (npm/PyPI egress
  works): for the deterministic `v4-treasure` key, both derive
  `EQDgICpEIOY6…`, exactly matching this module; and a reference
  signed transfer's body cell hash `8e8c73a2…` was reproduced
  byte-identically (signature included). A manual representation
  hash independently confirmed the data cell.
- VERIFIED (actually run): backend `pytest` **138 passed, 1
  skipped**; ruff clean. Pipeline vs API double incl. broadcast
  BoC signature verifying over the reconstructed signing-cell
  hash; deposit filter matrix + replay safety.
- NOT verified: live toncenter/testnet round-trip (chain APIs
  unreachable from the sandbox; exit criterion met against the
  double + differential proofs), Wallet V5, outbound-Jetton
  bounce-completion tracking (Phase 12). Signing gate unchanged.
  All five chains are now implemented; next is Phase 9.
- Outcome: first snapshot push was interrupted by a service
  restart — verified via the API that the branch was unchanged
  (still at the Phase 7 commit) before retrying; the retry
  (21 paths) landed as branch commit
  `6fbe5e2ec8c2c6d40048f447dcb4f62d8c28c55c`; PR **#9** merged to
  `main`, merge commit `78004700c9837d99ccb2530b836da6746f6bdaef`,
  verified via GitHub API (main = [P8 merge, P8, P7 merge, ...]).
  Sync record appended (9 entries). Local branches realigned;
  this note rides the Phase 9 commit. Next: Phase 9 (Financial
  Operations).

### 2026-11-12 — Phase 9 COMPLETE (Financial Operations)
Full record: `docs/architecture/phase-9-operations.md`.
- **New module `waas/modules/operations/`**: `WithdrawalRequest`
  implementing the design status machine (pending_policy →
  approved → signing → broadcast → confirming → completed |
  failed | rejected); **policy engine** (`WithdrawalPolicy`:
  asset row > project default > platform default; hard
  max-single + daily-velocity limits reject with reason;
  approvals_required with auto-approve threshold); **approvals**
  with roles (owner/administrator/withdrawal_approver),
  maker-checker, one decision per approver, one rejection final;
  **service-fee accounting** (flat fee journaled at dispatch,
  reversed via the ledger if the payout fails — fee income never
  survives a failed withdrawal); **actual network fee** reported
  on completion (new captures: EVM fee_wei from the receipt,
  Solana meta.fee; TRON/TON already carried theirs);
  **reconciliation halts** (`run_reconciliation` raises/clears
  fail-closed halts from the Phase 5 report; creation + dispatch
  refuse while halted); **refund playbook** (ADJUSTMENT journal
  with mandatory reason, cumulative cap); **CSV journal export**;
  worker commands `process_withdrawals` / `run_reconciliation`;
  dispatch adapter over the five chain pipelines with
  fail-closed production signer factories and an exception
  safety net so one request cannot crash the batch.
- API: POST/GET /withdrawals (+ Idempotency-Key contract),
  approve/reject/refund, policy GET/PUT, journal export;
  dashboard Withdrawals view + policy editor.
- VERIFIED (actually run): backend `pytest` **148 passed, 1
  skipped**; ruff clean; frontend typecheck + vitest (9) +
  build green. Includes an end-to-end API test (HMAC creation →
  dashboard approval) and a full EVM dispatch cycle against the
  provider double with exact fee/reservation balances.
- NOT verified: the live-testnet reconciliation soak (backlog
  exit criterion; chain APIs unreachable from this sandbox),
  Temporal wiring (commands are the entrypoints), PostgreSQL,
  CI. Signing gate unchanged.
- Outcome: the first snapshot push's approval expired
  unapproved (30-minute window elapsed during the work); a
  second attempt was approved and landed as branch commit
  `f12ceac1eefb433b3e4686a60b71df9d49665f7e` (29 paths); PR
  **#10** merged to `main`, merge commit
  `4eacf6a6fc2476d45d384ff9a1ecc180abcb7d75`, verified via GitHub
  API (main = [P9 merge, P9, P8 merge, ...]). Sync record
  appended (10 entries). Local branches realigned; this note
  rides the Phase 10 commit. Next: Phase 10 (Sweeping &
  Treasury).

### 2026-11-12 — Phase 10 COMPLETE (Sweeping & Treasury)
Full record: `docs/architecture/phase-10-sweeps.md`.
- **New module `waas/modules/sweeps/`** implementing the
  normative resolver design (docs/api/sweep-resolver.md, ADR
  0006) end to end, replacing the Phase 1 501 endpoint gates:
  `SweepDestinationEndpoint` (PostgreSQL-only, one per project,
  owner/administrator registration, Fernet-encrypted optional
  signing secret, versioned) + append-only
  `SweepEndpointHistory` (URL hashes, never values); **resolver
  client** with the full SSRF matrix (HTTPS only, all DNS
  answers must be public IPs incl. metadata ranges, no
  redirects, ≤512-byte single-token plain-text body, per-network
  address validation, bounded transport-only retries, HMAC
  request signing when a secret is registered); **sweep
  lifecycle** per the design state machine with
  `ResolvedDestinationSnapshot` (immutable at the model layer),
  blacklist/self-sweep/halt policy checks, threshold +
  leave-behind amount discovery, Phase 9 quorum reuse, and
  **no re-resolution after approval** — execution passes the
  snapshot address through the shared
  `operations.dispatch.execute_transfer` (extracted this phase);
  `process_sweeps` worker command; resolution test tool that
  stores nothing.
- API: endpoint GET/PUT/DELETE + history + test; `POST /sweeps`
  inspects the raw JSON — destination fields → 422
  `destination_not_allowed`, unknown fields → 422 (closed
  schema). Dashboard: endpoint view (project scope, test,
  history) + real Sweeps view.
- VERIFIED (actually run): backend `pytest` **154 passed, 1
  skipped**; ruff clean; frontend typecheck + vitest (9) +
  build green. Penetration-style tests cover the SSRF/format
  matrix, snapshot immutability, destination substitution after
  approval (endpoint switches address → approved sweep still
  uses the snapshot), and exact ledger outcomes. One Phase 1
  gate test updated (sweep gate now answers 422, not 501).
- NOT verified: live tenant-endpoint interoperability (no
  public-internet egress), socket-level DNS pinning (documented
  as deployment layer), Temporal wiring, PostgreSQL, CI.
  Signing gate unchanged.
- Outcome: snapshot push (24 paths) landed as branch commit
  `8ae350145fe56ae34a0af21f07b0f94eba0035e3`; PR **#11** merged
  to `main`, merge commit `0a7b7fbcd6873c88c44e188e4ec61d3635fd3833`,
  verified via GitHub API (main = [P10 merge, P10, P9 merge,
  ...]). Sync record appended (11 entries). Local branches
  realigned; this note rides the Phase 11 commit. Next: Phase
  11 (SaaS Product Completion).

### 2026-11-12 — Phase 11 COMPLETE (SaaS Product Completion)
Full record: `docs/architecture/phase-11-saas.md`.
- **Webhooks** (`waas/modules/webhooks/`): project endpoints
  (SSRF-validated at registration AND at every delivery,
  `whsec_` secrets shown once, Fernet at rest, separate from API
  HMAC); events deposit.credited / withdrawal.completed /
  withdrawal.failed / sweep.completed / sweep.failed emitted
  from the real lifecycle points (indexing credit path,
  operations terminal transitions incl. dispatch-failure paths,
  sweeps terminal transitions) inside the state-change
  transaction; delivery per docs/api/webhooks.md
  (`WaaS-Signature: t=,v1=` HMAC), at-least-once, 6-attempt
  ladder → dead, `deliver_webhooks` worker, list + replay API,
  dashboard Webhooks view.
- **Plans/billing** (`waas/modules/plans/`): Plan catalog
  (`seed_plans`: Sandbox/Growth/Scale), derived metering from
  operational tables (no driftable store), quota enforcement at
  wallet + API-key creation, fiat-only idempotent invoicing
  (plan price + withdrawal overage; `generate_invoices`
  command; mark-paid records off-platform payment — no card
  data in system). Dashboard Billing view.
- **Console completion**: team management endpoints +
  last-owner protections (`organization/member*` audit events),
  audit CSV export, staff-only read-only `support.lookup`
  (self-auditing). Dashboard Team view.
- **Public docs**: docs/api/webhooks.md, sdk-examples.md
  (Python stdlib + Node), hmac-test-vectors.md — vectors
  produced by the production signers and ASSERTED by
  tests/integration/test_hmac_vectors.py (docs cannot drift).
- VERIFIED (actually run): backend `pytest` **163 passed, 1
  skipped**; ruff clean; frontend typecheck + vitest (9) +
  build green. A deposit-payload field bug (`to_address` vs
  `address`) was caught by the chain suites and fixed — every
  family's credit path exercises emission.
- NOT verified: live webhook delivery (egress), payment
  collection (intentionally off-platform), deployed
  fresh-tenant walkthrough, PostgreSQL, CI, Temporal. Signing
  gate unchanged.
- Outcome: first snapshot-push attempt's approval EXPIRED
  unapproved (nothing pushed); retry after William's "Push it"
  landed as branch commit
  `ea719c2cc9e8fc4fae75a9a3976a890d424f9d5b`; PR **#12** merged
  to `main`, merge commit `824ddd73cd57710377b23a20b07a8118360e2635`,
  verified via GitHub API (main = [P11 merge, P11, P10 merge,
  ...]). Sync record appended (12 entries). Local branches
  realigned; this note rides the Phase 12 commit. Next: Phase
  12 (Hardening & Production Preparation) — the final phase.

### 2026-11-12 — Phase 12 COMPLETE (preparation scope) — roadmap finished
Full record + readiness assessment:
`docs/architecture/phase-12-hardening.md`. **Custodium is NOT
Production Approved** — the phase's own exit criteria require
an independent review with no open critical/high findings and
a separate written approval decision; neither exists.
- Built: **DB-level append-only triggers** (migration
  ledger.0003, `waas/common/db_triggers.py`) forbidding
  UPDATE/DELETE on ledger_journal_entry, ledger_journal_line,
  audit_audit_event, sweeps_resolveddestinationsnapshot —
  PostgreSQL function+triggers / SQLite RAISE(ABORT); tests
  prove raw SQL cannot rewrite history while appends work and
  the whole suite passes with triggers live. **Platform kill
  switch** (`PlatformHalt` + staff-only audited operator API;
  refuses withdrawal/sweep creation, dispatch, sweep
  processing). **/healthz + /readyz** probes. **Runbooks**:
  incident-response (7 scenarios, all steps use shipped
  mechanisms), key-ceremony (procedures + drill cadence,
  gated on the review), mainnet-rollout-plan (preconditions,
  staged caps, rollback).
- VERIFIED (actually run): backend `pytest` **167 passed, 1
  skipped**; ruff clean; **cargo test --workspace 16 passed**
  (re-run for the final record); frontend typecheck + vitest
  (9) + build green; migrations apply cleanly from scratch
  (SQLite). A UUID storage-format bug in the trigger test
  (dashed vs hex params matching zero rows) was found and
  fixed during verification.
- NOT verified / still open (external, by design): independent
  cryptographic + security reviews (package ready, William to
  commission), pentest, legal review, live-chain testnet soaks
  (egress), PostgreSQL trigger smoke test on a live server,
  Temporal (never wired), DR drills on real infrastructure,
  CI results (not visible via connector). Production signing
  remains DISABLED; wallets remain `provisioning`. This closes
  the 13-phase roadmap: all phases 0–12 are implemented and
  merged to `main`; what remains is evidence and approvals,
  not features.
- Outcome: snapshot push (16 paths) landed as branch commit
  `958b2fb3eea8d04030c0e03ffdea1d3be443f4df`; PR **#13** merged
  to `main`, merge commit `878fa4f33bf2f5f4fe09113e2b3178a97910661b`,
  verified via GitHub API (main = [P12 merge, P12, P11 merge,
  ...]). Sync record appended (13 entries — one per phase).
  Local branches realigned. **The 13-phase roadmap is
  complete.** Remaining work is external evidence and
  approvals (see the readiness assessment), plus the standing
  item: this closing note is an uncommitted local edit of this
  file — the repository on GitHub records Phase 12 through the
  phase-12-hardening document; any future commit should carry
  this note.

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

### 2026-11-12 — Post-roadmap: deployment tutorials + interactive installer
- Added `docs/operations/deployment-1-server-dev.md` (single-server
  dev topology: Compose and native paths, first-run walkthrough,
  worker commands, limitations) and
  `docs/operations/deployment-6-server.md` (minimum production
  topology: app / workers+coordinator / data / 3 participants on
  separate hosts, network zones, per-server steps, go-live
  checklist; MPC tier provisioning-only until the review gate).
- Added `scripts/install.sh`: interactive step-by-step installer
  for the one-server dev topology (Compose or native), fresh-secret
  .env generation, migrations + seeds, optional superuser, health
  probes; supports `--dry-run` and `--yes`. README links both
  tutorials and the installer.
- VERIFIED: `bash -n` syntax check; full `--yes --dry-run` walk
  completed all 8 steps cleanly in native mode (no Docker in this
  VM; detection fell back correctly) and modified nothing.
  NOT verified: a real end-to-end install run (would mutate the
  dev environment), Compose execution (no Docker), interactive
  TTY prompts (dry-run used --yes).
- Follow-up fix (same day): the snapshot connector records files
  as mode 644, so the GitHub copy of `scripts/install.sh` is not
  executable; README + the 1-server tutorial now invoke it as
  `bash scripts/install.sh`. Local repo config `core.fileMode`
  set to false to silence the resulting mode-only diff.

### 2026-11-13 — Gas station (post-roadmap module, William: "Implement gas station")
- What: `waas/modules/gasstation/` — per-(project, network)
  `GasStation` config (same-project funding wallet, threshold,
  top-up amount, daily cap) + `GasTopUp` records keyed by the
  operation's idempotency key. A preflight inside the shared
  `operations.dispatch.execute_transfer` reads the wallet's
  on-chain native balance via the family provider (EVM/Solana/TON
  `get_balance`; TRON account read) before any non-native transfer:
  below threshold it broadcasts a top-up from the funding wallet
  through the ordinary pipeline (`gas:<operation_key>`, journaled
  in the funding wallet's own scope — no special money path) and
  raises `GasTopUpPending`; withdrawal dispatch returns the request
  to `approved` with the service fee reversed, sweep execution
  returns to `resolved` with the snapshot untouched. Unreadable
  balances never block a transfer; native transfers, disabled
  stations and self-funding pass through. Dashboard-only API
  (owner/administrator; cross-project funding wallet rejected 422)
  + a Gas Station dashboard view. Record:
  `docs/architecture/gas-station.md`; README gained a highlight
  bullet.
- Verified: `tests/integration/test_gasstation.py` 6 passed (full
  EVM deferral cycle incl. funding-reservation settlement and
  zero native trial balance; sweep deferral resuming from the
  same snapshot; cap/native/disabled/API cases). Full backend
  suite **173 passed / 1 skipped**, ruff clean; frontend
  typecheck + vitest 9 + build green.
- NOT verified: live-chain top-ups (sandbox egress; provider-double
  proof like every family). Production signing remains disabled;
  top-ups inherit the fail-closed signer factories.

### 2026-11-13 — Production-readiness pass (William: "Make this project production ready and industry standard")
- Framing recorded honestly: everything closable from this
  environment was closed; the external gates (independent reviews,
  production signer build + review, pentest, legal, funded testnet
  soaks, live drills, the approval decision) remain the owner's —
  Custodium is still NOT Production Approved. Master gate list:
  `docs/operations/production-readiness-checklist.md`;
  sendable review brief: `docs/mpc/review/commissioning-brief.md`;
  addendum appended to `docs/architecture/phase-12-hardening.md`.
- PostgreSQL verification (was a standing NOT-verified item since
  Phase 2): full suite on a real PostgreSQL (pgserver in-VM):
  **179 passed, 0 skipped** — the wei-scale test runs and the
  Phase 12 append-only triggers execute as PG triggers/functions.
  The run caught a test bug: trigger introspection queried
  `sqlite_master` unconditionally; now vendor-aware. (SQLite
  suite unchanged: 178 passed / 1 skipped.)
- Production settings: `check --deploy` clean after adding HSTS
  preload, a 32-char minimum SECRET_KEY, and the proxy SSL header
  for the nginx topology.
- Audits: pip-audit — no known vulnerabilities. Secret scan of
  the tree and full git history — clean. npm audit could NOT run
  (the sandbox registry proxy refuses the audit endpoint) and
  cargo audit's tool build was interrupted by a full /tmp tmpfs;
  both recorded as environment limits in the checklist, not as
  results. SBOMs generated into `docs/security/sbom/` (backend +
  dashboard CycloneDX, MPC cargo metadata).
- Code hardening: socket-level DNS pinning for the sweep resolver
  and webhook delivery (`waas/common/http_pinning.py` — connect
  to the validated IP, hostname preserved for Host/SNI/cert;
  closes the Phase 10/11 rebinding note) with tests; Solana
  priority fees (median of recent prioritization fees, capped at
  500k micro-lamports/CU, ComputeBudget instruction; zero when
  the cluster reports none) with tests.
- Environment note: /tmp is a 512 MB tmpfs in this VM — large
  build trees (cargo target/install dirs, DB data) must live
  under $HOME or they fail with misleading "no space" errors.

### 2026-11-13 — Register-500 investigation (William's live Compose run) + deployment hardening

- William ran the one-server Compose stack on his own server:
  the dashboard loaded, but registration returned **500** — the
  first live deployment report for the project.
- Reproduced every layer available in this VM: backend under
  development settings via a real `runserver` process → register
  **201** (SQLite); through the Vite dev proxy exactly as the
  browser calls it → **201**; against a real PostgreSQL with a
  NON-superuser `custodium` role and migrations run as that role
  (Compose-matching) → **201**. Login → create organization also
  verified over HTTP (201). Conclusion: no registration code path
  reproduces a 500 in any configuration reproducible here; the
  failure on William's server is environmental and the
  discriminating evidence (`docker compose ps`, backend logs)
  lives on his server. Most probable cause family: backend
  container down or crash-looping (e.g. POSTGRES_PASSWORD changed
  after the postgres volume was initialized, so `migrate` cannot
  connect) while the dashboard container serves pages and its
  proxy surfaces the dead backend as a 500.
- Hardening shipped so this failure mode is visible instead of
  opaque: backend **healthcheck** on `/healthz` in
  `docker-compose.yml`, dashboard now depends on backend
  `service_healthy`; new **Troubleshooting** section in
  `docs/operations/deployment-1-server-dev.md` (register-500
  decision tree, the password/volume trap, `readyz` semantics;
  stale verify-install test count corrected to 178 passed /
  1 skipped).
- Verified: compose YAML parses; the healthcheck probe command
  exercised against a live dev server (200); register/login/org
  flows over HTTP as above. NOT verified: Docker itself (no
  Docker in this VM) — the Compose change is configuration-level,
  validated by inspection + YAML parse only. William's
  server-side root cause remains OPEN pending his
  `docker compose logs backend` output.

### 2026-11-13 — Production signer service built (post-roadmap, William's direction)

- Context: William asked to mark Custodium Production Approved;
  Muse declined (the approval gates are unmet and the status is
  evidence-based, not declarable) and William directed building
  the production signer instead — the one remaining buildable
  blocker. The implementation now EXISTS for the independent
  review. Activation remains gated and Custodium remains NOT
  Production Approved.
- Built: `services/mpc/crates/signer_service` (binary
  `custodium-signer`) — one process per participant node;
  XChaCha20-Poly1305 encrypted share store (per-node key file;
  wrong key or tampered file = hard error); peer-to-peer protocol
  transport over cluster-token HTTP (`round_based` Delivery for
  CGGMP; explicit envelopes for FROST; DKG round-2 packages go
  point-to-point; the coordinator starts sessions and collects
  public results, never relays shares); coordinator client API
  `/v1` (create key = aux + DKG, public key, sign). Phase 3 pins
  unchanged (cggmp24 =0.7.0-alpha.2, frost-ed25519 =3.0.0);
  Cargo.lock updated (axum, reqwest, chacha20poly1305, …).
- Django: `waas/modules/mpcsigner` client implementing both
  signer ports with fail-closed error mapping (trust_env=False);
  dispatch factories use it ONLY when `MPC_SIGNER_ENABLED=true`
  AND `MPC_SIGNER_URL` are set (defaults off; all four
  combinations pinned by tests); 9 new client/gate tests.
- Verified: `cargo test --workspace` **20 passed / 0 failed**.
  Service tests (three nodes, separate stores and store keys,
  real HTTP): FROST DKG + sign with quorum [0,2] verified by
  ed25519-zebra, plus a full node-set restart over the encrypted
  stores signing again; ECDSA DKG (incl. aux generation) +
  signing of the Phase 4 Sepolia sighash with k256 ecrecover ==
  group address (249 s test). Store unit tests (round-trip,
  wrong key, tamper). Live binaries: three `custodium-signer`
  processes driven by curl — FROST DKG + quorum [1,2] signature
  verified with Python `cryptography`; a persisted-store ECDSA
  signature likewise verified with `cryptography`. Backend:
  pytest **187 passed / 1 skipped** (JUnit report), ruff clean.
- Bugs the tests caught (fixed and re-verified): (1) signing
  sessions must translate between keygen party indices and
  session indices (a [0,2] quorum is session parties 0 and 1) —
  the first ECDSA run aborted with SenderIndexOutOfRange; the
  delivery layer now takes the session's participant list;
  (2) the two service tests collided on hardcoded ports when
  cargo ran them in parallel (AddrInUse) — disjoint port sets.
- Docs: `docs/architecture/production-signer.md` (design +
  limitations: bearer tokens not mTLS, no cggmp24 key refresh,
  no identifiable abort, in-memory session state); review
  evidence checklist item 7, commissioning brief, and the
  readiness checklist updated (signer = built, review open);
  Phase 3 status line updated above.
- NOT verified: multi-host deployment (all nodes shared this VM
  and loopback), TLS/mTLS transport, mid-ceremony node failure
  beyond protocol aborts — and the independent review itself,
  which now has an implementation to review. Remaining gates
  unchanged: commission the review, pentest, legal, funded
  testnet soaks, live drills, written approval decision.

### 2026-11-13 — Wallet provisioning wired to the signer + rehearsal (post-roadmap, William's direction)

- What changed: wallets can now actually be provisioned through
  the production signer. Key ids became PER CURVE
  (`wallet-<uuid>-ecdsa` / `wallet-<uuid>-ed25519` — the signer
  service stores one key per key id and a wallet holds two
  independent threshold keys; `key_id_for(wallet, curve)` in
  `waas/modules/mpcsigner/client.py`, both signing ports and the
  client tests updated). New setting `MPC_SIGNER_THRESHOLD`
  (default 2). New `waas/modules/wallets/provisioning.py`:
  `provision_wallet` refuses (wallet untouched) when the signer
  gate is closed, the registry is empty, the wallet is
  frozen/archived, or the signer fails; otherwise get-or-creates
  both keys (adopting existing keys after a partial failure —
  no re-keying), derives one address per family from the group
  public keys via the families' canonical helpers, records an
  address for EVERY seeded network through
  `record_derived_address`, stores the opaque key refs, flips
  the wallet to `active`, and audits `wallet.provisioned`.
  Ceremonies run outside DB transactions; only the
  address/wallet/audit writes are atomic. An active wallet with
  keys but missing addresses is backfilled, never re-keyed.
  Entry points: `POST /wallets/{id}/provision` (dashboard auth,
  WRITE_ROLES; 409 when the gate is closed) and the
  `provision_wallet` management command. Defaults unchanged:
  gate closed, wallets stay `provisioning`, Custodium NOT
  Production Approved.
- Tests: `tests/integration/test_wallet_provisioning.py` (9) with
  an in-memory fake coordinator (404→create→409 semantics) and
  FIXED group keys — generator-point ECDSA key whose EVM address
  is the externally known private-key-1 address
  `0x7E5F4552091A69125d5DfCb7b8C2659029395Bdf` (independent
  anchor), TRON/Solana/TON expectations pinned from the family
  helpers (which carry their own golden/differential tests).
  Covers gate-closed refusal, happy path (10 networks), idempotent
  re-run, resume-after-crash key adoption, frozen refusal,
  signer-outage atomicity, endpoint 409 + happy path. First run
  caught that test DBs have an EMPTY network registry (seeding is
  the `seed_networks_assets` command, not a migration) — the
  empty-registry guard above came from that.
- REHEARSAL (the point of the work): `scripts/rehearse_provisioning.py`
  booted 3 real signer binaries + the real backend (gate open for
  the run only, throwaway SQLite/stores under
  `~/custodium-rehearsal/run-20261113T064428Z/`) and drove the
  public API: register → org → project → wallet → provision in
  204.7 s → `active` with 10 addresses. The driver then verified
  EVM/TRON/Solana addresses by recomputing them from the
  signer-reported group keys WITHOUT the backend's helpers
  (TON shape-only; Phase 8 differential covers its derivation),
  and proved backend-initiated signing through the real dispatch
  factories: ECDSA signature recovered to the wallet's EVM
  address `0x5fca24b7822778Dca3ede2ad4009CE59D5822576`, FROST
  signature verified with `cryptography`. Teardown confirmed
  (no stray processes). Record: `docs/operations/provisioning-rehearsal.md`.
- Full verification: backend pytest **196 passed / 1 skipped**
  (JUnit; +9 over the signer build's 187), ruff clean, rehearsal
  driver compiles. No Rust changes in this package.
- NOT verified: multi-host deployment, TLS/mTLS, live chains
  (no deposits/withdrawals moved — signing was proven against
  digests/messages only), the dashboard UI against a provisioned
  wallet. Remaining gates unchanged: commission the independent
  review (now covering provisioning too), pentest, legal, funded
  testnet soaks, live drills, written approval decision.

### 2026-11-13 — Feature-completeness audit + gap closures (post-roadmap, William: "Make sure we have every feature that a usable mpc wallet has")

- Audit: inventoried every router/model against the usable-MPC-WaaS
  checklist. The platform already had more than the gap list first
  assumed — API-key `ip_allowlist`/`expires_at` fields AND their
  enforcement already existed in machine auth (only creation-time
  settability was missing); fee accounting, refund playbook,
  replayable webhooks, custom token registration, quotas/billing
  all present. Full mapping: `docs/product/feature-matrix.md`
  (Available / Gated / Added / Out-of-scope with reasons /
  External), including the deliberate exclusions (UTXO chains,
  staking/NFTs/ramps, AML/KYT by spec, cggmp24 key refresh,
  signer mTLS) and one honest follow-up: dashboard Vue views for
  the newest endpoints are NOT wired yet (APIs complete).
- Closed in this package (all behind existing auth/roles, all
  audit-logged):
  1. **TOTP 2FA** for dashboard users (pyotp added): setup →
     enable (valid code required) → login pauses at a signed
     5-minute challenge (`requires_totp`, no session issued) →
     verify completes it. 8 one-time recovery codes (digests
     only), consumed on use; disable needs a code/recovery.
     Secret Fernet-encrypted on the user row (migration
     identity 0002). `AuthOut.token/access_token` are null
     exactly during the challenge.
  2. **API-key options**: `ApiKeyIn` now accepts `ip_allowlist`
     + `expires_at`, echoed in `api_key_out`, recorded in the
     creation audit event (enforcement pre-existed).
  3. **Destination address book** (new `addressbook` module):
     per-project per-network entries (normalized matching,
     owner/administrator managed), plus
     `Project.withdrawal_allowlist_required` (projects migration
     0002) enforced in withdrawal creation beside the blacklist
     check when on; book is informational when off.
  4. **Webhook secret rotation**:
     `POST /webhooks/endpoints/{id}/rotate-secret`, same write
     authorization as endpoint management, old secret dies
     immediately, audit `webhook.secret_rotated`.
  5. **Auto-sweep rules** (sweeps migration 0002): per
     (wallet, network, asset) balance threshold; `run_auto_sweeps`
     creates sweeps through the ordinary path (resolver, policy,
     approvals untouched downstream), at most one open auto
     sweep per rule, idempotency from the rule trigger counter.
     Dashboard CRUD at `/auto-sweep-rules` (path renamed from
     `/sweeps/auto-rules`: the 2-segment path collided with
     `GET /sweeps/{sweep_id}` and 405'd — address-book policy
     routes had the same class of collision with
     `DELETE /address-book/{entry_id}` and were reordered ahead
     of it).
- Tests: `tests/integration/test_feature_gaps.py` (12): full
  TOTP challenge flow + recovery single-use + disable; IP
  allowlist allowed/blocked via real HMAC whoami; expired vs
  valid keys; address-book CRUD/uniqueness/roles + allowlist
  enforcement service-level (blocked → added → allowed);
  rotation replaces the stored secret (decrypt-verified) with
  role denial; auto-sweep threshold/open-gating/disabled + API
  + command smoke. Full suite **208 passed / 1 skipped**
  (JUnit), ruff check clean. (`ruff format` is not a project
  gate — pre-existing files fail it too; not applied.)
- NOT verified: dashboard UI for the new endpoints (not built —
  see matrix follow-up), TOTP against a real authenticator app
  (pyotp is the RFC 6238 reference implementation path and the
  tests compute codes with it), live anything. Status gates
  unchanged: NOT Production Approved.

### 2026-11-13 — Installation tutorials rewritten (dev + production) with deploy/ examples (William's request)

- New canonical tutorials: `docs/operations/installation-dev.md`
  (paths: installer / Compose / native local / local signer
  cluster with dev keys + rehearsal script; first-run walkthrough
  incl. provisioning and 2FA; workers on demand; the register-500
  troubleshooting carried over) and
  `docs/operations/installation-production.md` (six servers;
  S3 data, S1 app with full env inventory + RPC settings overlay
  example — endpoints are Django settings dicts per slug, S2
  workers via systemd, S4–S6 signer nodes with per-node store
  key generation, backups for BOTH the database and signer
  store+key pairs, a GATED activation step that lists the review/
  pentest/legal/ceremony/approval preconditions before the gate
  env is set, go-live checklist, upgrade/rollback with
  one-signer-node-at-a-time rule). The two 2026-11-12 tutorials
  now carry "Superseded" pointers (the 6-server one falsely said
  signer binaries do not ship yet); README links updated.
- New `deploy/` examples the tutorials reference:
  systemd units (custodium-api, custodium-indexer@ per network,
  custodium-job@ + six concrete timers with the cadences incl.
  run_auto_sweeps 1min and generate_invoices daily,
  custodium-signer with ProtectSystem=strict + IP allow-listing
  scaffold), `deploy/run-job.sh` (job-name → management command),
  nginx site (dashboard dist + /api proxy + TLS), env examples
  (backend incl. the commented-out signer gate; per-node signer
  env).
- Verification: every management command named in the docs was
  checked to exist (10/10); `bash -n deploy/run-job.sh`;
  `systemd-analyze verify` parsed all units (only the expected
  deploy-user uv path note on this VM); a real
  `cargo build -p custodium-signer-service` run SUCCEEDED —
  which caught and fixed a wrong package name
  (`-p signer_service` would have failed) in both new tutorials,
  the rehearsal doc, and the rehearsal driver's hint text.
- NOT verified: a live install on real servers or Docker
  (no Docker/systemd host available in the dev VM) — the
  tutorials are written from the verified code paths, command
  inventory, settings, and the executed rehearsal, and are
  labelled accordingly where a step is operator judgment.
  Production status unchanged: NOT Production Approved; the
  production tutorial installs with the signer gate closed.

### 2026-11-13 — Workflow-gap closures: deposit minimum, withdrawal minimum, gas top-up address, static sweep destinations (William's specified workflow check)

- William specified the target tenant workflow end to end
  (register → project → gas-station address → deposit →
  confirmations → gas top-up to the deposit address → sweep to
  per-chain hot wallets, manually or via API → admin-approved
  withdrawals → client-set min/max). Verification against the
  code found most of it already implemented; the gaps below
  were built in this package. Per his follow-up instruction,
  deposit MAXIMUM was deliberately NOT built (accept any
  amount; a cap could strand user funds) — deposit minimum only.
- Deposit minimum: `DepositPolicy` (indexing, per project+asset,
  migration 0002) enforced in the shared confirmation pass all
  four scanner families funnel into. Below-minimum deposits are
  HELD via the existing held/hold_reason mechanism (reason
  "below minimum deposit (N)") and accumulate per
  (wallet, asset): when a confirmation pass's matured group plus
  the held pool reaches the minimum, pool + group credit
  together, each with its own DEPOSIT_CREDIT journal (reorg
  reversal stays per-deposit). Dashboard API
  GET/PUT /deposit-policies (manage: owner/administrator).
- Withdrawal minimum: `WithdrawalPolicy.min_single_amount`
  (operations migration 0003, NULL = none) enforced beside the
  max/daily hard limits in create_withdrawal_request (REJECTED
  with the reason kept); exposed in PolicyIn + both policy
  serializers.
- Gas station: `GET /gas-stations` responses now include
  `top_up_address` — the funding wallet's address on the
  station's network (null until provisioned); documented in
  docs/architecture/gas-station.md.
- Static sweep destinations (ADR 0006 AMENDED at William's
  direction — amendment text in docs/adr/0006 and
  docs/api/sweep-resolver.md, rule 4 above updated):
  `SweepPolicy.destination_mode` (resolver default | static),
  `StaticSweepDestination` per (project, network) registered via
  PUT /sweep-destinations (owner/administrator; family-validated
  + normalized like the address book), GET list + DELETE;
  GET/PUT /sweep-policy added (the policy previously had no
  API). process_sweep branches at resolution time only: static
  mode re-validates the stored address, snapshots it into the
  same immutable ResolvedDestinationSnapshot (new `source`
  field), and fails closed (RESOLUTION_FAILED) when absent,
  disabled, or invalid — no resolver fallback. All downstream
  stages (blacklist/own-address checks, amount discovery,
  approvals, signing from snapshot) are shared and unchanged.
  Migrations sweeps 0003 + 0004: 0004 re-applies the Phase 12
  append-only triggers because adding the snapshot column
  remakes the table on SQLite and drops them (caught by
  test_hardening; the installer is idempotent and 0004 depends
  on ledger 0003 to guarantee order).
- Tests: tests/integration/test_workflow_gaps.py (9): hold →
  accumulate → credit (60 + 50 vs min 100, balance 110), pool
  release alongside a large deposit, no-policy passthrough,
  deposit-policy API + role denial; withdrawal min rejected
  with reason + policy API roundtrip; gas station top_up_address
  in the list response; static resolution → AWAITING_APPROVAL
  with source="static" snapshot, static-without-destination
  RESOLUTION_FAILED, destination/policy APIs + invalid-address
  422 + viewer 403. Full suite **217 passed / 1 skipped**
  (JUnit), ruff check clean.
- NOT verified: live-chain behaviour of the new paths (egress,
  as ever); dashboard Vue views for the new endpoints remain
  the recorded follow-up. Status unchanged: NOT Production
  Approved.

### 2026-11-13 — Dashboard UI pass: views for the PR #22/#24 endpoints (William approved the proposed pass)

- New views (all following the existing project-picker +
  TanStack Query patterns and DESIGN.md language):
  Security (2FA status from /me, setup → secret + provisioning
  URI shown for authenticator entry, enable → recovery codes
  shown once, disable with a current/recovery code); the login
  flow now handles the TOTP challenge — auth store `login`
  returns 'totp' without persisting a token, `completeTotp`
  verifies against /auth/2fa/verify and only then persists;
  Address Book (entries CRUD + the withdrawal allowlist-required
  toggle); Sweep Settings (sweep policy incl. destination_mode,
  static hot-wallet destinations CRUD, auto-sweep rules CRUD);
  Deposit Policies (per-asset minimum editor; copy states there
  is deliberately no maximum). Nav + routes added for all four.
- Extended existing views: API Keys create form gains the IP
  allowlist (one per line) and expiry fields, and the key list
  shows allowlist/expiry; Webhooks gains Rotate secret per
  endpoint, reusing the shown-once secret panel; Withdrawals
  policy form gains the minimum-single field (+ summary line);
  Gas Station table shows the station top_up_address.
- Client/types: new api functions for 2FA, address book +
  policy, deposit policies, sweep policy/destinations/rules,
  webhook rotation; types for all of the above (AutoSweepRule
  display resolves the asset symbol client-side because the API
  returns asset_id only).
- Verified: `npm run build` (vue-tsc strict + vite) green;
  vitest 15 passed (9 pre-existing + 6 new in
  tests/new-features-client.spec.ts: request shapes for the new
  endpoints + the two-step TOTP store flow asserting no token
  is persisted before verification). One contract mismatch
  caught during the pass: auto-sweep rule rows carry asset_id,
  not a symbol — fixed client-side.
- NOT verified: the views against a live backend in a browser
  (no browser-driven run in this environment); backend endpoint
  behaviour itself is covered by the PR #22/#24 test suites.
  Status unchanged: NOT Production Approved.

### 2026-11-14 — Frontend icons + data-driven Overview (William's request)

- Icons: hand-drawn inline SVG set in
  apps/dashboard/src/components/ui/Icon.vue (24x24 stroke icons,
  currentColor, no icon dependency): grid, building, folder,
  key, shield, wallet, pin, search, coins, refresh, signal,
  sliders, book, fuel, clipboard, ban, arrow-up-circle, webhook,
  users, card, file, clock, sun, moon, logout, chart. Wired into
  every sidebar nav item, the logo mark (shield), the theme
  toggle (sun/moon) and the logout button; also removed a
  pre-existing duplicate Webhooks nav entry.
- Charts: dependency-free components in src/components/charts/
  (BarChart, DonutChart, HBars) with pure math in chartMath.ts
  (fractionsOfMax, shares, donutSegments, bucketByDay).
- Overview rewritten from the Phase 1 placeholder into a real
  operations page — ALL data live from the API, per rule 9:
  KPI cards (organizations, projects, API keys, wallets in the
  selected project, awaiting-approval = withdrawals in
  pending_policy + sweeps in awaiting_approval); project
  selector (auto-selects the first project); available balances
  by asset (horizontal bars; display values are the raw base-unit
  strings, floats used only for proportions); withdrawals by
  status (donut, case-normalized statuses); platform activity
  (audit events per day, last 14 UTC days, from GET /audit-logs —
  the card states it counts the most recent 100 events); plan
  usage meters (first organization); recent-activity list. The
  stale "Phase 1" copy is gone; the header pill states the true
  status (Pre-production · not production approved). Every card
  has loading, error, and honest empty states.
- Audit Logs view wired at last: the Phase 11 placeholder is
  replaced with the real GET /audit-logs table (event type,
  project, timestamp) + client function listAuditLogs.
- Verified: npm run build (vue-tsc strict + vite) green;
  vitest 21 passed (6 new in tests/charts.spec.ts: chart math
  incl. day bucketing and zero-guards, Icon render smoke test).
  DESIGN.md gained an Icons & charts section.
- NOT verified: browser-driven rendering against a live backend
  (not available in this environment). Status unchanged: NOT
  Production Approved.

### 2026-11-14 — Workflow gaps II: automatic gas-station setup + create-address API (William's re-specified workflow)

- William re-specified the workflow (auto gas-sponsor addresses
  at project creation; address creation via API). Verification
  found the deposit/withdrawal mechanics already in place; these
  two gaps were built:
- (1) Auto gas setup: creating a project (POST /projects, one
  transaction) now also creates a dedicated funding wallet
  (external_customer_id "gas-station", label "Gas Station") and
  one GasStation per seeded network with per-family defaults —
  gasstation.services.setup_project_gas_station (idempotent,
  audited gas_station.auto_configured): EVM min 5e14/topup 2e15,
  TRON 1e7/5e7 SUN, Solana 1e7/5e7 lamports, TON 5e7/2e8
  nanotons, daily cap 100. The wallet is a normal project wallet
  (appears in wallet lists, counts in plan metering; provisioning
  it follows the ordinary signer-gated flow, after which station
  top_up_address values resolve).
- (2) Create-address API: POST /wallets/{id}/addresses {network}
  replaces the Phase 2-era 501 stub. Returns the existing address
  (200) or derives + records it (201) from the wallet's group
  public key — provisioning now PERSISTS both group public keys
  on the wallet (wallets migration 0002; public material only,
  shares never leave the signer) and
  provisioning.derive_address_for_network does the per-family
  derivation with no signer call. Unprovisioned wallet -> 409,
  unknown network -> 422, machine callers need
  addresses:write/wallets:write/write scope, dashboard callers a
  write role. Audited wallet.address_created. Dashboard:
  Addresses view's stale 501 card replaced with a working
  create/get control + client function.
- Phase 2 tests updated where the specified behaviour changed
  them: wallet list totals and global wallet counts now account
  for the auto gas-station wallet (assertions scoped to exclude
  it where the customer wallet was the subject), and the address
  gate assertion is 409 (unprovisioned) instead of 501.
- Tests: tests/integration/test_workflow_gaps2.py (7): station
  auto-creation incl. family defaults + API visibility with null
  top_up_address pre-provisioning + idempotent re-setup; address
  API 409/derive-201/return-200 (generator-point EVM + pinned
  Solana vectors)/422/403-scope; provisioning persists both
  public keys (monkeypatched key meta). Full suite 224 passed /
  1 skipped, ruff clean; frontend build + vitest 21 passed.
- NOT verified: live provisioning of an auto-created funding
  wallet against real signer nodes in this pass (the Phase 21
  rehearsal proved the same flow for a regular wallet; the
  funding wallet differs only in label/external id). Status
  unchanged: NOT Production Approved.
