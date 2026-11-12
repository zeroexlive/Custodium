# Custodium — Tenant Isolation (Phase 0)

> Status: Phase 0 design document. This system is **not production-ready**.
> Isolation is enforced in several layers because any single layer will
> eventually have a bug.

## 1. Model

- **Tenant**: a customer organisation. The hard security boundary.
- **Project**: a subdivision inside a tenant (e.g. environment or product).
  Projects never widen access beyond their tenant.
- **User / API key**: belongs to exactly one tenant; API keys are also
  bound to one project unless explicitly created as tenant-admin keys.
- Every tenant-owned row carries `tenant_id`; project-owned rows also
  carry `project_id`. There are no tenant-less financial records.

## 2. The cardinal rule

**Tenant and project are derived from authentication, never from the
request body, query string, or headers supplied by the caller.**

- The HMAC API key (or session) resolves to `(tenant_id, project_id,
  scopes)` at authentication time.
- Request schemas do not accept `tenant_id` at all. If a client sends
  one, it is ignored at best and rejected at worst — never honoured.
- A `project_id` in the body may be used only as a *selector within* the
  authenticated tenant, and must be checked against the key's project.
- Path IDs (wallet, address, transaction) are always resolved inside
  the authenticated tenant/project scope; out-of-scope means `404`.

## 3. API layer

- Authentication middleware runs before any handler and populates an
  immutable request context: tenant, project, actor, scopes, key ID.
- Handlers receive the context, not raw credentials, and cannot mutate it.
- Serialisers expose only fields owned by the caller's tenant.
- List endpoints filter by tenant/project before pagination, search,
  sorting, and aggregation — never after.
- Error behaviour: out-of-scope objects return `404`, not `403`, to
  avoid existence oracles across tenants.
- Admin/platform endpoints live on a separate surface with separate
  credentials; tenant credentials can never reach them.

## 4. Service layer

- Service functions take an explicit `TenantContext` as their first
  argument; there is no ambient/global tenant.
- Creating child objects copies `tenant_id`/`project_id` from the
  context or the parent object — never from client input.
- Cross-object operations (e.g. withdrawal from wallet W to a sweep
  resolver) verify every object shares the same tenant before acting.
- Money movement is exact integer arithmetic in the smallest unit;
  floats are forbidden, which also prevents cross-tenant rounding drift
  tricks from becoming a covert channel or a correctness bug.

## 5. Repository / data-access layer

- The default queryset/repository for tenant models is tenant-scoped:
  `Model.objects.for_tenant(ctx)` is the only sanctioned entry point.
- Raw/unscoped managers are named `unscoped` and linted: their use
  outside platform-admin and migration code fails CI.
- Foreign keys between tenant objects use composite integrity where
  feasible: a child cannot reference a parent of another tenant.
- Unique constraints are tenant-aware, e.g. idempotency keys are unique
  per `(tenant_id, project_id, key)`, not globally — and not per-tenant-less.

## 6. Database layer (defence-in-depth)

- PostgreSQL row level security (RLS) is enabled on tenant tables as a
  second line of defence, with policies keyed by a session variable
  (`app.tenant_id`) set per transaction from the authenticated context.
- RLS is defence-in-depth, **not** the primary control: application
  scoping must be correct even if RLS is disabled in a test.
- The application DB role has no `BYPASSRLS`; migrations and platform
  admin use separate, audited roles.
- Connection pooling must reset the tenant session variable on checkout;
  a pooled connection must never inherit the previous tenant's context.
- Backups, replicas, and analytics exports preserve tenant separation;
  no cross-tenant reporting view exists for tenant-facing roles.

## 7. Background workers and Temporal

- Every job/workflow input carries `tenant_id` and `project_id`, set by
  the enqueueing service from its authenticated context.
- Workers re-validate that all referenced objects belong to that tenant
  before acting; a mismatched workflow is terminated and alerted.
- Temporal namespaces or task queues are partitioned so a tenant's
  workflows cannot be signalled or queried by another tenant's calls.
- Retries preserve the original tenant context and idempotency key;
  a retry must never re-derive tenant from mutable object state.
- Dead-letter handling keeps tenant context attached for investigation.

## 8. Webhooks

- A webhook subscription belongs to one tenant/project; events are
  generated only from that tenant's objects.
- Payloads contain the owning tenant's IDs only; no global lookup data.
- Signing secrets are per-subscription; one tenant's secret never signs
  another tenant's events.
- Delivery workers scope by subscription tenant; a delivery ID cannot
  be replayed or inspected across tenants.

## 9. Sweep resolver and external calls

- Sweep destinations come **only** from the tenant-registered HTTPS
  resolver endpoint returning a plain-text address — never from a
  sweep request body and never from local files.
- The resolver URL itself is tenant configuration, changed only by
  tenant admins, and every resolution is audited per tenant.
- SSRF controls (see threat model T-09) apply per tenant equally.

## 10. Audit

- Every audit event records `tenant_id`, `project_id`, actor, action,
  object, and result. Platform-admin audit is a separate stream.
- Tenants can read only their own audit events.
- Audit writes use the object's tenant, not the caller's claim, so a
  bug that mis-attributes an action is itself detectable.

## 11. Address and transaction-hash lookup

These are classic cross-tenant leak vectors and get explicit rules:

- `GET address by value`: normalise per chain, then search **only**
  within the caller's tenant/project address registry.
- `GET transaction by hash`: search only the caller's tenant's
  transactions. A hash known on-chain but owned by another tenant
  returns `404`, identical to an unknown hash.
- No endpoint answers "does this address/hash exist anywhere?" — no
  global existence oracle, including via timing or error differences.
- Indexer storage is global internally, but every read path joins
  through tenant-owned address/wallet mappings before returning data.

## 12. Caching, search, and files

- Cache keys are prefixed with tenant/project; shared caches never use
  bare object IDs.
- Search indexes are partitioned or filtered by tenant at query time
  with the filter applied server-side from context.
- Exports and generated files are stored under tenant-prefixed paths
  and downloaded through tenant-scoped, expiring URLs.

## 13. Cross-tenant tests (mandatory)

Every release must pass, at minimum:

1. Tenant A cannot read, update, or delete any tenant B object by ID,
   for every resource type (wallet, address, deposit, withdrawal,
   sweep, transaction, webhook, blacklist entry, audit event).
2. Tenant A cannot list or search into tenant B's data, including with
   filters, pagination cursors, and sort parameters from B.
3. Address lookup and tx-hash lookup for B's values return `404` for A.
4. Idempotency key collision across tenants does not return B's result.
5. Webhook events for B are never delivered to A's subscriptions.
6. Worker/Temporal replay of A's job with tampered tenant fields fails
   validation and alerts.
7. RLS test: with application scoping deliberately bypassed in a test
   harness, the DB still blocks cross-tenant reads.
8. Aggregates (counts, balances) for A are unchanged by B's activity.

## 14. Residual risk and limitations

- Isolation depends on disciplined use of scoped repositories; code
  review and linting are part of the control, not bureaucracy.
- Platform operators with DB access are outside the tenant boundary by
  necessity; their access is logged, minimised, and reviewed.
- This document does not make the system production-ready; independent
  review and penetration testing remain required.
