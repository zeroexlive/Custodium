# Custodium — Manual Blacklist (Phase 0)

> Status: Phase 0 design document. This system is **not production-ready**.
>
> **The blacklist is manual only.** It is **not** AML/KYT, it is **not**
> sanctions screening, and it is **not** risk scoring. Nothing in this
> document claims the blacklist provides complete AML coverage — it
> does not, and it must never be described that way to tenants,
> auditors, or regulators.

## 1. Purpose

A manually curated list of blockchain addresses that the platform or a
tenant has decided must not receive funds (and, per policy, may be
flagged when sending). It exists so a human decision — "do not pay this
address" — is enforced consistently at every money-out path.

What it is not:

- Not AML (anti-money-laundering) tooling or a compliance programme.
- Not KYT (know-your-transaction) analysis or chain analytics.
- Not sanctions-list screening (no external lists are imported).
- Not risk scoring: entries have no score, probability, or risk tier.
- Not address clustering, taint analysis, or behavioural detection.

If a tenant needs those capabilities, they need a dedicated provider;
Custodium's manual blacklist does not substitute for one.

## 2. Entry model

| Field | Meaning |
|---|---|
| `scope` | `platform` or `tenant` (see Section 3) |
| `tenant_id` | Owning tenant; null only for platform entries |
| `chain/network` | Specific chain + network the entry applies to |
| `address` | Stored both raw (as entered) and normalised (Section 4) |
| `reason` | Free-text operator reason (required) |
| `created_by` / `created_at` | Actor and timestamp (UTC) |
| `expires_at` | Optional expiry; expired entries do not block |
| `active` | Soft-disable flag; entries are never hard-deleted |

Entries are addresses only — not transaction hashes, not IP addresses,
not user identities. Notes must not contain secrets or personal data
beyond what the operational reason strictly needs.

## 3. Platform vs. tenant entries

- **Platform entries**: created by platform operators; apply to all
  tenants, all projects. Used sparingly, e.g. an address confirmed as
  the destination of an active theft from the platform.
- **Tenant entries**: created by a tenant's admins; apply only to that
  tenant (all its projects, unless a project scope is set explicitly).
- Enforcement is the union: a withdrawal is blocked if **either** a
  platform entry **or** an entry of the withdrawing tenant matches.
- Tenant entries never affect other tenants: not their withdrawals,
  not their sweeps, not their search results.

## 4. Normalisation per chain

Matching is done on the normalised form; raw input is kept for audit.

| Chain family | Normalisation |
|---|---|
| EVM (ETH, BSC) | Lowercase hex; validate `0x` + 40 hex chars; checksum form derived for display only |
| TRON | Decode Base58Check to hex form; store/compare the canonical hex; reject invalid checksum |
| Solana | Base58, case-sensitive — **no** case folding; validate decoded length (32 bytes) |
| TON | Parse raw and user-friendly (bounceable/non-bounceable) forms to the same raw `workchain:hash`; compare raw form |

Rules:

- An address that cannot be parsed/normalised for its chain cannot be
  added and cannot be matched — invalid input is an error, never a
  silent miss.
- Entries are per chain/network: an EVM address entry on Ethereum does
  not automatically block the same hex address on BSC; operators add
  per-network entries deliberately (the UI may offer to copy, audited
  as separate entries).
- Memo/tag-based destinations are out of scope for this list: matching
  is on the address field only.

## 5. Where checks happen (enforcement points)

Every check is a hard block on match, evaluated in this order:

1. **Withdrawal validation**: when a withdrawal is requested, the
   destination is checked before the request is accepted/recorded as
   valid. A match returns a policy error and creates an audit event.
2. **Immediately before signing**: the final destination in the
   canonical signing payload is re-checked. This second check is
   mandatory — an entry added after validation must still stop the
   signing. The signer-side flow treats a match as abort, not warning.
3. **Sweeps, per policy**: the resolved sweep destination is checked
   after resolution and before signing, where the tenant/platform sweep
   policy enables blacklist enforcement (the default is enabled).
   Sweep destinations come only from the tenant-registered HTTPS
   resolver endpoint returning a plain-text address — never from a
   sweep request or local files — and the **resolved** address is what
   gets checked, normalised per Section 4.

Additional rules:

- If the blacklist service/DB is unavailable, financial operations
  **fail closed**: validation and signing pause rather than skip checks.
- Deposits **from** a blacklisted address are not auto-blocked on-chain
  (receipt cannot be prevented); per policy they may be flagged for
  manual review, but no AML/KYT conclusion is drawn from a manual entry.
- A check result (match / no match / unavailable) is recorded for every
  enforcement event, including which entry matched (by entry ID).

## 6. Management operations

- Create, disable, expire, and search entries via the admin UI/API.
- Creating or disabling a **platform** entry requires a platform-admin
  role; tenant entries require tenant-admin within that tenant.
- All changes are append-only audited: actor, tenant scope, entry,
  before/after state, reason, timestamp. Entries are soft-disabled,
  never deleted, so historical "why was this blocked?" is answerable.
- Bulk import, if offered, is still manual curation: a human uploads a
  reviewed list; each imported row becomes an individual audited entry
  with the import recorded as its reason/source. No external feed,
  sanctions list, or analytics provider is connected.

## 7. Search and visibility

- Platform operators can search platform entries, and — for support
  and incident handling — can see that a tenant entry caused a block,
  without exposing tenant entries in bulk.
- Tenants can search **only their own** entries plus the fact (not the
  underlying reason details) that a platform entry blocks an address.
- **Never reveal other tenants' entries**: not in search, not in error
  messages, not in APIs, not in support replies. A withdrawal blocked
  by a platform entry says "blocked by platform policy"; blocked by
  the tenant's own entry, it identifies that entry to that tenant.
- Existence is also confidential: querying an address returns matches
  only from scopes the caller is entitled to see (see tenant
  isolation). There is no cross-tenant "is this address listed?" oracle.

## 8. Testing

Mandatory test cases per release:

1. Entry blocks at withdrawal validation.
2. Entry added **after** validation still blocks before signing.
3. Resolved sweep destination is blocked per policy.
4. Normalisation: EVM case variants match; Solana case variants do
   **not** incorrectly fold; TRON Base58 and hex forms match; TON raw
   and friendly forms match.
5. Expired/disabled entries do not block; re-enabled entries do.
6. Tenant B's entry does not block tenant A, and A cannot see it.
7. Blacklist outage causes fail-closed behaviour, not silent passes.

## 9. Limitations (state these plainly)

- Coverage is only as good as manual curation: an address nobody added
  is not blocked, however illicit its activity may be.
- This is not complete AML, not KYT, not sanctions screening, and not
  risk scoring; marketing, sales, and support must never present it
  as such.
- Attackers rotate addresses; a manual list is a point control for
  known addresses, not a detection capability.
