# Signer Security — Bound Intent and Independent Verification

Status: Phase 0 — normative design. The signer tier is the last
line of defence: it assumes every component above it, including
Django, the coordinator, and tenant API keys, may be compromised
or buggy, and it is designed so that compromise alone cannot
produce a valid signature over attacker-chosen content.

## 1. Trust model

- **Django / SaaS backend: untrusted by signers.** It is the
  business-logic layer and the most exposed component.
- **Coordinator: untrusted for content, trusted only to relay.**
  It assembles sessions; it cannot alter an intent undetected.
- **Signers: independently policy-enforcing.** Each signer
  verifies before contributing a partial signature. A signer
  that merely signs what it is handed is a remote signing
  oracle and is forbidden by this design.
- **Result: Django cannot unilaterally sign.** Producing a
  signature needs (a) a threshold quorum of signers (2-of-3,
  see `key-management.md`) *and* (b) each participating signer
  independently accepting the same bound intent *and* (c) any
  business quorum the tenant policy requires (§5). No single
  service, credential, host, or person satisfies all three.

## 2. Bound intent

Every signing request is an **intent**: a canonical, hashed,
versioned structure that signers receive in full — not a bare
digest prepared elsewhere. Signing a digest whose preimage the
signer has not seen and checked is forbidden.

```text
intent = {
  version:            1,
  intent_id:          unique, single-use,
  tenant_id:          …,
  project_id / environment: …,
  wallet_id:          …,
  network:            "ethereum",
  asset_id:           "usdt-ethereum",   // network+contract identity
  operation:          "withdrawal" | "sweep",
  source_addresses:   [ … ],
  destination_address:"0x…",             // for sweeps: from snapshot
  sweep_snapshot_id:  "…" | null,        // required for sweeps
  amount:             "250000000",       // integer, smallest unit
  fee: { asset_id, max_amount },         // fee bounds, §3
  payload_hash:       hex(sha256(chain-specific signable payload)),
  payload:            <the full transaction template>,
  policy_version:     "pol-2026-11-…",   // policy evaluated against
  nonce_or_seq:       chain account nonce/seqno/blockhash data,
  expires_at:         unix time, short bound,
  approvals:          [ business approval records, §5 ]
}
intent_hash = SHA-256(canonical-serialisation(intent))
```

Signers sign protocol material derived from `payload_hash` only
after verifying the payload hashes to it and the payload encodes
exactly the intent's fields for that chain.

## 3. What each signer verifies before participating

A signer MUST verify **all** of the following, from its own
locally held policy and data where indicated, and MUST refuse
the session on any failure. Partial checks are non-compliance.

1. **Tenant and wallet binding:** `tenant_id`, `wallet_id`,
   and the group public key for that wallet match the signer's
   own wallet registry entry. A wallet id the signer does not
   hold a share for is refused.
2. **Network and asset:** `network` is one the signer serves;
   `asset_id` resolves (network + contract/mint/master) to an
   asset the wallet holds on that network. Symbol-only asset
   references are refused.
3. **Destination:** `destination_address` is syntactically valid
   for the network; for withdrawals it equals the destination
   in the approved business record; **for sweeps it equals the
   `ResolvedDestinationSnapshot` address for `sweep_snapshot_id`**
   (see `../api/sweep-resolver.md` §8) — the signer checks the
   snapshot, not a destination asserted by the coordinator.
4. **Amount:** integer, positive, within tenant/wallet policy
   limits (per-tx and velocity limits in signer-held policy),
   and equal to the amount encoded in the payload.
5. **Fee bounds:** the payload's maximum possible fee is within
   the intent's `fee.max_amount` and within policy fee bounds
   for the network/asset. Unbounded-fee payloads (e.g. a gas
   price field the coordinator could inflate) are refused.
6. **Payload integrity:** recompute the chain-specific encoding
   from intent fields (via the chain adapter library the signer
   embeds) and check it equals `payload` and `payload_hash`.
   The signer never trusts a pre-built payload it cannot
   reconstruct; where full reconstruction is impossible for a
   chain, that chain is not enabled for signing.
7. **Policy version:** `policy_version` equals a policy version
   the signer has been issued and has not seen revoked. Unknown
   or stale policy versions are refused. Policy distribution is
   signed by the policy authority and applied atomically.
8. **Expiration and freshness:** `expires_at` is in the future
   and within the maximum intent lifetime; the chain freshness
   fields (nonce/seqno/recent blockhash) match chain state the
   signer samples or is reliably provided, within tolerance.
   Expired intents cannot be revived; a new intent is required.
