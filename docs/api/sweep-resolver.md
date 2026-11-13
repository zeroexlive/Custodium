# Sweep Destination Resolver — Registered Endpoint Only

Status: Phase 0 — normative design. This document is the full
specification for sweep destinations. Where any other document,
code comment, ticket, or operational habit conflicts with this
one on sweep destinations, this one wins.

## 1. The rule, stated once and completely

A sweep moves funds from tenant deposit addresses to ONE
destination address. That destination is obtained **only** by
calling, at sweep time, an HTTPS endpoint that the tenant has
previously registered with Custodium. Therefore:

- A sweep request **NEVER** contains a destination. Requests
  containing `destination_address` or
  `destination_endpoint_url` (or any alias) are **rejected**
  (§3), not ignored.
- A destination **NEVER** comes from local configuration: no
  JSON, YAML, CSV, `.env`, database seed, spreadsheet, or file
  of any kind is a source of sweep destinations.
- The registered endpoint URL itself is stored **only in
  PostgreSQL**, scoped to (tenant, project, environment) (§2).
- If resolution fails at any point, the sweep **fails closed**:
  no fallback address, no stale cached destination, no retry
  against a "last known good" value (§7).

Rationale: a destination that can be supplied per-request or
read from a file can be swapped by anyone who can make a request
or edit a file. A registered, authenticated, freshly resolved
endpoint with an immutable snapshot makes destination changes
an audited administrative act, not a runtime input.

## 2. Registering the endpoint

### `PUT /api/v1/sweep-destination-endpoint`

Registers or replaces the endpoint for the caller's
(tenant, project, environment) scope.

```json
{ "url": "https://tenant.example/internal/waas/sweep-destination",
  "signing_secret_ref": "vault-or-kms-reference",
  "enabled": true }
```

Storage and rules:

- Stored **in PostgreSQL only**, one active row per
  (tenant_id, project_id, environment). The URL is data in that
  row; it is never written to a config file or environment
  variable by the platform.
- Registration requires **elevated authentication**: a dashboard
  session with step-up re-authentication and the
  `sweep-endpoint:admin` privilege, or a machine key holding
  `sweep-endpoint:admin`. Ordinary wallet/sweep scopes cannot
  register or modify the endpoint.
- The URL is validated at registration with the same SSRF rules
  as at call time (§6): HTTPS only, public routable host, no
  credentials in URL, no fragment. Registration-time validation
  does not replace call-time validation.
- A signing secret for response authentication (§5) is stored
  envelope-encrypted (KMS/Vault, per `authentication.md` §6) —
  never in plaintext, never in the same field as the URL.

### Companion operations

- `GET /api/v1/sweep-destination-endpoint` — view current
  registration (URL, enabled, version, updated_by, updated_at).
  The signing secret is never returned.
- `DELETE` / disable: setting `enabled=false` stops all new
  sweeps for the scope immediately. Disabling is not deletion;
  history is retained.
- **History:** every register/update/disable appends an
  immutable history row (actor, timestamp, previous URL hash,
  new URL hash, reason if supplied). History is queryable via
  `GET /api/v1/sweep-destination-endpoint/history`.
- **Test:** `POST /api/v1/sweep-destination-endpoint/test`
  performs a resolution (§5) for a caller-specified
  network/asset and reports the validated address or the exact
  failure stage. A test never creates a sweep, never signs, and
  its result is never reusable as a sweep destination.

## 3. Sweep requests reject destinations

### `POST /api/v1/sweeps`

```json
{ "wallet_id": "wal_…", "network": "ethereum",
  "asset_id": "usdt-ethereum", "address_ids": ["adr_…"] }
```

- The schema is closed: unknown fields are rejected, and the
  fields `destination_address` and `destination_endpoint_url`
  are rejected explicitly and loudly:

```json
{ "error": { "code": "destination_not_allowed",
  "message": "Sweep destinations come only from the registered endpoint." } }
```

  HTTP `422`. Silently ignoring a supplied destination is
  forbidden — a caller who believes they set the destination
  must learn immediately that they did not.
- Scope: `sweeps:create`. Idempotency-Key required.

## 4. Sweep state machine

```text
created
  → resolving            (endpoint call in progress)
  → resolution_failed    (terminal; §7 — no fallback)
  → resolved             (snapshot persisted, §8)
  → policy_check         (blacklist / limits / address checks)
  → policy_denied        (terminal)
  → awaiting_approval    (business quorum, if policy requires)
  → approval_expired / rejected   (terminal)
  → signing              (destination re-verified vs snapshot)
  → broadcast
  → confirming
  → completed            (terminal)
  → failed               (terminal, with stage + reason)
```

- Transitions are persisted; a worker crash resumes from the
  last persisted state, never from in-memory assumptions.
- `resolved → … → signing` carries the snapshot id. Any path
  that would sign without a snapshot id is unreachable by
  construction and alarmed if attempted.

## 5. Resolution protocol

Before **each new sweep**, Custodium performs a fresh HTTPS
`GET` to the registered endpoint. Results are never reused
across sweeps (§7 governs the single exception process:
none within a sweep after approval).

### 5.1 Request

```text
GET <registered-url>
X-Blockchain-Network: ethereum
X-Asset-ID: usdt-ethereum
X-WaaS-Request-ID: swp_01J…        (this sweep's id)
X-WaaS-Timestamp: 1790000000
Accept: text/plain
```

- Headers name the network and asset so a tenant serving
  multiple chains returns the right address per sweep.
- `X-WaaS-Request-ID` is unique per resolution attempt and is
  the tenant's replay/idempotency anchor on their side.
- Where the tenant endpoint requires request authentication,
  the request is additionally signed with the scope's resolver
  credential using the HMAC scheme of `authentication.md`,
  with timestamp+request-id in the canonical string
  (replay defence in both directions).

