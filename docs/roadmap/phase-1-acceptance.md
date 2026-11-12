# Phase 1 Acceptance Criteria — SaaS Foundation

- **Status date:** 2026-11-12
- **Phase status:** Planned (Phase 0 In Progress at the status date)
- **Governing documents:** ADR 0001, ADR 0002, ADR 0003, ADR 0005
- **Rule:** Phase 1 is NOT production-ready and must never be described
  as such. Passing this document means Phase 1 is `Tested` under the
  backlog taxonomy — not `Security Reviewed`, not `Production Approved`.

## Purpose and Scope

Phase 1 delivers the SaaS foundation of Custodium and nothing more:

- A user can register, verify email, and log in.
- A user can create an organisation and a project.
- A project exists in sandbox or production environment form, with
  the two environments strictly separated.
- A user can create an API key; the secret is shown once; HMAC
  authentication with that secret then works against the API.
- Tenants are isolated from each other, provably, by tests.
- The whole stack runs via Docker Compose and in CI.

Everything else — wallets, signing, chains, funds — is a later phase
(see `backlog.md`). This document defines the acceptance tests,
evidence requirements, security gates, and Definition of Done for
Phase 1, aligned with §32 of the product specification (Definition
of Done), restated for Phase 1 scope in the final section.

## Functional Acceptance Criteria

### 1. Registration

- [ ] A new user can register with email + password via the Vue console.
- [ ] Passwords are stored only as strong, salted hashes (Django's
      configured hasher); plaintext passwords never touch the database,
      logs, or email.
- [ ] Duplicate-email registration is rejected with a safe, generic
      response that does not leak account-existence beyond the
      registration flow's documented behaviour.
- [ ] Registration creates an inactive / unverified account that
      cannot use tenant features until email verification completes.

### 2. Email verification

- [ ] Registration (and email change) issues a single-use, expiring
      verification link/token to the supplied address.
- [ ] Opening the link verifies the email and activates the account.
- [ ] Expired, reused, or tampered tokens are rejected.
- [ ] A user can request a new verification email; resend is rate-limited.

### 3. Login and session management

- [ ] A verified user can log in with email + password and reach the
      console; an unverified or disabled user cannot.
- [ ] Failed logins return generic errors and are rate-limited /
      throttled; repeated failures are audit-logged.
- [ ] Sessions expire, logout invalidates the session server-side,
      and password change invalidates other sessions.
- [ ] The console session mechanism is distinct from API HMAC auth:
      a console cookie alone does not authenticate API-key endpoints
      that require HMAC, and vice versa.

### 4. Organisations

- [ ] A logged-in user can create an organisation and becomes its
      owner/admin under the Phase 1 role model.
- [ ] Organisation membership is explicit: non-members cannot view
      or enumerate the organisation, its projects, or its API keys.
- [ ] Role enforcement: read-only members cannot create projects,
      create/revoke API keys, or change organisation settings.
- [ ] Organisation create / membership / role changes are audit-logged.

### 5. Projects and environments

- [ ] An authorised member can create a project inside an organisation.
- [ ] Every project is created as sandbox or production environment
      (project environment is explicit data, shown in console and API).
- [ ] Sandbox and production are strictly separated: API keys, data,
      and API responses never cross environments; a sandbox key
      cannot authenticate against production resources and vice versa.
- [ ] Project listing/detail APIs return only projects in
      organisations the caller belongs to, in the requested environment.

### 6. API keys and HMAC authentication (ADR 0005)

- [ ] An authorised member can create an API key for a project.
      The response shows: key identifier, fingerprint/prefix, and
      the secret — the secret shown EXACTLY ONCE, at creation only.
- [ ] After creation, no console page, API response, log, or export
      can reveal the secret again. "Show secret again" does not exist.
- [ ] The stored secret is envelope-encrypted at rest (ADR 0005):
      a database dump alone does not reveal usable secrets.
- [ ] HMAC auth works: a request signed per ADR 0005 (canonical
      method / path+query / body SHA-256 / timestamp / nonce;
      HMAC-SHA256) with a valid key succeeds.
- [ ] Negative cases all fail closed with generic errors:
      - wrong secret / tampered body / tampered path or query
      - timestamp outside the 300-second window (past or future)
      - replayed nonce, and replayed full request within the window
      - revoked key, unknown key, key from the other environment
      - missing or malformed signing headers
- [ ] Key revocation takes effect immediately on the verification path.
- [ ] Reference test vectors for the canonical string are published
      in the API docs and pass in the automated test suite.

## Platform Acceptance Criteria

### 7. Docker Compose stack

- [ ] A single documented command brings up the full Phase 1 stack:
      Django, PostgreSQL, Redis, Temporal (server + UI in dev
      profile), and the Vue frontend.
- [ ] The stack starts clean from an empty volume set: migrations
      run, health checks pass, console loads, API answers, and an
      end-to-end smoke test (register → verify in dev mail capture →
      login → org → project → key → signed API call) passes.
- [ ] A Temporal smoke workflow executes successfully through a
      worker, proving workflow connectivity for later phases.
- [ ] Redis loss in the dev stack causes no data loss of record:
      users, orgs, projects, and keys survive in PostgreSQL.

### 8. CI pipeline

