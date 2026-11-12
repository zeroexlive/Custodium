# EVM Implementation Record — Phase 4 (Ethereum & BSC)

Status: **Implemented** (2026-11-12). Code:
`apps/backend/waas/modules/evm/` plus a cross-proof in the Phase 3
evaluation harness. **No mainnet enablement**: assets keep
deposits/withdrawals disabled in the registry, and the only signer
implementation wired anywhere is fail-closed (see §3).

## 1. What was built

| Piece | File | Notes |
|---|---|---|
| RLP encode/decode | `evm/rlp.py` | Pure Python; canonical vectors incl. long strings/lists; strict canonicality checks on decode. |
| Key/address math | `evm/keys.py` | Keccak-256 (pycryptodome), address derivation from an uncompressed secp256k1 public key (EIP-55), `ecrecover` and recovery-id resolution for threshold signatures. No private-key material anywhere in the module. |
| Transactions | `evm/transactions.py` | EIP-1559 (type 2) + legacy EIP-155 builders for native and generic ERC-20/BEP-20 transfers; sighash; signed assembly from an external (r, s); tokens identified by contract address only. |
| Provider | `evm/provider.py` | JSON-RPC over httpx with ordered endpoint failover, **chain-id verification** (an endpoint serving the wrong chain fails closed), nonce/fee/gas reads, `eth_call` (incl. `balanceOf`), broadcast, receipts. RPC errors map onto a failure taxonomy: `RevertError` (with decoded `Error(string)` reason), `NonceError`, `ReplacementError`. Broadcast is idempotent (`already known` → same hash). The HTTP client ignores ambient proxy env (`trust_env=False`): chain traffic goes only to configured endpoints. |
| Chains | `evm/chains.py` | Registry slugs `ethereum` (1), `ethereum-sepolia` (11155111), `bsc` (56), `bsc-testnet` (97) bound to endpoints (`EVM_RPC_ENDPOINTS` setting, public-endpoint defaults). |
| Pipeline | `evm/service.py`, `evm/models.py` | `EvmTransaction` state machine: created → reserved → signed → broadcast → confirmed / reverted / failed / dropped. See §2. |
| Signing boundary | `evm/signing.py` | `SignerPort` protocol + `UnavailableSigner` (fail-closed). See §3. |
| Address integration | `evm/service.py` | `register_wallet_evm_addresses`: derives the EVM address from a wallet's MPC group public key and records it for all four EVM networks via the wallets module's internal service (the only legitimate way Address rows come to exist). Wallet activation semantics are unchanged. |

## 2. Withdrawal pipeline semantics

reserve → build → sign → broadcast → confirm → settle, with:

- **Idempotency everywhere**: the pipeline row is keyed by a unique
  idempotency key (re-entry returns the stored row, no repeated
  side effects); ledger reserve/settle/release calls carry derived
  idempotency keys.
- **Ledger scope**: a wallet's reservation draws on its customer
  scope (`external_customer_id`, falling back to `wallet:<id>`);
  deposits for that customer must be credited to the same scope
  (Phase 5 indexing will credit wallet-scoped accounts).
- **Blacklist**: the destination is checked against the manual
  blacklist (Phase 2) before any row or reservation is created.
- **Failure handling**:
  - insufficient funds / ledger conflict → FAILED, nothing held;
  - would-revert at gas estimation → FAILED, reservation released;
  - signing unavailable → FAILED, reservation released (today's
    production behaviour, by design);
  - definite broadcast rejection → FAILED, reservation released;
  - broadcast outcome *unknown* (provider unreachable mid-send) →
    **DROPPED, reservation deliberately NOT released**: the
    transaction may exist on-chain; the row records the tx hash for
    manual resolution. Releasing funds here could double-pay.
  - mined-but-reverted receipt → REVERTED, reservation released;
  - success → settle exactly once when the network's
    `confirmations_required` is met.
- **Nonce management**: nonce from `eth_getTransactionCount
  (pending)`; a per-wallet row lock serialises the synchronous
  pipeline. Production nonce allocation under Temporal (a dedicated
  allocator activity) remains future work — the lock is correct,
  not fast.
- **Fees**: EIP-1559 suggestion from `eth_feeHistory` (2 × latest
  base fee + median priority fee), integer wei throughout.

