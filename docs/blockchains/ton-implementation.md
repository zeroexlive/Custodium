# TON — Phase 8 Implementation Record

Status: **Implemented** (2026-11-12). Code:
`apps/backend/waas/modules/ton/`. Networks: `ton` + `ton-testnet`.
Wallet contracts: **V4R2** (the Phase 0 design's version pin);
signing via the shared Ed25519 port (the FROST side, still
review-gated and fail-closed in production wiring).

## 1. What was built

| Piece | Notes |
|---|---|
| `cells.py` | TON's data model from scratch: cells (≤1023 bits + ≤4 refs), Builder/Slice, representation hashing (descriptors ‖ augmented data ‖ ref depths ‖ ref hashes), BoC serialisation/parsing with CRC32C. Ordinary cells only. |
| `addresses.py` | Raw ↔ user-friendly conversion (CRC16-XMODEM verified), testnet-flag validation, masterchain destinations rejected (Phase 0 design §2). Storage/matching in raw form. |
| `wallet.py` | V4R2: code cell taken **verbatim from the official @ton/ton SDK** (see §2), data cell, StateInit, address derivation; the signed-transfer builder (wallet_id ‖ valid_until ‖ seqno ‖ op ‖ mode ‖ ^message; signature packed in front; TON signs the cell *hash*); internal-message and Jetton-transfer payload builders. |
| `provider.py` | toncenter v2 (+ v3 `transactionsByMessage` for confirmation): account state/balance, `seqno` and Jetton `get_wallet_address` get-methods (a Jetton wallet address exists only by executing the master contract — resolved once, cached in `TonJettonAccount`), transaction history, `sendBocReturnHash`. |
| `service.py` | Withdrawal pipeline with platform semantics plus TON's rules: sends serialised per wallet under the row lock, seqno always read from chain, first send carries the StateInit, the signer's key is checked against the derived contract address before signing. Jetton sends attach 0.05 TON for gas/forwarding (recorded on the transaction row). Confirmation follows the external message hash to its transaction and settles/releases from compute/action success and bounce state. |
| `indexing.py` | Per-account history polling with `lt` cursors (`TonScanCursor`) per the Phase 0 design: native deposits are value-bearing internal messages at the wallet; **Jetton deposits credit from `internal_transfer` payloads at the Jetton wallet** (sender = the owner inside the payload); notifications/excesses/own-jetton-wallet messages and anything bounced are explicitly filtered so they can never be misread as deposits. Crediting flows through the Phase 5 lifecycle (registry policy: masterchain finality). |

## 2. Differential verification against the reference SDKs

TON's construction rules are intricate enough that internal
consistency proves little, so this phase verified against the
reference implementations directly (both executed locally on
2026-11-12; npm/PyPI egress is available in this sandbox):

- **Address derivation**: for the deterministic test key
  `keyPairFromSeed(sha256("v4-treasure"))` (pubkey
  `c37aa92e…`), the published **@ton/ton** package and
  **tonsdk** both derive
  `EQDgICpEIOY6eV348OIAf8Q-spcHAt0C2qi5A4MPKP2y773N` — and so do
  we. *Note:* the expectation written in @ton/ton's own spec
  file (`EQDnBF4J…`) does **not** match what the shipped package
  derives; that upstream test is `it.skip`'d and stale. We
  follow the shipped code, not the skipped test.
- **Signed transfer**: a v4 transfer built by @ton/ton
  (seqno 7, fixed timeout, 1 TON to a fixed address) and the
  same transfer built by this module produce the **identical
  body cell hash** `8e8c73a221664830…` — signature included
  (Ed25519 is deterministic; equality proves the signing hash,
  payload layout, message serialisation and hashing all agree).
- A manual-repr hash computation independently confirms the data
  cell hash.

## 3. Verification performed (repo test suite)

Backend suite: see `AGENTS.md`. Highlights: CRC16/friendly
round-trip incl. the USDT master address; cell hash vs
hand-built representation bytes (incl. the empty cell); BoC
round-trip with refs and CRC; the §2 differential vectors;
signing-layout parse-back; pipeline vs the API double — native
round-trip where the broadcast BoC's signature **verifies over
the reconstructed signing-cell hash with the wallet key** (the
contract's own check), Jetton send addressed to the resolved
Jetton wallet with the transfer payload parsed back,
signer/rejection/dropped semantics, failed execution releasing
the reservation, blacklist refusal; deposit scanning across the
full filter matrix with replay safety.

## 4. NOT verified / deferred

- **Live toncenter / testnet round-trip**: no TON API egress
  from this sandbox (npm/PyPI are reachable; chain APIs are
  not). The backlog exit criterion is met against the API double
  plus the §2 differential proofs, not against a live network.
- **Wallet V5 (W5)**: V4R2 only, per the Phase 0 pin.
- **Bounce-completion tracking** for outbound Jetton transfers
  beyond the wallet transaction's own result, and storage-fee
  drift accounting, are Phase 12 hardening items.
- Production signing remains disabled (Phase 3 review gate);
  FROST-with-TON payload compatibility is claimed only to the
  extent of the standard-Ed25519 signature format, per the
  Phase 0 caveats (§7 of the chain design).