- [ ] CI runs on every pull request / push to the working branch:
      - lint (Python and TypeScript/Vue)
      - type checks (Python typing; `vue-tsc` / TypeScript)
      - unit and integration tests (backend and frontend)
- [ ] CI uses the committed `uv.lock` / frontend lockfile — no
      floating dependency installs (ADR 0002).
- [ ] A failing lint, type, or test check blocks merge. CI status is
      visible on the change; "it passed locally" is not evidence.

### 9. Documentation delivered with Phase 1

- [ ] README quickstart: prerequisites, Compose startup, test commands.
- [ ] API reference for Phase 1 endpoints, including the HMAC
      canonicalisation spec and worked signing examples.
- [ ] Environment/configuration reference: every variable, its
      purpose, and which values are secrets.
- [ ] This acceptance document, updated with the evidence links
      produced when the criteria are actually run.

## Explicit Non-Goals of Phase 1

The following are OUT of scope. Their presence in Phase 1 — in code,
in marketing copy, or in demo data — is an acceptance failure:

- **No wallets.** No wallet creation, no address generation for real
  chains, no deposit/withdrawal endpoints.
- **No signing.** No MPC ceremonies, no cggmp21 / FROST execution,
  no private-key or key-share handling of any kind.
- **No mainnet funds.** No mainnet RPC configuration with real
  credentials, no real assets, no "small test with real money".
- **No MPC production (or pre-production) claims.** ADR 0004
  candidates remain `PENDING independent review`.
- **No sweeping.** The resolver rule (ADR 0006) is documented, not
  implemented, in Phase 1.
- **No ledger movements.** No fund-moving ledger entries; ledger
  implementation is Phase 2 under ADR 0007.
- **No production readiness claim** of any kind, for any audience.

## Test Evidence Requirements

Acceptance requires evidence, not assertions:

- Automated test suite output (CI run link / ID) covering:
  - auth flows: register, verify, login, logout, password reset
  - organisation / project CRUD and role enforcement
  - API key lifecycle: create (shown once), list (no secret), revoke
  - HMAC: positive round-trip + every negative case in §6
  - tenant isolation (see security gates below)
- Test data uses synthetic users/tenants only; no real customer
  data in any test environment.
- Tests are deterministic and re-runnable from a clean checkout:
  `docker compose` up, migrate, test — documented commands only.
- Any criterion that can only be checked manually (for example
  "secret appears once in the UI and never again") gets a written
  manual test record: steps, tester, date, result — attached to the
  Phase 1 completion note.

## Security Gates (all must pass; none may be waived silently)

1. **Tenant isolation tests:** automated tests attempt cross-tenant
   access for every Phase 1 resource type (organisation, project,
   API key metadata) via both console and API, with both session
   and HMAC credentials. Every attempt must fail (403/404 per the
   API's documented non-enumeration behaviour). A single success
   blocks Phase 1 acceptance.
2. **Secret hygiene check:** grep-able evidence that secrets
   (API secrets, passwords, tokens) are absent from logs, fixtures,
   committed files, and CI output; envelope encryption verified by
   inspecting stored ciphertext in a test database.
3. **HMAC gate:** the full negative-case suite in §6 passes,
   including replay and cross-environment key use.
4. **Auth gate:** rate limiting on login / verification resend /
   password reset is enabled and demonstrated by test.
5. **Dependency gate:** lockfiles committed; CI vulnerability scan
   shows no unaddressed critical vulnerabilities in Phase 1 deps.
6. **No-non-goals gate:** a reviewer confirms §"Explicit Non-Goals"
   holds in the shipped Phase 1 tree (no wallet/signing/mainnet code).

A gate failure is recorded openly in the completion note with its
remediation plan. Waiving a gate requires a written decision by the
project owner, recorded alongside this document — silence is not a waiver.

## Definition of Done (§32, applied to Phase 1)

A Phase 1 item is Done only when ALL of the following are true:

1. Code is merged to the phase branch with CI green (lint, types, tests).
2. Behaviour matches this acceptance document, criterion by criterion.
3. Automated tests covering the behaviour exist and pass in CI;
   manual-only checks have a written test record.
4. Security gates relevant to the item pass, with evidence attached.
5. Documentation (README / API reference / config reference, as
   applicable) is updated in the same change set.
6. No new secrets, credentials, or real data entered the repository,
   fixtures, logs, or CI output.
7. No non-goal (§ above) was introduced, even "temporarily" or
   behind a feature flag.
8. The backlog status for Phase 1 items is updated truthfully using
   the shared taxonomy (`Planned / In Progress / Implemented /
   Tested / Security Reviewed / Production Approved`) — and no item
   is marked beyond the evidence it actually has.
9. Known limitations and follow-ups are written down in the backlog
   or issue tracker, not left as tribal knowledge.

## Phase 1 Completion Statement (template)

When the criteria are run, complete this block; do not pre-fill it:

- Date assessed:
- Assessor:
- CI run (link / ID):
- Criteria passed / failed (list failures explicitly):
- Security gates passed / failed:
- Evidence locations (test reports, manual test records):
- Resulting status under the taxonomy: (expected maximum: `Tested`)
- Explicit confirmation: no wallets, no signing, no mainnet funds,
  no production claim were introduced in Phase 1.