### 5.2 Response — exactly a plain-text single address

- Status must be `200`. Content is **exactly one address as
  plain text**: optional surrounding whitespace/newline is
  trimmed; the remainder must be a single token.
- **Strict size limit: 512 bytes** maximum response body.
  Larger bodies are rejected without parsing.
- Reject, as `resolution_failed`, any of:
  - empty or whitespace-only body;
  - malformed address for the requested network (§8);
  - ambiguous content: multiple tokens/lines, an address plus
    commentary, a list, or anything requiring "picking" one;
  - JSON — including `{"address": "…"}` — or HTML, XML, or any
    structured content, regardless of `Content-Type` claims;
  - an address valid for a *different* network than requested.
- The raw body hash and the trimmed address are recorded in the
  snapshot (§8); the full raw body is not retained beyond the
  size limit and is never logged if it fails validation.

## 6. SSRF and transport security

The resolver is an HTTP client calling tenant-influenced URLs:
it is a first-class SSRF surface and is hardened as one.

- **HTTPS only.** `http://` URLs are rejected at registration
  and at call time. TLS certificate verification is mandatory
  and cannot be disabled per-tenant; TLS errors fail closed.
- **No redirects.** `3xx` responses are not followed; a redirect
  is a resolution failure. The registered URL must answer
  directly. (Redirect-following would let the registered host
  bounce the resolver at internal targets.)
- **Address filtering:** after DNS resolution, every resolved
  IP is checked; the connection is refused if any candidate is
  private, loopback, link-local, multicast, unspecified, or in
  cloud metadata ranges (e.g. `169.254.169.254`, `fd00:ec2::254`
  equivalents). Hostnames that are IP literals are checked the
  same way. Registration-time checks do not substitute.
- **DNS rebinding defence:** resolve once, validate the address
  set, and connect to the validated address (with correct TLS
  SNI / Host for the original hostname) — never resolve twice
  and connect to an unvalidated second answer. TTL tricks and
  alternating answers therefore cannot swap in a private IP
  between check and connect.
- **Egress allowlist:** the resolver runs in a network segment
  whose egress is restricted; where the deployment supports it,
  per-tenant registered hosts are allowlisted at egress, and
  the resolver has no route to internal service networks or
  the metadata service at the network layer (defence in depth
  beneath the application checks above).
- **Timeouts:** bounded connect and total timeouts (order of
  seconds; exact values are an operations setting with a hard
  ceiling). Slow-loris style responses hit the total timeout
  and the 512-byte cap.
- **Bounded retries:** transient network failures may be retried
  at most twice with backoff, each attempt a fresh full
  validation. Validation, SSRF, format, and policy failures are
  never retried. Retries never extend to a different URL.

## 7. Fail closed — no stale fallback, no late re-resolution

- Any failure in §§5–6 or §8 → sweep enters `resolution_failed`
  (or fails at its current stage) and stops. There is **no**
  fallback to a previously resolved destination, a cached value,
  a default, or a human-typed address. "Last known good" is
  precisely the value an attacker wants used after they break
  or seize the endpoint.
- Once a sweep is approved against a snapshot, the destination
  is **not re-resolved**. Re-resolution after approval would
  let the endpoint return a different address than the one
  approvers saw. The only way to use a newly resolved address
  is to terminate the sweep and start a **new** sweep, with a
  new resolution, a new snapshot, and **new authorisation**.
- Endpoint disabled or registration changed mid-flight: sweeps
  not yet signed are aborted; already-broadcast sweeps complete
  their confirmation tracking (chain facts cannot be undone).

## 8. Validation and the immutable snapshot

On a syntactically valid response, before any approval:

1. Validate the address **for the requested network** using the
   chain adapter's rules (checksum/base58/TON form etc., see
   `../blockchains/`).
2. Check the destination against the manual blacklist and sweep
   policy (tenant allowlist if configured, self-sweep loops,
   deposit-address-as-destination mistakes). Denial is terminal
   (`policy_denied`), with the reason recorded.
3. Persist an **immutable `ResolvedDestinationSnapshot`**:
   `{ sweep_id, tenant/project/env scope, network, asset_id,
   destination_address, endpoint_url_hash, request_id,
   resolved_at, raw_body_sha256, resolver_version }`.
   Snapshots are append-only; no update path exists.
4. Approvers (where business quorum applies) see the snapshot's
   address — the exact value that will be signed.
5. **Immediately before signing**, the signer pipeline verifies
   that the transaction's destination equals the snapshot's
   address, byte-for-byte after network normalisation, and that
   the snapshot belongs to this sweep. Mismatch → abort, alarm,
   no signature. This check is in the signing path itself, not
   only in the API layer, so a bug or compromise above the
   signer cannot substitute a destination.

## 9. Audit and observability

Every registration change, test, resolution attempt (success or
failure stage), snapshot, abort, and signature-time verification
is audit-logged with actor/key id, scope, request id, and
timestamps — never with signing secrets. Repeated resolution
failures alert operations and the tenant; a destination that
changes between consecutive sweeps is surfaced in the dashboard
as a high-salience event, because legitimate changes are rare.

---

## Amendment — static destinations (2026-11-13)

Per the amendment recorded in ADR 0006, a project may instead
set `SweepPolicy.destination_mode = "static"` and register one
static hot-wallet address per network
(`PUT /sweep-destinations`, owner/administrator; validated and
normalized per network family). Sweeps then snapshot that
address — same immutable snapshot, same fail-closed behaviour,
`source = "static"` — and the resolver endpoint is not called.
The mode is per project; the default remains `resolver`, and
§1's prohibitions on destinations in sweep requests or files
are unchanged in both modes.
