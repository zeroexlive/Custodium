# SDK Examples — Signed API Calls

Status: Phase 11 (2026-11-12). Minimal, dependency-light
examples implementing the HMAC scheme of
`docs/api/authentication.md`. Verify your implementation
against `docs/api/hmac-test-vectors.md` before going live.

## Python (stdlib only)

```python
import hashlib, hmac, json, time, uuid, urllib.request

BASE = "https://api.custodium.example/api/v1"
KEY_ID = "ck_live_…"          # from the console
SECRET = "…"                  # shown once at key creation

def call(method, path, body_obj=None):
    body = b"" if body_obj is None else json.dumps(body_obj).encode()
    ts = str(int(time.time()))
    nonce = uuid.uuid4().hex
    canonical = "\n".join([method, path, ts, nonce,
                           hashlib.sha256(body).hexdigest()])
    signature = hmac.new(SECRET.encode(), canonical.encode(),
                         hashlib.sha256).hexdigest()
    req = urllib.request.Request(
        BASE + path, data=body if method != "GET" else None,
        method=method,
        headers={
            "X-Api-Key-Id": KEY_ID, "X-Signature": signature,
            "X-Timestamp": ts, "X-Nonce": nonce,
            "Content-Type": "application/json",
            "Idempotency-Key": uuid.uuid4().hex,  # money endpoints
        })
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())

# Create a withdrawal request (destination is a tenant-supplied
# payout address — withdrawals only; sweeps never take one):
call("POST", "/withdrawals", {
    "wallet_id": "…", "network": "ethereum",
    "asset_id": "…", "destination_address": "0x…",
    "amount": "250000",
})
```

## JavaScript (Node ≥ 18, global fetch)

```js
import { createHash, createHmac, randomUUID } from "node:crypto";

const BASE = "https://api.custodium.example/api/v1";
const KEY_ID = "ck_live_…";
const SECRET = "…";

export async function call(method, path, bodyObj) {
  const body = bodyObj === undefined ? "" : JSON.stringify(bodyObj);
  const ts = String(Math.floor(Date.now() / 1000));
  const nonce = randomUUID().replaceAll("-", "");
  const canonical = [method, path, ts, nonce,
    createHash("sha256").update(body).digest("hex")].join("\n");
  const signature = createHmac("sha256", SECRET)
    .update(canonical).digest("hex");
  const res = await fetch(BASE + path, {
    method,
    headers: {
      "X-Api-Key-Id": KEY_ID, "X-Signature": signature,
      "X-Timestamp": ts, "X-Nonce": nonce,
      "Content-Type": "application/json",
      "Idempotency-Key": randomUUID(),
    },
    body: method === "GET" ? undefined : body,
  });
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
  return res.json();
}
```

## Verifying a webhook (Node)

```js
import { createHmac, timingSafeEqual } from "node:crypto";

export function verifyWebhook(secret, rawBody, header) {
  // header: "t=1790000000,v1=<hex>"
  const t = header.match(/t=(\d+)/)[1];
  const v1 = header.match(/v1=([0-9a-f]+)/)[1];
  const expected = createHmac("sha256", secret)
    .update(`${t}.`).update(rawBody).digest("hex");
  return timingSafeEqual(Buffer.from(v1), Buffer.from(expected));
}
```

Notes: timestamps must be within the 300-second window and each
nonce may be used once — generate both per request. Amounts are
always integer strings in the asset's base units.