## 3. The signing gate has not moved

Phase 3's rule stands: production signing requires the independent
cryptographic review, which is **not commissioned**. Therefore:

- `UnavailableSigner` is the only signer implementation in the
  backend; every real withdrawal attempt aborts cleanly at the
  signing step with funds restored (covered by a test that asserts
  exactly this behaviour).
- The Phase 4 cross-proof (below) runs entirely inside the
  test-only evaluation harness with ephemeral keys — it is not
  wired into the backend, and no code path in Django can reach it.

## 4. Cross-language proof (Python construction × MPC signing)

The two halves of an EVM withdrawal were proved together:

1. The Python module builds two Sepolia transactions (native
   transfer nonce 0; ERC-20 transfer nonce 1) whose sighashes are
   pinned as test fixtures on BOTH sides
   (`test_cross_language_sighash_fixtures` in Python).
2. The Rust harness runs ONE threshold ceremony (aux + 2-of-3 DKG)
   and signs both digests via `PrehashedDataToSign` (the preimages
   — the transactions — are constructed by our own code, the
   documented safe case), then derives the group key's EVM address
   and proves `ecrecover(sighash, r, s) == group address` for both
   signatures.

Result (2026-11-12): **PASSED** —
`ecdsa_eval::tests::threshold_signatures_are_valid_evm_signatures`
in the harness suite (6/6 harness tests, full workspace 16/16).
For both transactions, the threshold signature's `ecrecover`
returns exactly the group key's EVM address: the Python-built
transactions are validly signed by the MPC wallet key.

## 5. Verification performed

- Python: full backend suite (unit vectors incl. the **EIP-155
  canonical example** — sighash and signed bytes match the EIP
  exactly; RLP vectors; generator-point and EIP-155-key addresses)
  and pipeline integration tests with provider/signer doubles:
  round-trip with ledger reconciliation (trial balance 0),
  idempotent re-entry, signing-unavailable abort, insufficient
  funds, on-chain revert, blacklist rejection, token transfer
  construction. See `AGENTS.md` for the exact counts.
- Fixes found on the way: the Phase 2 address-family map named the
  Sepolia slug `sepolia` while the registry seeds
  `ethereum-sepolia` — corrected (this would have broken address
  recording for Sepolia in production, silently for mainnet-only
  tests).

## 6. NOT verified — and why

- **Live RPC calls**: the development sandbox's egress cannot reach
  public RPC endpoints (connection timeouts to publicnode,
  rpc.sepolia.org, Cloudflare, Binance seeds — verified by direct
  attempts). The provider is covered by mock-transport tests
  (failover, wrong-chain rejection, error taxonomy, fee math,
  idempotent broadcast). A live read-only check
  (chain id / block number / `balanceOf`) must be re-run from an
  environment with open egress before any testnet enablement.
- **Funded testnet broadcast**: requires a faucet-funded Sepolia /
  BSC-testnet account; not obtainable from this environment. The
  backlog exit criterion "testnet deposit→withdraw round-trip
  reconciles exactly in the ledger" is therefore met at the level
  of: withdrawal pipeline + ledger reconciliation proven against
  doubles, and transaction validity proven by the cross-proof —
  **not** by an on-chain round trip. Deposit detection/crediting is
  Phase 5 (indexing) by design.
- **Temporal orchestration**: the pipeline is a synchronous service
  whose steps map 1:1 onto the ADR 0003 workflow activities; no
  Temporal worker is wired in this phase.
- Gas-spike repricing / replacement transactions: the provider maps
  the errors; automated replace-by-fee is not implemented.

## 7. Exit-criteria assessment (backlog, Phase 4)

- RPC provider integration + chain configuration: **done**.
- Address generation integration with MPC wallets: **done**
  (derivation + recording; activation still review-gated).
- Transaction construction, gas estimation, nonce management:
  **done** (with the nonce caveat in §2).
- Withdrawal workflow: **implemented as a service** (Temporal
  wiring outstanding); idempotent at every step.
- EVM failure handling: **done** for reverts / nonce / rejection /
  unknown-outcome; replace-by-fee outstanding.
- Testnet round-trip reconciling in the ledger: **partially** —
  see §6. No mainnet enablement: **respected**.
