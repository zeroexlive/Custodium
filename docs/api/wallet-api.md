# Wallet API — Tenant-Scoped Wallets, Addresses, Money Movement

Status: Phase 0 — normative design. Base path `/api/v1`.
Auth: machine HMAC (see `authentication.md`) unless a route is
explicitly marked dashboard-session. All routes are tenant-aware.

## 1. Tenancy model (applies to every endpoint)

- Tenant, project, and environment are derived from the API key,
  never trusted from the request body or query string.
- Every database query is filtered by `tenant_id` (and project /
  environment where applicable). An object belonging to another
  tenant is indistinguishable from a non-existent object: `404`,
  never `403` with confirming detail, and never leaked fields.
- `external_customer_id` is the tenant's own identifier for an
  end customer (opaque string, unique per tenant+project+env).
  Custodium maps it to internal customers; tenants never need
  Custodium's internal ids for their customers, though internal
  ids are also returned.
- All money amounts are integers in the asset's smallest unit,
  transmitted as strings to avoid float/precision loss. Floats
  in requests are rejected. Each asset declares its decimals;
  see the per-chain documents for USDT decimals per network.

## 2. Conventions

### 2.1 Pagination

List endpoints use cursor pagination:

```text
GET /api/v1/wallets?limit=50&cursor=<opaque>
→ { "data": [ … ], "next_cursor": "<opaque|null>",
    "has_more": true }
```

- `limit` default 25, max 100; out-of-range values are clamped
  or rejected per the OpenAPI contract, consistently.
- Cursors are opaque, signed/encoded server state; clients MUST
  NOT parse or construct them. Ordering is stable
  (`created_at, id`) so pages do not duplicate or skip rows.
- Offset pagination is not offered on unbounded collections.

### 2.2 Errors

Uniform envelope, stable machine-readable `code`, `request_id`
on every response (also returned as a response header):

```json
{ "error": { "code": "wallet_not_found",
             "message": "No such wallet.",
             "request_id": "req_01J…",
             "details": {} } }
```

Codes include `validation_error` (422), `not_found` (404),
`conflict` (409), `insufficient_funds` (422),
`idempotency_conflict` (409), `rate_limited` (429),
`policy_denied` (403), `blacklist_denied` (403).

### 2.3 Idempotency

- State-creating money endpoints (withdrawals, sweeps, wallet
  and address creation) REQUIRE an `Idempotency-Key` header.
- Scope of a key: `(tenant_id, project_id, environment, key)`.
- Same key + same request body → the original response is
  replayed (same resource id / status), no duplicate effect.
- Same key + different body → `409 idempotency_conflict`.
- Records are retained at least 24 h; money operations retain
  them for the life of the operation record.
- Idempotency is enforced before execution, inside the same
  transaction that creates the operation record.

### 2.4 Request ids and auditing

Every request gets a `request_id`; money operations also get an
operation id referenced by webhooks, audit log, and support.

## 3. Wallets

### `POST /api/v1/wallets` — create wallet

```json
{ "external_customer_id": "cust_8841",
  "label": "Customer 8841 main",
  "wallet_type": "mpc_threshold" }
```

- Creates a wallet for the customer in the key's tenant/project.
  MPC key generation is asynchronous where DKG is involved;
  response may be `201` with `status: "provisioning"` and the
  wallet becomes `active` when DKG completes (webhook emitted).
- No private key material, share, or seed is ever returned. The
  response contains ids, status, and policy metadata only.
- Idempotency-Key required. Scope: `wallets:create`.

### `GET /api/v1/wallets` — list wallets

Filters: `external_customer_id`, `status`. Cursor pagination.
Scope: `wallets:read`.

### `GET /api/v1/wallets/{wallet_id}` — retrieve one wallet

`404` if the wallet is another tenant's (§1). Scope: `wallets:read`.

## 4. Addresses

### `POST /api/v1/wallets/{wallet_id}/addresses`

```json
{ "network": "ethereum", "asset_id": "usdt-ethereum" }
```

- Derives/allocates a deposit address for that network from the
  wallet's MPC material via the chain adapter. Derivation limits
  of threshold schemes are documented per protocol/chain; where
  public derivation is unavailable, an address-generation
  ceremony replaces naive HD derivation (see `../mpc/`).
- One wallet may hold addresses on many networks; an address
  belongs to exactly one wallet, network, and tenant.
- Response: address string, network, asset, `status`, memo/tag
  fields where the chain requires them (e.g. TON bounce/comment
  conventions are returned explicitly, never assumed).
- Idempotency-Key required. Scope: `addresses:create`.

