# Custodium — Python SDK (Phase 0 Reference Outline)

> Status: Phase 0 design document. This system is **not production-ready**.
> This document specifies the reference behaviour for a Python client.
> It contains **no real secrets**; all keys below are placeholders.

## 1. Goals and non-goals

- Goals: correct HMAC signing, safe retries, idempotency, typed errors,
  exact integer money handling.
- Non-goals: the SDK never holds MPC shares, never signs chain
  transactions, and never chooses sweep destinations.

## 2. Installation and compatibility (target)

- Package name (planned): `custodium`.
- Python >= 3.11, dependencies limited to an HTTP client (`httpx`) and
  the standard library for cryptography (`hmac`, `hashlib`).
- Async and sync clients expose the same method surface.

## 3. Configuration

```python
from custodium import CustodiumClient

client = CustodiumClient(
    base_url="https://api.example.invalid",   # placeholder host
    api_key="ck_test_PLACEHOLDER",            # placeholder, not a secret
    api_secret="PLACEHOLDER_SECRET",          # load from env / secret store
    timeout_seconds=10.0,
)
```

Rules:

- Load `api_secret` from an environment variable or secret manager.
- Never hard-code secrets, never log them, never put them in URLs.
- One client instance is bound to one tenant project by its API key;
  tenant/project are derived server-side from the key, never sent
  as caller-chosen fields by the SDK.

## 4. HMAC signing — reference implementation outline

Every request is signed. The canonical string is:

```text
METHOD \n PATH \n TIMESTAMP \n NONCE \n SHA256_HEX(body)
```

Reference outline (illustrative, not a shipped library):

```python
import hashlib, hmac, secrets, time

def sign(secret: str, method: str, path: str,
         body: bytes, timestamp: int, nonce: str) -> str:
    body_hash = hashlib.sha256(body).hexdigest()
    canonical = "\n".join(
        [method.upper(), path, str(timestamp), nonce, body_hash]
    ).encode()
    return hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest()
```

Headers sent on each request:

| Header | Value |
|---|---|
| `X-Api-Key` | the public API key identifier |
| `X-Timestamp` | Unix seconds; server rejects stale timestamps |
| `X-Nonce` | random, unique per key; `secrets.token_hex(16)` |
| `X-Signature` | hex HMAC-SHA256 as above |
| `Idempotency-Key` | required on mutations (Section 5) |
| `Content-Type` | `application/json` |

Notes:

- Sign the exact bytes sent. Serialise JSON once, sign those bytes,
  send those bytes — never re-serialise after signing.
- Use `hmac.compare_digest` semantics server-side; clients just send hex.
- Clock skew: keep host clocks NTP-synced; a `401` with a clock error
  code means fix the clock, not retry blindly.

## 5. Idempotency

- All mutating calls (`POST`/`PATCH`/`DELETE` with effects) accept and
  should always send an `Idempotency-Key` (UUID4 recommended).
- Same key + same request body returns the original result without
  executing twice — including for withdrawals.
- Same key + **different** body is an error (`409 idempotency_conflict`);
  never reuse a key for a different operation.
- Generate a fresh key per logical operation, and reuse that same key
  across retries of that operation — that is the entire point.

```python
import uuid
key = uuid.uuid4().hex
client.withdrawals.create(..., idempotency_key=key)  # retry with same key
```

## 6. Money representation

- Amounts are **integers in the smallest unit** of the asset (wei,
  sun, lamports, nanotons, USDT base units) — in JSON and in Python.
- The SDK uses `int` only. Passing a `float` raises `TypeError` locally.
- Decimal-looking strings are rejected unless a helper explicitly
  converts them with `decimal.Decimal` to integer base units with an
  explicit decimals parameter and exactness check.

## 7. Retries

Safe to retry automatically:

- Network errors and `502/503/504`, and `429` after `Retry-After`.
- Only when the request is idempotent: all `GET`s, and mutations that
  carry an `Idempotency-Key` (reuse the same key).

Never retry automatically:

- `400/401/403/404/409/422` — these are decisions, not transients.
- A mutation without an idempotency key.

Policy: exponential backoff with jitter, base 0.5s, factor 2, max 5
attempts, max elapsed 30s, honour `Retry-After` as a floor.

## 8. Errors

The API returns a stable envelope:

```json
{ "error": { "code": "insufficient_funds", "message": "...",
             "request_id": "req_PLACEHOLDER", "details": {} } }
```

SDK exception hierarchy (planned):

| Exception | HTTP | Meaning |
|---|---|---|
| `CustodiumError` | any | base class, carries `code`, `request_id` |
| `AuthenticationError` | 401 | bad/expired signature, revoked key |
| `PermissionDeniedError` | 403 | key scope does not allow operation |
| `NotFoundError` | 404 | not found *in your tenant scope* |
| `ValidationError` | 422 | schema/policy validation failed |
| `ConflictError` | 409 | idempotency or state conflict |
| `RateLimitError` | 429 | includes `retry_after` |
| `ServerError` | 5xx | retryable per Section 7 |

Callers must branch on `error.code`, not on human-readable `message`.

## 9. Webhooks from Python

- Verify webhook HMAC with the subscription secret before trusting any
  field (see `webhooks.md` for the scheme, rotation, and replay rules).
- Treat webhook delivery as a *hint*: re-fetch the resource via the API
  before acting, and never mark a financial operation successful solely
  because a webhook arrived.

## 10. Sweeps

- The SDK's sweep call takes wallet, asset, and policy identifiers only.
- It has **no destination parameter**: sweep destinations come only from
  the tenant-registered HTTPS resolver endpoint returning a plain-text
  address — never from a sweep request and never from local files.
- Any SDK PR adding a destination argument to sweeps must be rejected.

## 11. Testing guidance for integrators

- Use sandbox keys; test HMAC against published golden vectors.
- Test: replayed nonce rejection, expired timestamp, idempotency replay,
  retry-after handling, and float-amount rejection.
- Record/replay HTTP fixtures must scrub signatures and secrets.

## 12. Security checklist

- [ ] Secrets only from env/secret manager; none in code or logs.
- [ ] Nonce unique per request; timestamp from a synced clock.
- [ ] Idempotency key on every mutation, reused only for its retries.
- [ ] Integer amounts only.
- [ ] Errors branched on `code`; `request_id` logged for support.
