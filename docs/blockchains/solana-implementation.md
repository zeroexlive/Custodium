# Solana — Phase 7 Implementation Record

Status: **Implemented** (2026-11-12). Code:
`apps/backend/waas/modules/solana/`. Networks: `solana` +
`solana-devnet` (registry policy: 32-slot finality).

## 1. What was built

| Piece | Notes |
|---|---|
| `base58.py` / `keys.py` | Address = base58(Ed25519 group key). **ATA derivation**: PDA of the Associated Token Program with an Ed25519 on-curve test implemented from the curve equation (exact edge cases tested: base point, the (0,−1) point with both sign bits, y ≥ p). |
| `signing.py` | The Ed25519 signer port (whole-message signatures — no digest, no recovery id). Only wired implementation is fail-closed (`UnavailableEd25519Signer`) until the Phase 3 FROST signer passes the independent review; derivation/indexing/deposits work without it. FROST usage stays inside its evaluated ciphersuite (Ed25519/SHA-512, the Phase 3 pin) — no other curve or hash is introduced. |
| `transactions.py` | Legacy message compiler (shortvec, account-key dedup/ordering, header derivation) + SystemProgram transfer, SPL **TransferChecked**, and ATA **create-idempotent** instructions. Versioned/ALT transactions deliberately not used. Compiled messages are parsed back byte-by-byte in tests, and test signatures over them verify with a standard Ed25519 implementation. |
| `provider.py` | JSON-RPC client with failover: getSlot (finalized), getLatestBlockhash, getBlock (jsonParsed), getSignatureStatuses, sendTransaction (base64). |
| `service.py` | Withdrawal pipeline with the platform semantics. SPL withdrawals prepend the idempotent ATA creation for the destination (rent ~0.002 SOL paid by the wallet as fee payer, accounted at confirmation — never hidden) and move funds ATA→ATA with TransferChecked (mint + decimals pinned in the instruction). |
| `indexing.py` | Slot scanner on the Phase 5 framework using the **balance-delta model** (Phase 0 design §5.3): SOL from pre/post balances, SPL from pre/post token balances attributed by token-account **owner**. Skipped slots advance the cursor without blocks; reorg walk-back anchors on real blocks only. `run_indexer` dispatches Solana networks here. |
| Wiring | Lookup resolves Solana withdrawals and no longer lowercases hashes for base58 families (that would corrupt them); reconciliation counts settled Solana withdrawals. |

## 2. Cross-family bug found by the Solana tests (fixed for all)

`indexing.services._record_deposit` lowercased `tx_hash`,
`block_hash`, and `from_address` before storing. Correct for hex
families, **corrupting for base58**: a Solana deposit's block hash
was stored folded, so the reorg walk-back (comparing against the
true blockhash) found the orphaned block but matched **zero**
deposits to reverse — a silent failure the reorg test caught.
Fix: `_record_deposit` stores exactly what the family scanner
passes; hex scanners canonicalise at their call sites. Two more
falsy-value bugs fixed in passing: Solana slot 0 collapsing to
None in confirmation (`int(...) or None`), caught by the
round-trip test.

## 3. Verification performed

Backend suite: see `AGENTS.md`. Highlights: shortvec/base58
vectors incl. the SystemProgram all-zero address; on-curve edge
cases above; ATA determinism + off-curve + owner/mint sensitivity;
message compilation parsed back with exact header/key/instruction
assertions for SOL and SPL transfers; **Ed25519 verification of
the pipeline's wire transaction** against the wallet key; SOL and
SPL withdrawal round-trips; signer-unavailable/rejected/dropped
semantics; blacklist refusal; deposit detection for SOL deltas and
owner-attributed SPL deltas (with a same-tx other-owner control);
failed-transaction exclusion; skipped slots; reorg reversal.

## 4. NOT verified / deferred

- **Live RPC / devnet round-trip**: no Solana RPC egress from
  this sandbox. The backlog exit criterion (testnet SOL + SPL
  round-trip reconciling exactly) is met against the RPC double
  only; the ATA derivation and message format, while built to the
  protocol rules and property-tested, have not been accepted by a
  live cluster yet.
- **Token-2022** (transfer fees / extensions): classic SPL only.
- **Priority fees**: a base fee model only; compute-unit price
  markets are a Phase 12 tuning item.
- Deposit sender attribution is the fee payer (exact for direct
  transfers; documented approximation of the delta model for
  program-mediated transfers, per the Phase 0 design).
- Production signing remains disabled (Phase 3 review gate).
