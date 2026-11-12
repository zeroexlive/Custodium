# Sweeping & Treasury — Phase 10 Implementation Record

Status: **Implemented** (2026-11-12). Code:
`apps/backend/waas/modules/sweeps/`. This phase implements the
normative sweep-resolver design (`docs/api/sweep-resolver.md`,
ADR 0006) end to end, replacing the Phase 1 501 gates on the
endpoint routes with real behaviour.

## 1. The rule, enforced in code

A sweep's destination comes **only** from a fresh HTTPS call to
the tenant's registered endpoint, at sweep time:

- **Registration** (`SweepDestinationEndpoint`, one row per
  project — the project fixes tenant + environment): the URL
  lives **only in PostgreSQL**; registration requires a dashboard
  owner/administrator; the URL is validated at registration with
  the same SSRF rules used at call time; an optional signing
  secret is stored Fernet-encrypted and never returned; every
  change appends a `SweepEndpointHistory` row (actor, action,
  previous/new URL **hashes**) and an audit event.
- **`POST /sweeps` rejects destinations loudly**: the raw JSON
  body is inspected — `destination_address` or
  `destination_endpoint_url` → **422 `destination_not_allowed`**;
  any other unknown field → 422 (closed schema). Silently
  ignoring a supplied destination is treated as a bug class.
- **No local-file path exists**: there is no code path that
  reads a destination from settings, files, or environment.

## 2. The resolver client (§§5–6)

`resolver.resolve_destination` performs one fresh resolution:

- URL: HTTPS only, no credentials, no fragment; the host's
  **every DNS answer must be a public IP** (private, loopback,
  link-local incl. cloud metadata, multicast, reserved and
  unspecified answers refuse the call; IP-literal hosts are
  checked identically) — evaluated at registration and again at
  call time.
- Request headers per spec: network slug, asset id, unique
  `X-WaaS-Request-ID`, timestamp; when a signing secret is
  registered, an HMAC-SHA256 signature over
  timestamp/request-id/network/asset authenticates the call.
- Response: status exactly 200 (**3xx is a failure — redirects
  are never followed**), body ≤ **512 bytes**, UTF-8, and after
  trimming **exactly one token** (JSON — including
  `{"address": …}` — multi-token bodies, and commentary are
  rejected, never "picked from"); the address must validate
  **for the requested network** via the chain family's own
  rules. Transport failures retry at most twice; validation
  failures never retry. Nothing is cached between sweeps.
- Failures raise `ResolutionError` with a stage
  (`ssrf`, `dns`, `transport`, `redirect`, `http_status`,
  `too_large`, `format`, `wrong_network`, …) which the sweep
  records verbatim before entering `resolution_failed`.

## 3. The sweep lifecycle (§4)

`created → resolving → resolution_failed | resolved →
policy_denied | awaiting_approval → signing → broadcast →
confirming → completed | failed`, persisted at every step (the
`process_sweeps` worker command resumes from stored state):

- On resolution, a **`ResolvedDestinationSnapshot`** is
  persisted (sweep, destination + normalized form, endpoint URL
  hash, request id, raw-body SHA-256). Snapshots are
  **immutable at the model layer** — an update attempt raises.
- Policy checks run against the snapshot: manual blacklist,
  self-sweep (destination = one of the wallet's own addresses),
  and the Phase 9 reconciliation halt.
- Amount discovery: the wallet scope's `customer_available`
  minus the project `SweepPolicy.leave_behind`; below
  `min_sweep_threshold` the sweep completes as a no-op with the
  reason recorded. Business approval quorum reuses the Phase 9
  withdrawal policy (roles + maker-checker via `SweepApproval`).
- **After approval there is no re-resolution** (§7): execution
  passes the snapshot's address — the exact resolved string —
  to the signing pipeline via the shared
  `operations.dispatch.execute_transfer`, so sweeps inherit the
  pipelines' blacklist re-check, reservation accounting, signer
  gates, and confirmation tracking unchanged. Endpoint changes
  or disabling mid-flight therefore cannot redirect an approved
  sweep; a changed destination requires a new sweep.
- **Test tool** (`POST /sweep-destination-endpoint/test` +
  dashboard): performs a real resolution and reports the
  address or the failure stage; it creates no snapshot, no
  sweep, and its result is unusable as a destination.

Dashboard: the Sweep Endpoint view gained project scoping, the
test tool, enabled/version state, and the change-history table;
the Sweeps view is now a real list + create + approve surface
(previously an honest placeholder).

## 4. Verification performed

Backend suite: see `AGENTS.md`. The penetration-style matrix
(backlog exit criteria) covers: `http://` registration/call
rejection; DNS answers containing a private IP and an
IP-literal metadata address refused *before* any HTTP; URL
credentials refused; redirects not followed; JSON bodies,
two-token bodies, and 600-byte bodies rejected; a TRON address
returned for an Ethereum sweep rejected as `wrong_network`; a
full sweep cycle (resolve → snapshot → approval → execution →
confirmation) with exact ledger outcomes; snapshot immutability
enforced; an endpoint that starts returning a **different**
address after approval cannot redirect the approved sweep;
blacklisted and self-sweep destinations denied; unreachable
endpoint → `resolution_failed` with the transport stage;
below-threshold no-op; API-level destination-field and
unknown-field rejection (422, no sweep row created).

## 5. NOT verified / deferred

- **Live endpoint interoperability** (a real tenant HTTPS
  endpoint over the public internet) is not exercised from this
  sandbox; the resolver is verified against in-process HTTP
  doubles implementing the wire contract exactly.
- **Connection pinning** (connect to the validated IP with SNI)
  is a deployment-layer defence alongside the egress allowlist
  (§6); the application layer validates the DNS answer set at
  registration and immediately before each call, but does not
  pin the socket to a validated address.
- Temporal remains unwired: `process_sweeps` is the idempotent
  worker entrypoint, as with the earlier phases.
