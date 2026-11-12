# SaaS Product Completion — Phase 11 Implementation Record

Status: **Implemented** (2026-11-12). The commercial surface
around the custody core: signed webhooks, plans/quotas/
metering, fiat invoicing, team management, audit export,
support tooling, and the public integration documents.

## 1. Webhooks (`waas/modules/webhooks/`)

Contract: `docs/api/webhooks.md`. Endpoints are
project-scoped, SSRF-validated at registration **and again at
every delivery**, with a per-endpoint signing secret
(`whsec_…`, shown once, Fernet-encrypted at rest) that is
deliberately **separate** from API keys/HMAC.

- Events: `deposit.credited`, `withdrawal.completed`,
  `withdrawal.failed`, `sweep.completed`, `sweep.failed` —
  emitted from the real lifecycle points: the indexing credit
  path, the operations terminal transitions (refresh *and*
  dispatch failure paths), and the sweeps terminal transitions.
  Emission happens inside the state-change transaction (an
  event exists iff the change committed) and is a no-op when no
  endpoint subscribes.
- Delivery: `WaaS-Signature: t=<ts>,v1=<hmac>` over
  `f"{ts}.{raw_body}"`, `X-WaaS-Event-Id` for receiver-side
  idempotency, at-least-once with a bounded ladder
  (6 attempts: ~1m/5m/30m/2h/12h) then dead-letter.
  `deliver_webhooks` is the worker entrypoint; deliveries are
  inspectable and **replayable** (attempt counter reset, same
  event id) from the API and the console.

## 2. Plans, quotas, metering, invoicing (`waas/modules/plans/`)

- `Plan` catalog (seeded by `seed_plans`: Sandbox free,
  Growth, Scale) with quotas for wallets, API keys per project,
  included monthly withdrawals, and a per-withdrawal overage
  price in cents. Organisations without a subscription row run
  on Sandbox.
- **Metering is derived**: usage snapshots count the
  operational tables (wallets, live API keys, this-period
  withdrawals excluding rejected/failed) — there is no separate
  metering store that can drift from reality.
- **Enforcement**: wallet creation and API-key creation check
  quotas and fail with an explicit `QuotaExceeded` (403) —
  quotas are product guardrails, not security boundaries.
- **Invoicing is fiat-only and collection-free by design**:
  `generate_invoice` produces one idempotent invoice per
  organisation per period (plan price + overage); status moves
  draft → issued → paid by explicit operator action
  ("mark paid" records an off-platform payment; no card data
  ever touches this system). The custody ledger remains the
  crypto system of record.

## 3. Console completion

- **Team management**: member list/add-by-email/role-change/
  remove under `/organizations/{id}/members`, owner/administrator
  gated, last-owner protections, all mutations audited.
- **Audit export**: `GET /audit-logs/export` streams the
  caller's organisations' audit trail as CSV (capped at 10k
  rows per export).
- **Support tooling**: `GET /support/lookup` — staff-only,
  read-only, returns identifiers/statuses only, and **every
  lookup is itself audit-logged** with the query.
- Dashboard gained Webhooks (endpoints, one-time secret
  display, deliveries + replay), Billing (plan, usage, invoices,
  mark-paid), and Team views.

## 4. Public integration documents

- `docs/api/webhooks.md` — the delivery contract above.
- `docs/api/hmac-test-vectors.md` — fixed-input vectors
  produced by the production signers (API HMAC + webhook
  scheme); `tests/integration/test_hmac_vectors.py` asserts
  them, so docs and implementation cannot silently drift.
- `docs/api/sdk-examples.md` — stdlib-only Python and Node
  examples for signed calls and webhook verification.

## 5. Verification performed

Backend suite: see `AGENTS.md`. Highlights: the signature on a
captured delivery verifies independently against the documented
scheme; the retry ladder reaches DEAD at exactly 6 attempts;
replay resets a dead delivery; an inward-resolving endpoint
fails closed at delivery time; a real Phase 9 withdrawal
completion emits exactly one event + delivery. Quota, invoice
idempotency + overage maths, team flows (including last-owner
protection), and the CSV export are covered end to end. A
field-name bug in the deposit event payload was caught by the
chain suites (every family's credit path exercises emission)
and fixed.

## 6. NOT verified / deferred

- **Live webhook delivery** to a real tenant endpoint is not
  exercised from this sandbox (in-process HTTP doubles only).
- Payment collection (e.g. a card processor) is intentionally
  not integrated; "mark paid" is the recording surface.
- Self-serve exit criterion ("signup to testnet operations
  using only published docs") is supported by the new docs and
  the shipped flows, but a fresh-tenant walkthrough against a
  deployed instance remains an operational validation, not a
  code claim.
- Temporal remains unwired (`deliver_webhooks` is the
  entrypoint), as with earlier phases.
