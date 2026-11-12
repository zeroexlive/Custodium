# ADR 0005: HMAC-SHA256 Authentication for the Custodium API

- **Status:** Proposed — Accepted for Phase 0/1, NOT Production Approved
- **Date:** 2026-11-12
- **Deciders:** Custodium architecture team
- **Phase scope:** Phase 1 (API keys / HMAC) and all subsequent API phases

## Status

Proposed and accepted as the working API authentication design for Phase 0 and Phase 1 only. This decision is NOT Production Approved.
Key-management and transport details must be re-reviewed before any production API handling real funds is exposed.

## Context

Custodium exposes a programmatic API that tenants' servers use to create wallets, read balances, and (in later phases) request
withdrawals and sweeps. These are machine-to-machine calls where:

- Interactive session cookies and browser OAuth flows do not fit.
- A bearer token alone, if leaked, is replayable until it expires
  or is revoked — unacceptable for fund-moving operations.
- Requests must be authenticated for integrity as well as identity:
  an attacker who can alter the amount or destination in transit must not produce a valid request.
- Replays of captured valid requests must fail.

The Phase 1 product flow is: a tenant creates an API key in the console; the secret is **shown once** at creation; the tenant's
server then signs every API request with that secret. The console session (cookie/JWT for the web UI) is a separate concern and does
not replace API HMAC authentication.

A critical cryptographic fact shapes storage design: **HMAC verification requires the actual secret.** Unlike a password, an
HMAC secret cannot be stored only as a one-way hash — a hash of the secret cannot be used to verify a signature computed with the
secret. Storage must therefore be recoverable by the server under strict protection (envelope encryption), not hashed-and-compared.

## Decision

Adopt **HMAC-SHA256 request signing** for all tenant API calls.

### 1. Canonical string

Each request is signed over a canonical string containing, in a fixed documented order, at minimum:

```
METHOD \n
PATH + QUERY (canonicalised, exactly as sent) \n
SHA-256 hex digest of the raw request BODY \n
TIMESTAMP \n
NONCE
```

- `METHOD`: uppercase HTTP method.
- `PATH + QUERY`: the exact request path and canonical query string.
- `BODY digest`: SHA-256 of the raw body bytes (empty-body digest
  for GET/DELETE without a body). Signing the digest binds the body without ambiguity over whitespace or key ordering — the raw bytes
  are what is digested.
- `TIMESTAMP`: Unix epoch seconds (UTC), sent in a header.
- `NONCE`: a unique, unpredictable value per request, sent in a
  header (UUIDv4 or at least 128 bits of randomness).

Signature: `HMAC-SHA256(secret, canonical_string)`, hex- or base64-encoded per the published API spec, sent in a header together
with the API key identifier, timestamp, and nonce. Header names and the exact canonicalisation are specified in the API reference and
frozen for Phase 1; any change is a versioned API change.

### 2. Verification rules (server side, fail closed)

- Look up the API key by its public identifier; reject unknown,
  revoked, expired, or wrong-environment (sandbox vs production) keys.
- **Timestamp window: 300 seconds.** Reject requests whose timestamp
  differs from server time by more than 300 seconds, in either direction. Clients must sync clocks (NTP).
- **Nonce uniqueness:** reject any nonce already seen for that API
  key within the timestamp window (nonces are stored for at least the window duration, in Redis or Postgres). This makes a captured
  request non-replayable inside its validity window; outside the window, the timestamp check rejects it.
- Recompute the expected signature and compare in **constant time**.
- Any failure — malformed headers, digest mismatch, stale timestamp,
  reused nonce, bad signature — returns a generic authentication error without revealing which check failed.

### 3. Secret generation, display, and storage

- Secrets are generated server-side with a CSPRNG, with at least
  256 bits of entropy, encoded for copy-paste at creation.
- The plaintext secret is **shown exactly once**, at creation, to
  the authorised console user. It is never shown again, never sent by email, and never logged.
- At rest, the secret is stored **envelope-encrypted**: a per-secret
  data-encryption key (DEK) encrypts the secret; the DEK is wrapped by a key-encryption key (KEK) held in the deployment's secret
  management (environment-injected in Phase 1 development; KMS/HSM- backed in real deployments, decided before production).
