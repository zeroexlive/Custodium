# Ethereum (Mainnet)

Status: Phase 0 — chain integration design.
Network id: `ethereum`. Chain id: 1. Signature: ECDSA secp256k1
via cggmp21 candidate (PENDING review, see `../mpc/`).

## 1. Identity and assets

- Native asset: ETH, 18 decimals, `asset_id: native:ethereum`.
- **USDT: contract `0xdAC17F958D2ee523a2206206994597C13D831ec7`,
  6 decimals, issuer-native Tether ERC-20.** Identity is this
  contract on this network — never the symbol `USDT`.
- Arbitrary ERC-20 tokens: registered by contract address;
  decimals read from the contract at registration and stored.

## 2. Address validation

- Form: `0x` + 40 hex characters (20 bytes).
- EIP-55 checksum: mixed-case addresses MUST have a valid
  checksum; all-lowercase / all-uppercase are accepted as
  unchecksummed but normalised to checksummed form for display
  and storage comparison.
- Reject: wrong length, non-hex, missing `0x`, zero address as
  a withdrawal/sweep destination (unless an explicit burn flow
  is ever designed — it is not in Phase 0), and contract-vs-EOA
  confusion is *not* an error: sending to contracts is allowed
  but flagged, because ERC-20 transfers to contracts that
  cannot handle them are irrecoverable.
- The same format exists on BSC; the `network` field, not the
  string, decides which chain an address is used on.

## 3. Transaction model and nonce specifics

- Account-based. Each externally-owned account has a sequential
  **nonce**; a transaction consumes exactly one nonce.
- Custodium maintains a per-address nonce manager: allocations
  are persisted before broadcast, gaps are filled or explicitly
  resolved, and a stuck low-fee transaction is handled by
  replacement (same nonce, higher fee) — never by reusing the
  nonce for a different intent.
- Typed transactions (EIP-1559 preferred): `chainId=1`,
  `maxFeePerGas`, `maxPriorityFeePerGas`, `gasLimit`, `to`,
  `value`, `data`. Legacy transactions are supported only where
  needed; chain id is always present (EIP-155 replay defence).
- The signable digest is the typed-transaction hash defined by
  the envelope type; adapters build it, signers verify the
  reconstruction (see `../mpc/signer-security.md` §3.6).

## 4. Fees and resources

- Fee asset is ETH, charged as `gasUsed × effectiveGasPrice`.
- Estimation: `eth_estimateGas` plus a buffer policy per
  operation type; ERC-20 `transfer` to a fresh holder costs more
  than to an existing holder — estimation uses the actual
  destination, not a constant.
- Fee bounds (max fee) are part of the signer intent. Base fee
  volatility means an intent carries a ceiling, not a spot
  price; broadcasts priced above the ceiling wait or fail,
  they are never signed at a higher ceiling silently.
- A wallet with tokens but no ETH cannot pay fees: the gas
  funding flow is explicit and ledger-visible.

## 5. Token parsing

- ERC-20 transfers are parsed from receipt **logs**: topic0 =
  `Transfer(address,address,uint256)` signature hash, emitter =
  the token contract (this is the asset identity check),
  `from`/`to` from topics, value from data.
- Deposits are credited from logs, not from transaction `to`
  fields: a call to a router/contract that emits a Transfer to
  a tenant address is a deposit; a plain ETH transfer to the
  contract is not a token deposit.
- Approval/permit and other events are indexed separately and
  never mistaken for transfers.
- Tokens with fee-on-transfer or rebasing behaviour break the
  "log value = credited amount" assumption: such tokens are
  onboarded only with a per-token parsing note and balance-delta
  verification, or not onboarded.

## 6. Finality and reorg handling

- Post-merge finality: blocks are justified/finalised at
  checkpoints (roughly two epochs, ~13 minutes, under normal
  conditions). Short reorgs of a few blocks are possible before
  finalisation.
- Deposit policy: `detected` at inclusion, `confirming` until
  the platform confirmation policy is met, `credited` only at
  the policy threshold aligned with finalisation for value
  tiers (higher-value deposits may require finalised status).
- Indexer tracks block hashes, not just heights: a hash change
  at a credited height on an unfinalised block triggers reorg
  handling — affected deposits revert to `confirming`/reversed
  with compensating ledger entries, and withdrawals in the
  reorged range are re-checked for inclusion.
- `finalised` block queries are used for the authoritative
  credit decision where the policy requires them.

## 7. Indexing and RPC specifics

- Sources: block stream + receipts; log filters scoped to
  registered token contracts and tenant addresses.
- RPC providers are redundant; a single provider's view is
  never the sole basis for crediting at high value tiers.
- Uncle/orphan terminology is legacy; current handling is the
  reorg procedure in §6.

## 8. Operational limits and safety defaults

- Broadcast is idempotent at the operation layer: re-submitting
  the same signed transaction returns its hash; building a
  second transaction for the same intent is refused while the
  first is pending (see the signer single-use rule).
- Mempool eviction is not failure: a transaction absent from
  mempools but with its nonce unconsumed returns to a
  re-price/re-broadcast decision under the original fee ceiling,
  with any ceiling change treated as a new intent.
- Contract destinations for native ETH: the adapter warns when
  `to` has code and no matching internal handling is known,
  because plain value transfer invokes the contract's
  receive/fallback path (or reverts).
- Withdrawal amounts are checked against both ledger balance
  and the address's on-chain state at build time; disagreement
  beyond fees halts the operation for reconciliation rather
  than broadcasting on stale assumptions.
- Test vectors are maintained for: EIP-1559 envelope hashing,
  ERC-20 log decoding with multiple transfers in one receipt,
  and checkpoint-finalised credit decisions.

## 9. Failure modes to test

Nonce gap stall; replacement-transaction fee escalation;
fee-on-transfer token miscrediting; log from an impostor
contract with the same symbol; reorg across a credited deposit;
EIP-55 checksum typo that still parses as hex; mempool eviction
mistaken for failure; ETH sent to a reverting contract fallback.