9. **Approvals:** business approval records (§5) are present,
   validly signed by the approvers' credentials, cover this
   exact `intent_hash`, and satisfy the tenant's quorum rule.
   Approvals over a different intent hash are worthless here.
10. **Blacklist / policy denylist:** destination (and, where
    policy requires, source) is not on the current manual
    blacklist version held by the signer. Stale blacklist
    beyond its freshness bound → refuse (fail closed).
11. **Single use:** `intent_id` has not been signed before
    (signer-local consumed registry, persisted). Replays —
    including "the same withdrawal again after a timeout" —
    are refused; retries are new intents linked to the same
    business operation above the signer.

## 4. Session and transport security

- Signer-to-coordinator and signer-to-signer channels are
  mutually authenticated (per-signer certificates/keys) and
  encrypted; a session binds `intent_hash`, session id, and
  participant set, and every protocol message is authenticated
  in that binding. Cross-session message injection must fail.
- Signers accept sessions only for wallets they serve and only
  from the coordinator identity for their deployment — but
  acceptance to *join* is not agreement to *sign*: §3 runs
  after joining, inside each signer.
- Timeouts are short and aborts are clean: an aborted session
  destroys its ephemera (nonces/presignatures) per
  `key-management.md` §4.
- Rate and concurrency limits per wallet/tenant in each signer
  blunt a compromised coordinator trying to brute-force policy
  edges or exhaust presignature material.

## 5. Business quorum vs. cryptographic threshold — separate

These are different mechanisms solving different problems, and
neither substitutes for the other:

| | Business quorum | MPC threshold |
|---|---|---|
| Question answered | *Should* this happen? | *Can* a signature be produced? |
| Actors | Tenant approvers (people/roles) | Signer services holding shares |
| Rule example | 2 of 3 tenant admins approve | 2 of 3 share-holders participate |
| Enforced in | SaaS policy + signer check §3.9 | MPC protocol |
| Failure it stops | Fraudulent / mistaken instruction | Key theft / rogue server |

- A satisfied business quorum without threshold participation
  signs nothing. Threshold participation without the required
  business quorum must also sign nothing — that is exactly what
  §3.9 enforces inside the signer, so bypassing the SaaS
  approval UI does not help an attacker.
- Tenant-configurable business quorum rules are versioned as
  part of policy (§3.7); changing a quorum rule is itself a
  quorum-governed administrative act.

## 6. Compromise cases (design acceptance tests)

- **Django fully compromised:** attacker can create intents but
  cannot forge tenant approver signatures, cannot alter the
  sweep snapshot a signer checks, cannot raise signer-held
  limits, and cannot extract shares. Expected outcome: no valid
  signature over attacker-chosen destination/amount.
- **Coordinator compromised:** can withhold or replay sessions
  (liveness impact) but replays die on §3.11, alterations die on
  §3.6, destination swaps die on §3.3.
- **One signer compromised:** yields one share — below threshold.
  Attacker still needs a second signer to accept the intent,
  which runs §3 independently. Detection: refresh/reshare per
  `key-management.md`.
- **Tenant API key compromised:** bounded by key scopes, tenant
  policy limits, business quorum, and signer checks; key
  revocation path is in `../api/authentication.md` §7.
- **Policy distribution compromised:** policies are signed;
  unsigned or wrongly signed policy is rejected by signers.
  Policy *authority* compromise is a platform-critical incident
  (its key is HSM-held, dual-controlled).

## 7. Logging and observability

Signers log: intent_hash, intent_id, wallet, network, decision
(accept/refuse + which check failed), session id, timestamps.
Signers never log: shares, nonce material, presignatures, full
payloads containing tenant-sensitive memos beyond operational
need. Refusals alert: a spike in §3 refusals is treated as a
possible upstream compromise signal, not as noise.

## 8. Non-goals and limits

- Signers do not judge business legitimacy beyond policy,
  approvals, blacklist, and limits; a properly approved,
  in-policy payment to a novel destination will be signed.
  That is the tenant's authorisation working as designed.
- Signer checks are only as strong as signer-held policy
  freshness; the freshness bounds in §3.7/§3.10 are therefore
  security parameters, reviewed with the protocol review.
- This document does not approve any implementation. It states
  what an implementation must do to be considered for the
  independent review gate in `protocol-evaluation.md`.
