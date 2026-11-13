# ADR 0006: Sweep Destinations Only via Tenant-Registered Resolver

- **Status:** Proposed — Accepted for Phase 0/1, NOT Production Approved
- **Date:** 2026-11-12
- **Deciders:** Custodium architecture team
- **Phase scope:** Binding design rule from Phase 0; implemented in Phase 10

## Status

Proposed and accepted as a binding rule for Phase 0 and Phase 1, and for every later phase unless superseded by an ADR of equal rigour.
This decision is NOT Production Approved. Sweeping itself is not implemented in Phase 1; this ADR fixes the rule before any sweep
code exists, so no implementation can drift into a weaker pattern.

## Context

Sweeping consolidates funds from many deposit addresses into a tenant's treasury / cold destination. The destination address is
therefore one of the highest-value targets in the entire system:

- If an attacker (external, malicious insider, or compromised tenant
  API credential) can influence the sweep destination for a single sweep, they can steal the entire swept amount in one transaction.
- If a destination can be supplied ad hoc — in a sweep API request,
  in a local file on a worker, in an environment variable edited at deploy time — then every one of those surfaces becomes a theft
  vector and an audit gap.
- Destinations also change rarely and legitimately (treasury rotation,
  cold-wallet migration). The change path must be deliberate, authorised, and auditable — not a parameter on a routine request.

Custodium's mandated rule, restated without dilution:

> Sweep destinations are obtained ONLY by calling a tenant-registered
> HTTPS resolver endpoint, whose URL is stored in PostgreSQL, and
> which returns the destination address as plain text. Destinations
> are NEVER accepted in a sweep request, and NEVER read from local
> files.

This ADR exists to make that rule precise, testable, and hard to accidentally weaken.

## Decision

### 1. Registration (the only way a resolver comes to exist)

- A tenant registers a sweep destination resolver by providing an
  **HTTPS URL** in the Custodium console / API, under privileged tenant roles, with the change written to the audit log.
- The resolver URL is stored in **PostgreSQL** as part of the
  tenant / project configuration. It is configuration of record — not code, not a file, not an environment variable.
- Registration and change of a resolver URL follow the same change-
  control discipline as other crown-jewel tenant settings: authorised role, audit entry (who, when, old URL → new URL, source IP), and
  notification to tenant administrators. Cooling-off / dual-approval for production resolver changes is a Phase 10/12 design item.
- Only `https://` URLs are accepted. Plain HTTP, other schemes,
  URLs with embedded credentials, and URLs with fragments are rejected.

### 2. Resolution (how a sweep obtains its destination)

- At sweep time, the sweep workflow (Temporal, ADR 0003) calls the
  registered resolver URL over HTTPS and receives the destination address as a **plain-text** response body (a single address string,
  trimmed of surrounding whitespace).
- The returned address is validated for the target chain / asset
  (format, checksum where the chain defines one, network match: sandbox resolvers cannot yield production destinations and vice
  versa).
- The validated address is stored as an **immutable snapshot** on
  the sweep record: address, resolver URL identifier, resolution timestamp, and response metadata (status, latency, content hash).
  The signing step uses the snapshotted address from the sweep record — it never re-resolves mid-ceremony and never accepts a
  substituted value.
- If resolution fails, times out, returns a non-2xx status, returns
  malformed / multi-line / unexpected content, or fails validation, the sweep **fails closed**: it aborts, releases any ledger
  reservation via the defined compensation, raises an operator alert, and requires human attention. There is no fallback address,
  no cached-address reuse by default, and no retry-forever loop.

### 3. Absolute prohibitions

- A sweep API request must **never** contain a destination address.
  The API schema has no such field; a request that smuggles one in an unexpected field is rejected / ignored-and-logged per API rules.
- Sweep destinations must **never** be read from local files,
  worker configuration files, spreadsheets, or code constants.
- No Custodium operator or support workflow may "just type in" a
  destination to unblock a stuck sweep. The fix is always at the resolver registration / resolver service, with audit.

### 4. SSRF and resolver-call protections

Calling a tenant-supplied URL from Custodium servers is a classic Server-Side Request Forgery (SSRF) surface. The resolver client must:

- Enforce HTTPS with full certificate verification; no option to
  disable verification, including in sandbox (sandbox may use a clearly separate test CA by explicit environment design, never a
  global "insecure" flag).
- Resolve DNS and **reject private, loopback, link-local, and
  metadata-service address ranges** (RFC 1918, 127.0.0.0/8, ::1, 169.254.0.0/16 including 169.254.169.254, and equivalents), and
  re-validate the connected IP to resist DNS-rebinding / TOCTOU.
- Not follow redirects by default; if redirects are ever allowed,
  they are limited (count, same-host or allow-listed) and every hop re-passes all checks above. Default Phase 10 behaviour: reject 3xx.
- Apply strict timeouts (connect and total), a small maximum response
  size, and require a plain-text content type (or no/compatible type) with a body that parses as exactly one address.
- Egress from the resolver-calling worker is restricted by network
  policy to outbound HTTPS, so a bypassed check still cannot reach internal HTTP services.