### `GET /api/v1/wallets/{wallet_id}/addresses`

Filter by `network`. Scope: `addresses:read` (or `wallets:read`
per final OpenAPI contract — decided once, applied uniformly).

### `POST /api/v1/addresses/resolve` — resolve an identifier

Resolves a tenant-facing identifier to an address record:

```json
{ "external_customer_id": "cust_8841", "network": "tron" }
→ { "wallet_id": "wal_…", "address": "T…", "network": "tron" }
```

- Resolution only ever searches inside the caller's tenant.
- Unknown customer/network → `404`, with no hint about whether
  the customer exists for another tenant.

## 5. Balances

### `GET /api/v1/wallets/{wallet_id}/balances`

Returns per-asset ledger balances: `available`, `pending`,
`locked` (e.g. by in-flight withdrawals), each as integer-string
plus `asset_id` and `decimals`. Balances are double-entry ledger
figures, reconciled against on-chain state by the indexer; the
API never computes balances by scanning chain RPC live per call.

### `GET /api/v1/balances?external_customer_id=…&network=…`

Tenant-wide balance listing with cursor pagination.

## 6. Transactions

### `GET /api/v1/wallets/{wallet_id}/transactions`

Unified ledger/on-chain transaction list: deposits, withdrawals,
sweeps; filters `network`, `asset_id`, `direction`, `status`,
`from`/`to` time. Cursor pagination, newest first.

### `GET /api/v1/transactions/{transaction_id}`

One transaction owned by the caller's tenant, else `404`.

### `GET /api/v1/transactions/lookup?network=&hash=`

Cross-reference an on-chain hash. Specified in full in
`transaction-lookup.md`, including its privacy rules.

## 7. Deposits

### `GET /api/v1/deposits` / `GET /api/v1/deposits/{id}`

Deposits detected by the indexer on tenant addresses:
`{ address, network, asset_id, amount, tx_hash, confirmations,
required_confirmations, status: detected|confirming|credited|
rejected }`. Credit happens only at the chain's finality policy
(see per-chain docs); `detected` funds are not spendable.
Deposits to a blacklisted source follow the manual blacklist
policy (see `../blacklist/` if present) and are not auto-credited
where policy says hold.

## 8. Withdrawals

### `POST /api/v1/withdrawals`

```json
{ "wallet_id": "wal_…", "network": "ethereum",
  "asset_id": "usdt-ethereum", "amount": "250000000",
  "destination_address": "0x…",
  "external_reference": "order-991" }
```

- This is a tenant-instructed payout to an *external* address
  supplied in the request — the opposite of a sweep (§9), where
  a destination in the request is forbidden by design.
- Pipeline: validate address for network → blacklist/policy
  check → balance/lock → business approval policy (quorum rules
  are business policy, distinct from MPC threshold) → signer
  intent binding → broadcast → confirmation tracking.
- Idempotency-Key required. Scope: `withdrawals:create`.
- Response `202`-style operation object with `status` machine:
  `pending_policy → approved → signing → broadcast → confirming
  → completed | failed | rejected`.
- Fee handling: estimated fee and fee bounds are part of the
  signed intent; actual network fee is reported on completion.
  Amounts remain integer strings; fee asset identified explicitly.

### `GET /api/v1/withdrawals` / `GET /api/v1/withdrawals/{id}`

List/retrieve, tenant-scoped, cursor pagination.

## 9. Sweeps (summary — normative doc is `sweep-resolver.md`)

### `POST /api/v1/sweeps`

Consolidates funds from deposit addresses to the tenant's
pre-registered destination. The request names wallet/address
scope, network, and asset — and **MUST NOT** contain
`destination_address` or `destination_endpoint_url`; requests
containing either are rejected (`422 destination_not_allowed`).
The destination is obtained only by resolving the tenant's
registered HTTPS endpoint at sweep time, snapshotted, and
verified before signing. See `sweep-resolver.md` in full.

## 10. Webhooks (interface note)

State changes (wallet active, deposit credited, withdrawal
completed, sweep completed/failed) emit signed webhook events
to tenant-registered HTTPS URLs. Webhook signing is a separate
secret/scheme from API HMAC keys and is specified with the
webhook contract; events carry ids enabling idempotent handling
and a `GET` re-fetch of the underlying resource.

## 11. Rate limits and versioning

- Per-key rate limits; `429` with `Retry-After`. Money-creation
  endpoints have stricter buckets than reads.
- Version is in the path (`/api/v1`). Breaking changes ship as
  a new version; `v1` semantics in this document do not change
  silently.
