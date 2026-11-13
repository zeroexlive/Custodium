# Provisioning Rehearsal — Runbook & Record

How to rehearse the full wallet-provisioning flow end to end on
one machine, and the record of the first run (2026-11-13).

**What this is:** a software rehearsal with throwaway state and
test keys on a single host. **What it is not:** a production
deployment, a key ceremony, or evidence toward Production
Approval — the independent cryptographic review remains the
gate for enabling the signer in any real environment.

## Run it

Prerequisites: the signer binary built
(`cargo build -p custodium-signer-service` in `services/mpc/`) and the
backend venv installed (`uv sync` in `apps/backend/`).

```bash
# from the repository root
apps/backend/.venv/bin/python scripts/rehearse_provisioning.py
```

The driver (`scripts/rehearse_provisioning.py`):

1. starts three `custodium-signer` processes with distinct
   store directories and store keys on loopback ports
   18611–18613,
2. starts the Django backend (development settings, a SQLite
   file inside the rehearsal dir) with the signer gate open
   **for this run only**, migrates, and seeds the network
   registry,
3. drives the public API: register → organization → project →
   wallet → `POST /wallets/{id}/provision` (both DKGs run for
   real; expect several minutes, dominated by the ECDSA
   aux-info generation),
4. verifies the recorded addresses against the signer-reported
   group public keys **independently of the backend's helpers**
   (EVM: keccak + EIP-55 in the driver; TRON: Base58Check;
   Solana: base58; TON: raw-form shape — its derivation was
   differentially verified against @ton/ton in Phase 8),
5. proves the binding between provisioning and signing through
   the real dispatch factories in a backend shell: an ECDSA
   threshold signature whose recovered address equals the
   wallet's EVM address, and an Ed25519 (FROST) signature
   verified against the group key,
6. writes `rehearsal-record.json` into the run directory
   (`~/custodium-rehearsal/run-<UTC timestamp>/`) and tears
   every process down.

## Record — 2026-11-13 run (dev VM, debug signer build)

- Run dir: `~/custodium-rehearsal/run-20261113T064428Z/`
  (ephemeral to the dev VM; the facts below are the record).
- 3 signer nodes healthy; backend healthy; wallet
  `5635bc85-fe2b-4880-a8c9-ca01b23d63a2` created in
  `provisioning`, provisioned in **204.7 s** (FROST DKG + ECDSA
  aux/DKG), status `active`, key refs
  `wallet-…-ecdsa` / `wallet-…-ed25519`.
- 10 addresses recorded (one per seeded network); families:
  EVM/BSC `0x5fca24b7822778Dca3ede2ad4009CE59D5822576`,
  TRON `TJhhMTJW1nVR3dasvgcAM6yjvyBQCqwm15`,
  Solana `551fPXUoFtXJ56edFZ5B1YPfmWTr1uYXz2f7vPo4C7cW`,
  TON `0:95c8af5fe5c8ca1f171901838266739b6ae2dd8b3d3b85c8e59339764a8913f0`.
- Independent address verification passed (EVM/TRON/Solana
  recomputed in the driver; TON shape-checked).
- Backend-initiated signing passed: ECDSA signature recovered
  to the wallet's EVM address; Ed25519 signature verified with
  `cryptography` against the FROST group key.
- Teardown confirmed: no signer or backend processes remained.

Not covered by this rehearsal: multi-host deployment, TLS/mTLS
between nodes, live chain interaction of any kind, performance
under load, and node failure mid-ceremony.