- Log resolution attempts (tenant, URL id, outcome, latency) without
  logging any credentials the tenant endpoint might expect; resolver authentication, if the tenant requires it, uses a Custodium-issued
  credential / signed request defined in Phase 10 design — never a secret pasted into the URL.

## Consequences

### Positive

- A single, auditable chokepoint controls every sweep destination:
  the registered URL in Postgres, plus the immutable per-sweep snapshot. Investigators can always answer "where did this sweep
  go, who registered that resolver, and what did it return, when?"
- Compromise of a tenant API key alone does not yield destination
  control: the attacker can at most trigger the tenant's own registered resolver, not redirect funds to themselves.
- Tenants keep custody-side control of their treasury policy in
  their own resolver service (allowlists, rotation, freezes on their side) without Custodium holding destination spreadsheets.

### Negative

- Tenant resolver availability becomes a sweep dependency: if the
  tenant endpoint is down, sweeps fail closed and wait for humans. This is intentional (fail closed), but it is an operational cost.
- Tenants must build and secure a small HTTPS endpoint correctly;
  Custodium must provide a precise resolver contract, examples, and a test tool in the console.
- SSRF defences add implementation and testing burden to what looks
  like "just an HTTP GET". That burden is not optional.

### Neutral / mitigations

- A resolver health / test-resolution action in the console lets
  tenants verify their endpoint (returning a masked preview of the address) without creating a sweep.

## Alternatives Considered

### A. Destination address in the sweep request — Rejected absolutely

- This is the pattern this ADR exists to forbid. It makes every API
  caller a destination authority and turns any credential leak or request-tampering bug into direct theft.

### B. Destination stored directly as an address in Custodium's DB — Rejected

- Tempting and simple, but it makes Custodium's console / DB the
  destination authority, diffusing accountability and inviting "edit the address" support flows. The mandated model keeps the
  address decision in the tenant's own resolver service, with only the URL as Custodium-side configuration of record.

### C. Destinations in local files / worker config — Rejected absolutely

- Un-auditable, undeployable safely, invisible to tenants, and a
  classic insider / supply-chain tampering target.

### D. Hard-coded treasury addresses per chain in code — Rejected

- Code deploys are not a change-control system for treasury policy,
  and per-tenant hard-coding does not scale or audit at all.

## Security Considerations

- This ADR protects the single most theft-attractive value in the
  sweep flow; treat any proposed exception as a critical finding.
- Resolver URL changes are security events: audit, notify, and (for
  production, per Phase 10/12 design) consider dual approval and a cooling-off period during which sweeps pause.
- Immutable snapshots prevent time-of-check/time-of-use swaps
  between resolution and signing.
- Address validation must include network correctness: a valid-
  format address on the wrong network is a loss event, not a pass.
- Manual blacklist checks (the project's only screening control —
  no AML/KYT integration per scope) apply to resolved destinations exactly as to withdrawal destinations: a blacklisted resolved
  address fails the sweep closed.
- Resolver responses are untrusted input: strict size, encoding,
  and single-address parsing; anything else aborts.

## Review Triggers

Re-open this ADR if any of the following occurs:

- Any request — product, customer, or internal — to accept a sweep
  destination from any source other than the registered resolver. Such a request starts from "no" and requires a superseding ADR.
- A tenant cannot operate an HTTPS resolver and proposes an
  alternative; assess without weakening §3 prohibitions.
- A new SSRF technique or resolver-call incident emerges in testing
  or in the wider industry.
- Resolver authentication (signed requests / mTLS to tenant
  endpoints) is introduced or changed.
- Before Phase 10 implementation AND again before ANY production
  approval — re-review SSRF defences, change control, and snapshot immutability with penetration-test evidence.

---

## Amendment — 2026-11-13 (owner's direction)

The resolver endpoint remains the **default and recommended**
destination source. At the product owner's explicit direction, a
second tenant-registered source is now permitted: a **static
hot-wallet address per (project, network)**, registered through
the dashboard API by an owner/administrator
(`StaticSweepDestination`), selected per project via
`SweepPolicy.destination_mode = "static"`.

What does NOT change — the invariants this ADR exists for:

- A sweep request still **never** carries a destination; the API
  still rejects destination fields with 422.
- The destination is still **tenant-registered configuration
  only** (PostgreSQL, role-gated, audited) — never a file, env
  var, seed, or per-request value.
- Resolution still happens **exactly once, before approval**,
  and the result is stored in the same **immutable**
  `ResolvedDestinationSnapshot` (now carrying `source =
  "resolver" | "static"`); signing uses the snapshot only.
- Absent or invalid static destinations **fail closed** with
  `RESOLUTION_FAILED`; there is no fallback between modes.

Rationale for the amendment: some tenants operate a fixed hot
wallet per chain and cannot run a resolver endpoint. The static
mode serves them without weakening the request-side rule — the
attack this ADR defends against (destination injection via a
compromised API key or a swapped file) remains impossible,
because changing a static destination requires an
owner/administrator dashboard session and is audit-logged.
