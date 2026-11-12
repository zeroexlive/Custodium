# Custodium — Webhooks (Phase 0)

> Status: Phase 0 design document. This system is **not production-ready**.
>
> **Cardinal rule: never mark a financial operation successful solely
> on webhook delivery.** A webhook is a notification that something
> changed; the API / ledger state, re-fetched and verified, is the
> source of truth.

## 1. Model

- A subscription belongs to one tenant/project and one HTTPS endpoint.
- Each subscription has its own signing secret and event filter.
- Events are created by a **transactional outbox** (Section 8): the
  event row is written in the same DB transaction as the state change,
  so an event cannot be lost between commit and publish, nor published
  for a change that rolled back.
- Delivery is at-least-once. Consumers must be idempotent.

## 2. Events

| Event | Fires when |
|---|---|
| `wallet.created` | A wallet is created for the project |
| `address.created` | A deposit address is generated and registered |
| `deposit.detected` | A deposit is seen on-chain, below confirmation threshold |
| `deposit.credited` | Confirmation threshold met and ledger credit posted |
| `deposit.reversed` | A credited/detected deposit is removed by a reorg |
| `withdrawal.requested` | A withdrawal request is accepted |
| `withdrawal.signed` | Threshold signing completed |
| `withdrawal.broadcast` | Transaction broadcast to the network |
| `withdrawal.confirmed` | Withdrawal reaches the confirmation threshold |
| `withdrawal.failed` | Withdrawal fails validation, policy, or broadcast |
| `sweep.requested` | A sweep is scheduled under a sweep policy |
| `sweep.resolved` | The tenant resolver returned a destination address |
| `sweep.broadcast` | Sweep transaction broadcast |
| `sweep.confirmed` | Sweep reaches the confirmation threshold |
| `sweep.failed` | Resolution, validation, or broadcast failed |
| `transaction.confirmed` | Generic confirmation for a tracked transaction |

Notes:

- `deposit.*` covers detected, credited, and reversed; wildcard
  subscriptions are stored as explicit event lists at subscribe time.
- Amounts in payloads are integer strings in the smallest unit; never
  floats, never decimal-formatted numbers.

## 3. Payload format

```json
{
  "id": "evt_PLACEHOLDER",
  "type": "deposit.credited",
  "created_at": "2026-01-01T00:00:00Z",
  "tenant_id": "ten_PLACEHOLDER",
  "project_id": "prj_PLACEHOLDER",
  "data": {
    "wallet_id": "wal_PLACEHOLDER",
    "address": "ADDRESS_PLACEHOLDER",
    "chain": "ethereum",
    "asset": "USDT",
    "amount": "1000000",
    "tx_hash": "TXHASH_PLACEHOLDER"
  }
}
```

- `id` is the **delivery-independent event ID**: redeliveries of the
  same event carry the same `id`. Consumers deduplicate on it.
- Payloads contain only the owning tenant's data (see tenant isolation).
- Payload schema is versioned by field addition only; removing or
  re-typing a field requires a new event version and notice.

## 4. Signing and verification

Headers:

| Header | Meaning |
|---|---|
| `X-Custodium-Event-Id` | Event `id` |
| `X-Custodium-Delivery-Id` | Unique ID of *this delivery attempt* |
| `X-Custodium-Timestamp` | Unix seconds when this delivery was signed |
| `X-Custodium-Signature` | `v1=<hex HMAC-SHA256>` |

Signed content: `TIMESTAMP + "." + RAW_BODY`, HMAC-SHA256 with the
subscription secret. Verification (consumer side):

1. Read the **raw** body bytes; do not parse-then-reserialise.
2. Reject if the timestamp is outside a 5-minute tolerance window.
3. Compute the expected HMAC and compare in constant time.
4. Reject on any mismatch; log the delivery ID, never the secret.
5. Deduplicate on the event ID before processing (Section 6).

Secrets are placeholders in all examples; real secrets are shown once
at subscription creation and stored only by the tenant and the platform's
secret store — never in code, tickets, or logs.

## 5. Timestamp and replay protection

- The 5-minute window plus signature binds each delivery to its time.
- A captured delivery replayed later fails the timestamp check.
- A captured delivery replayed *inside* the window is stopped by event
  ID deduplication — consumers must keep processed IDs at least 24h.
- Delivery IDs are unique per attempt, so a replayed delivery ID is
  itself evidence of replay; consumers may reject repeats outright.

## 6. Consumer idempotency

- At-least-once delivery means duplicates are normal, not exceptional.
- Processing pattern: `INSERT event_id` into a processed-events table
  (unique) in the same transaction as the business update; on conflict,
  return `200` and do no work.
- Return `200` only after durable processing; return `5xx`/timeout to
  trigger a retry when processing genuinely failed.

## 7. Retries, backoff, and dead letters

- Retry schedule per delivery (targets): immediate, 1 min, 5 min,
  30 min, 2 h, 6 h, 12 h, 24 h — exponential backoff with jitter.
- Any non-`2xx` response, timeout (>10 s), or connection error retries.
- `4xx` (except `408`/`429`) still retries on the same schedule: tenant
  endpoints are often misconfigured transiently; the DLQ is the remedy.
- After the final attempt, the delivery enters the **dead-letter queue
  (DLQ)**: retained, inspectable by the owning tenant, and manually
  replayable from the dashboard/API after the endpoint is fixed.
- DLQ depth and oldest-age are alerted (see `operations/monitoring.md`).
- Endpoints that fail continuously may be auto-paused, with an audit
  event and tenant notification; pausing never deletes queued events.

## 8. Transactional outbox (producer side)

1. Business transaction updates state **and** inserts the outbox row.
2. A relay worker reads unpublished outbox rows, creates deliveries,
   and marks rows published — idempotently, keyed by event ID.
3. Relay crashes cannot lose events (row is durable) and cannot create
   two events for one change (unique event ID per state transition).
4. Ordering: deliveries for one object are attempted in creation order,
   but consumers must not depend on strict ordering — use per-object
   state/versions in payloads and re-fetch when in doubt.

## 9. Secret rotation

- Each subscription supports **two active secrets** (current + next).
- Rotation: generate next secret -> platform signs with both during a
  grace window (default 24 h) -> tenant confirms their endpoint accepts
  the new secret -> old secret retired.
- Signatures during the window carry a key identifier so consumers know
  which secret verified.
- Emergency rotation (suspected leak) retires the old secret immediately;
  deliveries during the gap may fail verification and will be retried /
  DLQ'd rather than silently trusted.

## 10. Endpoint requirements and SSRF safety

- HTTPS only, valid certificate, no redirects to other hosts.
- Platform egress applies SSRF controls: private/loopback/link-local
  and metadata ranges denied at connect time, DNS-rebinding resistant
  (see threat model T-09).
- Response body is ignored; keep endpoints fast and side-effect-light.

## 11. What webhooks are not

- Not a settlement guarantee: `*.confirmed` reflects the platform's
  confirmation policy at delivery time; reorgs can still produce a
  later `deposit.reversed`.
- Not a substitute for reconciliation (see `operations/reconciliation.md`).
- Not an authorisation channel: no webhook asks the tenant to approve
  a financial operation, and replies to deliveries are ignored.
- Reiterate the cardinal rule to every integrator: **never mark a
  financial operation successful solely on webhook delivery** — verify
  via an authenticated API read of the resource's current state.

## 12. Testing

- Dashboard/API can send a signed `test` event to a subscription.
- Integrator test cases: bad signature, stale timestamp, duplicate
  event ID, out-of-order events, DLQ replay, dual-secret rotation.
