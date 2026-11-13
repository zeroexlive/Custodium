# Feature Matrix — Custodium vs. a Usable MPC Wallet Service

Audited 2026-11-13 against the feature surface a tenant needs to
run a real custody integration (the checklist commercial MPC
WaaS products are compared on). Status meanings:

- **Available** — implemented and covered by the backend suite.
- **Gated** — implemented; activation waits on the independent
  cryptographic review (the signer gate). Not a missing feature.
- **Added 2026-11-13** — gaps found by this audit and closed in
  the same pass.
- **Out of scope** — deliberately excluded by the product spec,
  with the reason recorded.
- **External** — not a code feature; an operational/owner action.

## Accounts & access

| Feature | Status | Where |
|---|---|---|
| Registration, email verification, password reset | Available | `/auth/*` |
| Organizations, projects (sandbox/production), team roles (owner/administrator/developer/finance_operator/withdrawal_approver/viewer) | Available | organizations, projects |
| **Two-factor auth (TOTP) with recovery codes** | **Added 2026-11-13** | `/auth/2fa/setup|enable|disable|verify`; secret Fernet-encrypted, recovery codes stored as digests, login pauses at a signed 5-minute challenge |
| API keys: create/rotate/revoke, scopes, secret shown once | Available | api_credentials |
| **API-key IP allowlist + expiry, settable at creation** | **Added 2026-11-13** | enforcement already existed in machine auth; `ApiKeyIn` now accepts `ip_allowlist` / `expires_at` |
| HMAC-SHA256 machine auth, nonce replay protection | Available | `waas/api/authentication.py`, `docs/api/hmac-test-vectors.md` |
| Audit log + CSV export, staff support lookup | Available | audit |

## Wallets & addresses

| Feature | Status | Where |
|---|---|---|
| Threshold wallets (2-of-3 default, configurable), per-customer via `external_customer_id` | Gated | wallets + mpcsigner |
| Wallet provisioning (real DKG, address derivation, activation) | Gated | `POST /wallets/{id}/provision`, `provision_wallet` command; rehearsal in `docs/operations/provisioning-rehearsal.md` |
| One address per network (10 seeded networks, 5 chains) | Gated (derivation) / Available (registry) | wallets |
| Freeze / archive lifecycle | Available | wallet status API |
| Balances per wallet and per project (integer base units) | Available | ledger |
| Custom token registration (network + contract/mint identity) | Available | `POST /assets` |

## Money movement

| Feature | Status | Where |
|---|---|---|
| Deposit detection, confirmations, reorg reversal, blacklist holds | Available | indexing |
| Transaction lookup by hash (tenant + public projections) | Available | `/transactions/lookup` |
| Withdrawals with policy engine: hard limits, approval quorum, maker-checker | Available | operations |
| **Destination address book + optional withdrawal allowlist enforcement** | **Added 2026-11-13** | `/address-book`, `/address-book/policy`; enforced beside the blacklist check in withdrawal creation |
| Manual blacklist (never an AML/KYT claim) | Available | blacklist |
| Service fee + actual network fee accounting | Available | operations |
| Sweeps via tenant resolver endpoint only, immutable snapshots | Available | sweeps (ADR 0006 — no destination in requests, ever) |
| **Auto-sweep rules (balance-threshold triggers)** | **Added 2026-11-13** | `/auto-sweep-rules`, `run_auto_sweeps` command; sweeps still flow through resolver + policy + approvals |
| Gas station (native-balance top-ups that defer, never fail) | Available | gasstation |
| Refund playbook, reconciliation halts, platform kill switch | Available | operations, hardening |

## Notifications & billing

| Feature | Status | Where |
|---|---|---|
| Webhooks: signed deliveries, retry ladder, dead letters, replay | Available | webhooks, `docs/api/webhooks.md` |
| **Webhook signing-secret rotation** | **Added 2026-11-13** | `POST /webhooks/endpoints/{id}/rotate-secret` |
| Plans, quotas, usage metering, fiat invoicing (off-platform collection) | Available | plans |

## Deliberately out of scope

- **UTXO chains (Bitcoin etc.)** — the mandated chain set is
  ETH/BSC/TRON/Solana/TON; the account-model ledger and pipelines
  are built for it. Adding UTXO is a product decision, not a gap
  fix.
- **Staking, NFTs, swaps/DEX, fiat on/off-ramps** — not part of
  the custody specification.
- **AML/KYT/sanctions screening** — excluded by spec; the manual
  blacklist is the compliance surface, always described as such.
- **Key refresh for cggmp24** — the pinned library has none; the
  compensating control (re-key + migrate) is a review decision,
  recorded in the MPC review package.
- **mTLS between signer nodes** — documented limitation of the
  signer transport (`docs/architecture/production-signer.md`);
  bearer tokens today, mTLS is pre-production hardening tracked
  in the readiness checklist.
- **Dashboard UI for the newest endpoints** (2FA enrollment,
  address book, auto-sweep rules) — the APIs are complete and
  dashboard-authenticated; wiring the Vue views is a follow-up
  UI pass, tracked here so it is not mistaken for done.

## External (not code)

Independent cryptographic review (now also covering
provisioning and this pass), penetration test, legal review,
funded live-testnet soaks, key ceremony and DR drills on real
infrastructure, and the written production approval decision.
Until then the signer gate stays off by default and Custodium
remains **not Production Approved**.