- A non-secret fingerprint / prefix may be stored in plaintext so
  tenants and support can identify which key is which.
- The database alone must not be sufficient to recover secrets:
  a database dump without the KEK yields ciphertext only.
- Key rotation creates a new key/secret pair; revocation is
  immediate and disables verification for that key identifier.

## Consequences

### Positive

- Integrity and authenticity per request, including the body —
  tampering with amounts or destinations invalidates the signature.
- Replay resistance via the 300-second window plus nonce store.
- No secret travels on the wire: only signatures, timestamps, and
  nonces are sent, so TLS termination logs capture no usable secret.
- Shown-once plus envelope encryption gives a defensible storage
  story that a plain hash (unusable) or plaintext column (unsafe) cannot provide.

### Negative

- Tenants must implement canonical signing correctly; client SDKs /
  examples and a signature-test endpoint are required to reduce integration errors (clock skew is the most common failure).
- Envelope encryption adds key-management operations: KEK rotation,
  DEK re-wrapping, and backup discipline for the KEK.
- Nonce storage adds a write per API request (bounded by the window).

### Neutral / mitigations

- Publish exact canonicalisation rules, worked examples with test
  vectors, and reference signing snippets in the API docs (Phase 1 acceptance requires a working HMAC round-trip in tests).

## Alternatives Considered

### A. Bearer API tokens only (no signing) — Rejected for fund-moving APIs

- A leaked bearer token is fully replayable and malleable in effect:
  the token authenticates the caller but does not bind the request body. Acceptable, if at all, only for read-only sandbox tooling —
  not adopted as the general API scheme.

### B. Store only a hash of the secret (password-style) — Rejected (impossible)

- HMAC verification mathematically requires the secret itself.
  A stored hash cannot verify incoming signatures. Any design that claims otherwise is broken; envelope encryption is the correct
  recoverable-storage mechanism.

### C. OAuth 2.0 client credentials / mTLS as the only API auth — Deferred

- Viable for enterprise integrations and may be added later as an
  additional scheme, but HMAC is simpler for Phase 1 tenants, language-agnostic, and matches the mandated Phase 1 specification.

### D. Signing without timestamp/nonce (signature only) — Rejected

- A valid captured request could be replayed indefinitely. The
  timestamp window and nonce are not optional decoration.

### E. AWS-SigV4-style full header signing — Rejected as over-scoped for Phase 1

- The chosen canonical string covers method, path+query, body,
  timestamp, and nonce — the fields whose mutation matters here — without the complexity of canonical header lists.

## Security Considerations

- All API traffic requires HTTPS; HMAC is not a substitute for TLS
  (without TLS, nonces/signatures are observable and metadata leaks).
- Constant-time signature comparison; generic error responses.
- Rate limiting per API key and per IP, with alerting on bursts of
  signature failures (possible probing or a leaked key being tested).
- Secrets never appear in logs, traces, error reports, Temporal
  payloads (ADR 0003), or analytics. Log the key identifier and fingerprint only.
- Sandbox and production keys are fully separated: different key
  namespaces, different secrets, no cross-environment verification.
- Revocation and tenant off-boarding must propagate immediately to
  the verification path (no long-lived cached "valid" decisions).
- The KEK is a crown-jewel secret: its compromise plus a database
  dump compromises all API secrets. KEK custody, rotation, and access auditing receive production-gate scrutiny in Phase 12.

## Review Triggers

Re-open this ADR if any of the following occurs:

- A tenant or auditor requires OAuth2 / mTLS as an additional or
  replacement scheme.
- Any replay, canonicalisation, or clock-skew incident in testing
  or production-like environments.
- The KEK management solution changes (for example migration to a
  cloud KMS or HSM), or a KEK compromise is suspected.
- API versioning introduces new signed fields (for example mandatory
  idempotency keys as signed headers).
- Before ANY production approval — re-review canonicalisation test
  vectors, nonce-store behaviour under load, and KEK custody in full.
