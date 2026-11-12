# Transaction Lookup by Network and Hash

Status: Phase 0 — normative design.
Endpoint: `GET /api/v1/transactions/lookup?network=<network>&hash=<hash>`
Auth: machine HMAC, scope `transactions:read`. Tenant-aware.

## 1. Purpose

Given a chain transaction hash, answer three questions for the
calling tenant: (a) what happened on-chain, in normalised form;
(b) does any part of it belong to this tenant (their customer,
wallet, or address); (c) if it belongs, link to the internal
deposit/withdrawal/sweep record. It is an investigation tool,
not an oracle for other people's transactions.

## 2. Request

```text
GET /api/v1/transactions/lookup?network=tron&hash=9f2c…(64 hex)
```

- `network` (required): one of `ethereum`, `bsc`, `tron`,
  `solana`, `ton`. Unknown network → `422 validation_error`.
- `hash` (required): chain-native hash format, validated per
  network before any lookup (hex txid for EVM/TRON, base58
  signature for Solana, TON hash forms per adapter). Malformed
  → `422`, no downstream query is made.
- No other parameters. In particular there is no `tenant_id`,
  `customer_id`, or `address` parameter: belonging is computed
  server-side, never asserted by the caller.

## 3. The 10-step processing pipeline

1. **Authenticate & scope.** Verify HMAC, derive tenant/project/
   environment from the key, require `transactions:read`.
2. **Validate inputs.** Normalise `network`; validate and
   normalise `hash` format for that network (case rules per
   chain; reject wrong-length/charset values).
3. **Local index lookup.** Query the platform transaction index
   (populated by indexers) for `(network, hash)`. This index
   covers all tenants internally, but results are not yet
   tenant-visible (§4 filters everything that follows).
4. **Local record match.** If index rows exist, join to internal
   deposits, withdrawals, sweeps, and ledger entries to find
   candidate internal records.
5. **Belonging evaluation.** Compute `belongs_to_tenant` (§4)
   from address/wallet/customer ownership for *this* tenant.
6. **RPC fallback (optional, policy-gated).** If there is no
   local index row, the adapter MAY query chain RPC/node APIs
   for the raw transaction — subject to rate limits, caching,
   and a per-network enable flag. Absence locally never triggers
   an unbounded chain scan.
7. **Chain-specific parsing.** The adapter parses the raw
   transaction into the normalised model (§5) using the rules
   for that network.
8. **Attribution pass.** Re-evaluate belonging against parsed
   participants (senders, recipients, token accounts, Jetton
   wallets) — parsing may reveal participants the index lacked.
9. **Privacy projection.** Build the response through the
   projection in §4: tenant-owned detail in full; third-party
   detail reduced to the public on-chain minimum, with all
   other-tenant platform metadata stripped.
10. **Respond & audit.** Return the normalised result; write an
    audit record (who looked up what, belonging outcome) without
    logging other tenants' internal identifiers.

## 4. Privacy and `belongs_to_tenant`

### 4.1 Definition

```text
belongs_to_tenant = true  iff  any participant address/account
  in the transaction (sender, recipient, token account owner,
  Jetton wallet owner, fee payer where it identifies a wallet)
  is an address owned by a wallet of the calling tenant in the
  key's project/environment, OR an internal record (deposit,
  withdrawal, sweep) of that tenant references this hash.
```

Otherwise `belongs_to_tenant = false` — including when the
transaction belongs to a *different* tenant of Custodium.

### 4.2 Non-negotiable rules

- **Never expose another tenant's customer, wallet, or address
  book data.** No `external_customer_id`, wallet id, label,
  internal transaction id, balance, or policy data of any other
  tenant appears in the response — in fields, in error text, in
  timing, or in "did you mean" hints.
- When `belongs_to_tenant=false`, the response contains only
  what any public block explorer would show for that hash:
  network, hash, block, timestamp, status, and normalised
  transfers with raw on-chain addresses. Platform attribution
  is omitted entirely, not redacted field-by-field after the
  fact — the projection is built that way.
- Existence oracle defence: lookup of a hash for a transaction
  involving another tenant returns the same shape as lookup of
  a purely external transaction. There is no response (including
  `404` vs `200` distinctions) that reveals "this hash belongs
  to some Custodium tenant".
