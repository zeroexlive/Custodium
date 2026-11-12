# TRON

Status: Phase 0 — chain integration design.
Network id: `tron`. Signature: ECDSA secp256k1 via cggmp21
candidate (PENDING review). Virtual machine: TVM.

## 1. Identity and assets

- Native asset: TRX, 6 decimals (amounts in `sun`,
  1 TRX = 1,000,000 sun), `asset_id: native:tron`.
- **USDT: contract `TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t`,
  6 decimals, native Tether issuance as a TRC-20 token.**
  The USDT contract is also TRON's highest-volume contract;
  indexer capacity is planned around it.
- TRC-10 assets (id-based, not contract-based) exist and are a
  distinct asset type in the registry; TRC-20 is the default
  for token onboarding. Arbitrary TRC-20 tokens register by
  contract address with verified decimals.

## 2. Address validation

- User-facing form: Base58Check, 34 characters, starting with
  `T`, encoding a 21-byte payload: `0x41` prefix + 20-byte
  account hash, plus 4-byte checksum.
- Internal/hex form: `41` + 40 hex characters. Adapters convert
  deterministically between forms; ownership matching in lookup
  and indexing normalises to one form (see
  `../api/transaction-lookup.md` §5.2).
- Reject: bad Base58Check checksum, wrong prefix byte, EVM-style
  `0x` addresses (a frequent cross-chain user error), and
  contract addresses used where an account address is required
  without an explicit contract-destination flag.
- An address may not exist on-chain until activated (a first
  incoming transfer / account creation). Sending TRX to a fresh
  address activates it; the adapter surfaces "not yet activated"
  in address metadata rather than treating it as invalid.

## 3. Transaction model and ordering specifics

- Transactions reference a recent block (`ref_block_bytes`,
  `ref_block_hash`) and carry an **expiration** (typically
  minutes). An expired transaction cannot be broadcast — the
  build/sign/broadcast pipeline must complete inside the
  window, which affects MPC session timing: signing sessions
  for TRON are scheduled against expiration, and an expired
  signed transaction means a *new intent and new session*, not
  a re-sign of identical material with a bumped field.
- The signable digest is the SHA-256 of the raw transaction
  data (`raw_data` protobuf serialisation). Signers verify the
  reconstructed transaction matches the intent fields
  (contract type, parties, amount, fee limit).
- Contract types handled: `TransferContract` (TRX),
  `TransferAssetContract` (TRC-10), `TriggerSmartContract`
  (TRC-20 calls incl. `transfer(address,uint256)`).
- Multi-signature in TRON's native permission system is a
  chain feature distinct from Custodium MPC; Phase 0 uses
  ordinary owner-permission accounts controlled by the MPC key.

## 4. Fees and resources — bandwidth and energy

TRON does not use a simple gas market:

- **Bandwidth** is consumed by transaction size; accounts get a
  free daily allowance and can stake TRX for more. Insufficient
  bandwidth burns TRX.
- **Energy** is consumed by smart-contract execution (TRC-20
  transfers need energy). Obtained by staking TRX (freezing) or
  paid for by burning TRX per unit.
- TRC-20 transfers specify a `fee_limit` (in sun): the maximum
  the sender accepts for execution. **The fee limit is part of
  the signer intent's fee bounds** — an inflated fee limit is
  a real cost risk and signers check it.
- Operational model: Custodium wallets stake for resources
  where economical, and the ledger records *actual* resource
  cost (burned TRX and/or amortised stake cost per accounting
  policy) in TRX, never hidden inside the token amount.
- A USDT transfer from an address with no TRX and no staked
  resources fails; resource funding is an explicit flow, like
  gas funding on Ethereum.

## 5. Token parsing

- TRC-20 transfers: parse the `TriggerSmartContract` call for
  intent, but credit from **logs** in transaction info where
  the `Transfer` event is present, cross-checked with the
  contract result. Contract execution can fail while consuming
  fees (`OUT_OF_ENERGY`, `REVERT`, etc.): receipt result
  decides success; a failed execution is never a deposit.
- Distinguish internal transactions (contract-to-contract
  movements inside one tx) in transaction info; lookup uses
  them per `../api/transaction-lookup.md` §5.2.
- Amounts are `uint256` in the token's smallest unit (USDT: 6).

## 6. Finality and reorg handling

- DPoS: blocks every ~3 seconds by elected Super
  Representatives. A block is **solidified** when confirmed by
  a supermajority (≥ ~70%, conventionally 19 of 27 SRs), after
  which it is irreversible in normal operation.
- Deposit policy: credit on solidified blocks
  (`getsolidifiedlatestblock`-equivalent in the indexer), not
  on mere inclusion. Pre-solidification deposits show as
  `confirming`.
- Reorgs before solidification are handled by the indexer's
  hash tracking; after solidification a reorg is a chain
  incident, not a routine event, and triggers incident handling
  rather than silent reversal.

## 7. Indexing and RPC specifics

- Full-node / solidity-node APIs (HTTP/gRPC); event subscription
  or block polling scoped to the USDT contract and tenant
  addresses — TRON event volume makes unscoped scanning
  infeasible.
- Address activity APIs supplement, never replace, block-based
  indexing for crediting decisions.

## 8. Failure modes to test

Expired transaction resubmitted; `OUT_OF_ENERGY` transfer
misread as success; Base58/hex mismatch in ownership matching;
fee_limit inflated by a compromised builder (signer must
refuse); deposit credited before solidification; activation
state mishandled for a fresh address.
