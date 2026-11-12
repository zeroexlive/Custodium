# BNB Smart Chain (BSC)

Status: Phase 0 — chain integration design.
Network id: `bsc`. Chain id: 56. Signature: ECDSA secp256k1
via cggmp21 candidate (PENDING review).

## 1. Identity and assets

- Native asset: BNB, 18 decimals, `asset_id: native:bsc`.
- **USDT: contract `0x55d398326f99059fF775485246999027B3197955`,
  18 decimals. This is Binance-Peg USDT, NOT Tether-native
  issuance — Tether does not list BSC among its native
  networks.** Provenance matters for risk disclosures, and the
  **18 decimals** (vs 6 on Ethereum/TRON/Solana/TON) matter for
  every amount calculation. Code that assumes USDT has 6
  decimals is catastrophically wrong here.
- Arbitrary BEP-20 tokens: registered by contract address with
  on-chain-verified decimals, exactly as ERC-20 on Ethereum.

## 2. Address validation

- Identical format to Ethereum: `0x` + 40 hex, EIP-55 checksum
  rules identical. Validation, normalisation, zero-address
  handling: see `ethereum.md` §2, applied unchanged.
- Because the format is shared with Ethereum, the most likely
  user error is *network* confusion (an address is fine, the
  selected network is wrong). APIs require `network` explicitly
  and never infer BSC vs Ethereum from an address string.
- A deposit sent on the wrong EVM network is not visible to
  this adapter at all; support flows treat cross-network sends
  as external-chain problems, not as pending BSC deposits.

## 3. Transaction model and nonce specifics

- Account-based, sequential per-account **nonce**, EVM
  semantics shared with Ethereum: persisted nonce allocation,
  gap handling, same-nonce replacement for stuck transactions.
- Transactions include `chainId=56` (EIP-155). Legacy and
  EIP-1559-style fee fields follow what the BSC client set in
  use actually supports at integration time; the adapter
  isolates this so business logic sees only fee bounds.
- Signable digest construction is the EVM typed/legacy hash as
  on Ethereum, with BSC's chain id — adapters must not reuse an
  Ethereum-built payload on BSC (chain id binds it, and signer
  verification checks it).

## 4. Fees and resources

- Fee asset is BNB: `gasUsed × gasPrice` (BSC historically uses
  a gas-price model with low, relatively stable prices rather
  than Ethereum's EIP-1559 base-fee market; the adapter reads
  current network parameters instead of assuming Ethereum's
  fee market).
- Blocks are fast (~sub-second to a few seconds historically,
  with validator-set changes affecting cadence). Fee estimation
  still uses per-destination estimation for token transfers.
- Fee bounds enter the signer intent as on Ethereum; unusually
  cheap fees do not relax any check.

## 5. Token parsing

- BEP-20 is ERC-20-compatible: parse receipt logs for
  `Transfer` events emitted by the registered contract;
  emitter address is the asset identity; see `ethereum.md` §5
  in full, including impostor contracts and fee-on-transfer
  cautions.
- BSC has a high population of clone/impostor tokens using the
  `USDT` symbol and name: the contract-address check in log
  parsing is the only defence, and the token registry must
  never auto-register a token because its symbol matches.
- Bridge-related mint/burn events for pegged assets are parsed
  distinctly from ordinary transfers where they affect supply
  interpretation, but a user deposit is still credited from
  the Transfer to the tenant address.

## 6. Finality and reorg handling

- BSC uses a validator-based consensus (Proof of Staked
  Authority lineage, with later upgrades). Blocks arrive fast;
  finality is reached after confirmation by a supermajority
  pattern of validators — in practice the platform policy uses
  a confirmation count calibrated to BSC's validator finality
  (historically ~15 blocks for strong assurance) rather than
  Ethereum's checkpoint model.
- Short reorgs are possible. The indexer is hash-aware:
  reorged deposits revert with compensating ledger entries,
  per the common procedure in `capability-matrix.md` §4.1.
- Because blocks are fast, confirmation *count* is reached
  quickly in wall-clock time; policy must not translate
  Ethereum's time-based intuition to BSC — use BSC's own
  finality analysis, reviewed at integration.

## 7. Indexing and RPC specifics

- Block + receipt + log indexing as on Ethereum, with BSC
  RPC endpoints (public endpoints are rate-limited and are not
  a production indexing plan; dedicated endpoints required).
- Higher block rate means larger log volumes: filters stay
  scoped to registered contracts and tenant addresses.

## 8. Operational limits and safety defaults

- Amount handling is regression-tested at the asset-record
  level: every BSC USDT code path (deposit credit, withdrawal
  build, sweep, lookup response, ledger posting) has a test
  asserting 18-decimal scaling, so a shared "USDT helper" that
  assumes 6 decimals fails CI instead of corrupting funds.
- Peg-provenance disclosure: tenant-facing material for BSC
  USDT describes it as Binance-Peg, and risk/policy documents
  do not present it as direct Tether issuance or as redeemable
  with Tether by virtue of holding it on BSC.
- Cross-chain address reuse: a tenant may legitimately use the
  same EVM address on Ethereum and BSC (same MPC key family);
  ledger, indexing, and nonce state are nevertheless kept
  strictly per-network — a nonce or balance from one EVM chain
  must never be read as belonging to the other.
- Fast blocks make "wait N minutes" policies meaningless; all
  BSC policies are expressed in confirmation counts / finality
  terms (see §6), and dashboards show both count and finality
  state rather than an Ethereum-style time estimate.
- Public RPC endpoints are for development only; production
  indexing and broadcast use dedicated endpoints with the
  redundancy rule from `ethereum.md` §7.

## 9. Failure modes to test

6-vs-18-decimal amount corruption (the headline BSC bug);
impostor USDT contract deposit; Ethereum/BSC network mix-up;
stuck transaction replacement; reorg at fast block cadence;
token registered with symbol-only matching (must be rejected
in review/tests); per-network nonce/balance leakage between
Ethereum and BSC for a shared address.
