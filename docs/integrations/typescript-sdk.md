# Custodium — TypeScript SDK (Phase 0 Reference Outline)

> Status: Phase 0 design document. This system is **not production-ready**.
> This document specifies reference behaviour for a strict-TypeScript
> client. It contains **no real secrets**; all keys are placeholders.

## 1. Goals and non-goals

- Goals: correct HMAC signing, safe retries, idempotency, typed errors,
  exact integer money handling, strict typing throughout.
- Non-goals: the SDK never holds MPC shares, never signs chain
  transactions, and never chooses sweep destinations.

## 2. Installation and compatibility (target)

- Package name (planned): `@custodium/sdk`.
- Node.js >= 20 (server) or modern browsers for read-oriented use;
  financial mutations belong in server-side code, not browsers.
- Compiled with `strict: true`, `exactOptionalPropertyTypes: true`,
  and `noUncheckedIndexedAccess: true`. No `any` in public types.

## 3. Configuration

```ts
import { CustodiumClient } from "@custodium/sdk";

const client = new CustodiumClient({
  baseUrl: "https://api.example.invalid", // placeholder host
  apiKey: "ck_test_PLACEHOLDER",          // placeholder, not a secret
  apiSecret: process.env.CUSTODIUM_API_SECRET ?? "", // secret store / env
  timeoutMs: 10_000,
});
```

Rules:

- Load the secret from an environment variable or secret manager.
- Never bundle the secret into browser code, logs, or URLs.
- Tenant/project are derived server-side from the API key; the SDK
  never sends caller-chosen tenant identifiers.

## 4. HMAC signing — reference implementation outline

Canonical string (identical to the Python SDK):

```text
METHOD \n PATH \n TIMESTAMP \n NONCE \n SHA256_HEX(body)
```

Node `crypto` outline:

```ts
import { createHmac, createHash, randomBytes } from "node:crypto";

export function signRequest(args: {
  secret: string; method: string; path: string;
  body: Uint8Array; timestamp: number; nonce: string;
}): string {
  const bodyHash = createHash("sha256").update(args.body).digest("hex");
  const canonical = [
    args.method.toUpperCase(), args.path,
    String(args.timestamp), args.nonce, bodyHash,
  ].join("\n");
  return createHmac("sha256", args.secret).update(canonical).digest("hex");
}

export const newNonce = (): string => randomBytes(16).toString("hex");
```

Web Crypto outline (browser/edge runtimes):

```ts
async function signWebCrypto(secret: string, canonical: string) {
  const enc = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw", enc.encode(secret), { name: "HMAC", hash: "SHA-256" },
    false, ["sign"],
  );
  const sig = await crypto.subtle.sign("HMAC", key, enc.encode(canonical));
  return [...new Uint8Array(sig)]
    .map((b) => b.toString(16).padStart(2, "0")).join("");
}
```

Headers sent on each request:

| Header | Value |
|---|---|
| `X-Api-Key` | public API key identifier |
| `X-Timestamp` | Unix seconds; stale timestamps are rejected |
| `X-Nonce` | random, unique per key |
| `X-Signature` | hex HMAC-SHA256 of the canonical string |
| `Idempotency-Key` | required on mutations (Section 5) |

Sign the exact bytes sent: serialise JSON once (`JSON.stringify` into
a `Uint8Array`), sign it, send it. Do not re-serialise after signing.

## 5. Idempotency

- All mutating methods accept `idempotencyKey?: string`; callers should
  always provide one (UUID, e.g. `crypto.randomUUID()`).
- Same key + same body returns the original result, including for
  withdrawals; same key + different body is `409 idempotency_conflict`.
- Retries of one logical operation reuse its key; a new operation gets
  a new key. The client enforces this by taking the key as an explicit
  option rather than generating one per HTTP attempt.

## 6. Money representation

- Amounts are integers in the smallest unit, typed as `bigint` in
  TypeScript and serialised as decimal strings in JSON.
- `number` is **not** accepted for amounts: IEEE-754 floats cannot
  represent base units exactly. The public types make this a compile
  error, and runtime guards reject `number` defensively.

```ts
type Amount = bigint; // smallest unit; never a float
interface CreateWithdrawal {
  walletId: string; asset: string; amount: Amount; destination: string;
}
```

## 7. Retries

Automatically retry only:

- Network failures, `502/503/504`, and `429` (after `Retry-After`).
- Requests that are idempotent: all `GET`s, plus mutations carrying an
  `Idempotency-Key` (reused unchanged).

Never retry: `400/401/403/404/409/422`, or unkeyed mutations.
Policy: exponential backoff with jitter, base 500 ms, factor 2, max 5
attempts, 30 s total budget, `Retry-After` honoured as a floor. An
`AbortSignal` from the caller cancels in-flight retries.

## 8. Errors

API error envelope:

```json
{ "error": { "code": "insufficient_funds", "message": "...",
             "request_id": "req_PLACEHOLDER", "details": {} } }
```

The SDK throws a discriminated error type:

```ts
export class CustodiumError extends Error {
  readonly code: string; readonly requestId: string;
  readonly httpStatus: number;
}
export class AuthenticationError extends CustodiumError {} // 401
export class PermissionDeniedError extends CustodiumError {} // 403
export class NotFoundError extends CustodiumError {} // 404 in your scope
export class ValidationError extends CustodiumError {} // 422
export class ConflictError extends CustodiumError {} // 409
export class RateLimitError extends CustodiumError { // 429
  readonly retryAfterSeconds: number;
}
export class ServerError extends CustodiumError {} // 5xx, retryable
```

Branch on `code` / error class, never on the human-readable `message`.

## 9. Webhooks from TypeScript

- Verify the webhook HMAC with the subscription secret using a
  constant-time comparison (`timingSafeEqual` in Node) before use.
- See `webhooks.md` for the scheme, replay window, and rotation.
- A webhook is a hint, not proof: re-fetch via the API, and never mark
  a financial operation successful solely on webhook delivery.

## 10. Sweeps

- The sweep method accepts wallet, asset, and policy identifiers only.
- There is deliberately **no `destination` field** in its type: sweep
  destinations come only from the tenant-registered HTTPS resolver
  endpoint returning a plain-text address — never from a sweep request
  and never from local files. Strict typing makes misuse a compile error.

## 11. Testing guidance for integrators

- Verify signing against the shared golden vectors (same vectors as
  the Python SDK).
- Test nonce replay, expired timestamp, idempotency replay/conflict,
  `bigint` serialisation at values above `Number.MAX_SAFE_INTEGER`,
  and rejection of `number` amounts.
- Scrub signatures and secrets from recorded fixtures/snapshots.

## 12. Security checklist

- [ ] Secret from env/secret manager only; never shipped to browsers.
- [ ] Unique nonce per request; synced clock for timestamps.
- [ ] Idempotency key on every mutation, reused only for its retries.
- [ ] Amounts are `bigint` end-to-end; no `number`, no floats.
- [ ] Errors handled by class/`code`; `requestId` logged for support.
