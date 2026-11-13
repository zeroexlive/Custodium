# Webhooks — Signed Event Delivery

Status: Implemented in Phase 11 (2026-11-12). Code:
`apps/backend/waas/modules/webhooks/`.

## Registering an endpoint

`POST /api/v1/webhooks/endpoints` (dashboard owner/administrator,
or a machine key with the `webhooks:manage` scope):

```json
{ "project_id": "…", "url": "https://tenant.example/hooks",
  "events": ["deposit.credited", "withdrawal.completed"] }
```

The response contains the endpoint's **signing secret exactly
once** (`whsec_…`). It is stored envelope-encrypted and never
returned again. Endpoint URLs are validated with the platform's
SSRF rules (HTTPS only, public IPs) at registration and again at
every delivery.

## Event catalog

| Event | When |
|---|---|
| `deposit.credited` | A deposit passed confirmations and was credited to the customer's available balance. |
| `withdrawal.completed` | A Phase 9 withdrawal request completed on-chain. |
| `withdrawal.failed` | A withdrawal request reached the terminal failed state (reason in the payload). |
| `sweep.completed` | A sweep completed (including below-threshold no-ops, marked in `status_reason`). |
| `sweep.failed` | A sweep reached the terminal failed state. |

## Delivery format

```http
POST <endpoint-url>
Content-Type: application/json
X-WaaS-Event-Id: 3f6d…           (stable per event — deduplicate on this)
X-WaaS-Event-Type: withdrawal.completed
WaaS-Signature: t=1790000000,v1=<hex>
```

Body (compact JSON, sorted keys):

```json
{"id":"3f6d…","type":"withdrawal.completed",
 "created_at":"2026-…","data":{ …event payload… }}
```

**Signature verification:** `v1` is
`HMAC-SHA256(secret, f"{t}." + raw_body)` hex-encoded, where
`raw_body` is the exact request body bytes. Reject deliveries
whose timestamp is far from your clock (replay window) and
always verify against the raw bytes, never a re-serialisation.

## Rotating the signing secret

`POST /webhooks/endpoints/{id}/rotate-secret` (owner/administrator,
or a machine key with `webhooks:manage`) replaces the endpoint's
`whsec_` secret and returns the new one exactly once. The old
secret stops verifying immediately — update the receiver in the
same change window. Rotations are audit-logged
(`webhook.secret_rotated`).

## Retries and replay

Any non-2xx response (or transport failure) schedules a retry:
attempts at ~1 minute, 5 minutes, 30 minutes, 2 hours, and
12 hours after the previous attempt (6 attempts total). After
the final attempt the delivery is **dead**. Tenants can inspect
deliveries (`GET /api/v1/webhooks/deliveries`) and replay any
delivery (`POST /api/v1/webhooks/deliveries/{id}/replay`,
dashboard owner/administrator) — replay resets the attempt
counter; the event id stays the same, so receivers must handle
duplicates idempotently.

Delivery is at-least-once by design: **deduplicate on
`X-WaaS-Event-Id`** and use the event's `data` ids to re-fetch
the underlying resource via the API for anything
security-sensitive.