- If the hash is unknown both locally and via RPC, return
  `404 transaction_not_found` — identical for "never existed"
  and any internal state the caller may not learn about.
- Rate limiting and audit apply as for an enumeration attempt:
  bulk probing of hashes is throttled and alerted.

## 5. Chain-specific handling

### 5.1 EVM (Ethereum, BSC)

- Fetch transaction + receipt. Use receipt `status` for success.
- Token transfers come from receipt **logs**: filter `Transfer`
  events by the asset's contract address (identity is
  network+contract, never symbol — see chain docs), decode
  `from`/`to`/`value` with the contract's decimals.
- A native-value transfer and token transfers in the same tx are
  all reported; internal transactions via traces are out of
  scope for v1 and their absence is documented, not hidden.
- Reorg safety: report `confirmations` and a `finalised` flag
  per the chain's finality policy; unfinalised data is labelled.

### 5.2 TRON

- Fetch transaction + transaction-info; use receipt result and
  `blockNumber`, energy/bandwidth fee fields normalised.
- Parse `TransferContract`, `TransferAssetContract`, and TRC-20
  `TriggerSmartContract` calls; TRC-20 transfers are confirmed
  from logs in transaction-info where present.
- Addresses normalised between hex and Base58Check forms for
  ownership matching; the response uses Base58Check.
- Distinguish a failed contract execution (fee consumed, no
  transfer) from a successful transfer.

### 5.3 Solana

- Fetch transaction with `jsonParsed` where available, plus
  meta balances. A signature may contain many instructions.
- Parse **inner instructions** as well as top-level ones: SPL
  token transfers are frequently inner (e.g. under a program
  call), and ignoring them misattributes the transfer.
- Use pre/post **token balances** keyed by account index and
  **token account → owner** resolution: the participant is the
  token account's owner, not the token account address itself.
  Ownership matching runs against owners.
- Report slot, `blockTime`, fee (lamports), and error state
  from `meta.err`; a failed transaction transfers nothing even
  if instructions were attempted.

### 5.4 TON

- A logical transaction is a chain of **messages**; parse the
  transaction on the relevant account plus its out-messages.
- Jetton transfers are identified via the sender/recipient
  **Jetton wallet** accounts (per-owner wallet contracts derived
  from the Jetton master), with `internal_transfer` /
  `transfer_notification` opcodes decoded by the adapter.
  Attribution matches the *owner* address behind a Jetton
  wallet, not merely the wallet contract address.
- Report workchain/address forms normalised to user-friendly
  form for display, raw form retained for matching; include
  `lt`, block seqno, exit codes, and bounce status — a bounced
  transfer is not a completed transfer.

## 6. Normalised response model

```json
{
  "network": "tron",
  "hash": "9f2c…",
  "status": "confirmed",
  "finalised": true,
  "block": { "number": 61234567, "timestamp": "2026-11-12T10:15:00Z" },
  "confirmations": 25,
  "fee": { "asset_id": "native:tron", "amount": "13500000" },
  "transfers": [
    { "asset_id": "usdt-tron", "from": "T…", "to": "T…",
      "amount": "250000000" }
  ],
  "belongs_to_tenant": true,
  "tenant_record": {
    "type": "deposit",
    "transaction_id": "txn_01J…",
    "wallet_id": "wal_01J…",
    "external_customer_id": "cust_8841",
    "status": "credited"
  }
}
```

- `tenant_record` is present **only** when `belongs_to_tenant`
  is true; it is absent (not `null`-filled with hints) otherwise.
- `transfers[].amount` is an integer string in smallest units;
  `asset_id` encodes network+contract/mint/master identity.
- `status`: `pending | confirmed | failed | not_found`.

## 7. Caching, freshness, and errors

- RPC fallback results are cached briefly; local-index data is
  authoritative once a transaction is indexed and credited.
- A lookup never mutates ledger state: discovering a deposit via
  lookup does not credit it; crediting is the indexer's job
  under finality policy. This prevents lookup-driven double
  credit and race conditions.
- Errors: `422 validation_error` (bad network/hash format),
  `404 transaction_not_found`, `429 rate_limited`,
  `502 upstream_unavailable` when RPC fallback fails and no
  local data exists — never a fabricated "not found" in that
  case, and never stale data presented as fresh.
