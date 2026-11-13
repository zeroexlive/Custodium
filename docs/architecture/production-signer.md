# Production signer service

Status: **Implemented + Tested locally (2026-11-13). NOT Security
Reviewed, NOT Production Approved.** Built at William's direction
so that the independent cryptographic review has an implementation
to review. Activation in the Django wiring stays behind an
explicit default-off gate (below) until that review passes.

Code: `services/mpc/crates/signer_service` (Rust, binary
`custodium-signer`) + `apps/backend/waas/modules/mpcsigner`
(Django client).

## What it is

One binary per threshold participant node (2-of-3 in the reference
topology, matching the six-server deployment: one signer node on
each of S4/S5/S6). Each node:

- holds exactly **one share per key**, serialized by the threshold
  library and encrypted at rest with XChaCha20-Poly1305 under a
  per-node 32-byte store key (file-provided; AEAD failure = hard
  error, fail closed);
- stores only public metadata in plaintext (curve, threshold,
  group public key);
- exchanges protocol messages **directly with peer nodes** over
  HTTP authenticated by a cluster bearer token
  (`POST /internal/inbox`); broadcast goes to all peers except the
  sender, mirroring `round_based` semantics;
- exposes a client API (`/v1/*`, API bearer token): create key
  (DKG), get public key, sign. The node receiving a client request
  acts as **coordinator** — it starts sessions on the participating
  peers and collects public results. The coordinator never
  receives, relays, or logs key shares: CGGMP messages travel
  peer-to-peer through `round_based` delivery, and FROST round-2
  packages are sent directly to their recipient (only commitments
  are broadcast and only signature shares reach the aggregator,
  exactly as the protocol prescribes).

## Protocols (Phase 3 pins, unchanged)

- **ECDSA/secp256k1:** `cggmp24 =0.7.0-alpha.2` — aux-info
  generation once per node set (persisted encrypted, reused across
  keys), threshold DKG, signing of pre-computed 32-byte digests
  (`PrehashedDataToSign`; digests come from Django's transaction
  builders whose preimages are our own constructions — the
  documented safe case). cggmp21 remains rejected at any version.
- **Ed25519:** `frost-ed25519 =3.0.0` (RFC 9591) — DKG
  (part1/part2/part3) and two-round signing of complete messages,
  aggregation by the first listed signer, in-library verification
  before any signature is returned.

## Django integration and the gate

`waas.modules.mpcsigner.client.SignerServiceClient` implements
both signing ports (`RemoteEcdsaSigner`, `RemoteEd25519Signer`)
over the coordinator API. Wallets map to signer keys per curve —
`wallet-<uuid>-ecdsa` and `wallet-<uuid>-ed25519` — because the
service stores exactly one key per key id and a wallet holds two
independent threshold keys. Error mapping is fail-closed: any
transport or service error raises the port's
`SigningUnavailable`, which the family pipelines already treat as
a clean abort (reservation released).

The operations dispatch factories return the remote signers
**only when both** `MPC_SIGNER_ENABLED=true` **and**
`MPC_SIGNER_URL` are set. Defaults are off/unset, so a stray URL
or a stray flag cannot activate signing. Tests pin all four
combinations.

## Wallet provisioning (post-roadmap, 2026-11-13)

`waas.modules.wallets.provisioning.provision_wallet` closes the
Phase 2 loop — a wallet becomes `active` only when MPC key
generation has actually completed. It is an operator action,
reachable via `POST /wallets/{id}/provision` (dashboard auth,
owner/administrator roles) or the `provision_wallet` management
command, and it runs only while the signer gate is open; with
the gate closed it refuses (HTTP 409 at the endpoint) and the
wallet remains `provisioning`.

Flow, idempotent and resumable after a partial failure:
get-or-create both threshold keys (threshold from
`MPC_SIGNER_THRESHOLD`, default 2) → derive one address per
chain family from the group public keys with each family's
canonical helper → record an address for every seeded network
through `record_derived_address` → store the opaque key ids on
the wallet, flip to `active`, audit `wallet.provisioned`. The
ceremonies run outside any database transaction; only the
address/wallet/audit writes are atomic. An active wallet with
keys but missing addresses (e.g. provisioned before the registry
was seeded) is backfilled, never re-keyed. A rehearsal driver
(`scripts/rehearse_provisioning.py`) exercises the whole flow
against real signer processes and a real backend server; the
2026-11-13 run is recorded in
`docs/operations/provisioning-rehearsal.md`.

## Verification performed (2026-11-13, this dev VM)

- Three service nodes (separate store dirs and store keys, real
  HTTP between them) executed a FROST DKG and signed with quorum
  [0,2]; the signature verifies with **ed25519-zebra**. The whole
  node set was then restarted over the same encrypted stores and
  signed again — persistence proven at service level.
- The same three-node setup executed an ECDSA DKG (incl. aux
  generation) and signed the Phase 4 Sepolia sighash; **ecrecover
  returns the group key's EVM address** (k256 cross-check). The
  first run of this test caught a real transport bug: signing
  sessions must translate between keygen party indices and
  session indices (a [0,2] quorum is session parties 0 and 1) —
  fixed in the delivery layer and re-verified; a signature from
  the persisted stores was additionally verified with Python's
  `cryptography` library. The first full-workspace run also
  caught the two service tests colliding on hardcoded ports
  when run in parallel — the tests now use disjoint port sets.
- Store unit tests: round-trip, wrong-key failure, ciphertext
  tamper failure, key-id validation.
- Django: 9 client/gate tests (MockTransport contract + the four
  gate combinations); full backend suite green.
- NOT verified: multi-host deployment (nodes here share one
  machine and loopback networking), TLS/mTLS transport, behaviour
  under node failure mid-ceremony beyond protocol aborts, and —
  decisively — independent review of any of it.

## Known limitations (for the reviewers' scope)

- **Authentication is bearer-token, not mTLS.** The cluster/API
  tokens are a development-grade control; the production
  deployment must terminate node-to-node traffic over mTLS (or a
  WireGuard-style mesh) — tracked in the deployment runbooks and
  the readiness checklist.
- **cggmp24 has no key refresh** (alpha limitation recorded in
  Phase 3); the compensating control remains re-key + migrate,
  and the rotation decision is still open.
- **No identifiable abort** in the pinned CGGMP line: a failed
  ceremony aborts without attributing the faulty party; sessions
  are retryable with fresh session ids and failures surface to the
  coordinator as errors.
- **Aux generation is minutes-scale** on small hardware (safe
  primes); it happens once per node set, at first key creation.
- Session state is in-memory per node; a node restart mid-ceremony
  aborts that ceremony (safe — no partial signatures) and the
  operation can be retried.
- FROST signing broadcasts commitments to all nodes (including
  non-quorum nodes, whose inboxes buffer them unread); harmless
  but visible in the code for reviewer attention.
