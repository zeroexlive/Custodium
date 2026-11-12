# TON (The Open Network)

Status: Phase 0 — chain integration design, with explicit
caveats. Network id: `ton`. Signature: Ed25519 — FROST
compatibility is caveated, see §7 and `../mpc/`.

## 1. Identity and assets

- Native asset: TON (Toncoin), 9 decimals (nanotons),
  `asset_id: native:ton`.
- **USDT: Jetton master
  `EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs`,
  6 decimals, native Tether Jetton.** Asset identity is the
  Jetton master contract; balances live in per-owner Jetton
  wallet contracts derived from that master (§5).
- Arbitrary Jettons: registered by master address with
  on-chain-verified metadata/decimals. A Jetton's name/symbol
  metadata is untrusted display data.

## 2. Address validation

- Two serialisations of the same 36-byte address
  (workchain id + 32-byte account id):
  - **Raw form:** `<workchain>:<64 hex>`, e.g. `0:ab12…`.
  - **User-friendly form:** Base64url, 48 characters, encoding
    flags (bounceable / non-bounceable, mainnet/testnet) plus
    a CRC16 checksum. Prefixes differ accordingly (`EQ…` /
    `UQ…` families).
- Validation: parse strictly, verify CRC for user-friendly
  form, reject testnet-flagged addresses on mainnet config,
  normalise to raw form for storage/matching and retain the
  presentation form used.
- **Bounceable flag matters operationally:** sending to a
  non-existent or erroneous contract with bounceable=true can
  return funds; non-bounceable sends to bad destinations can
  be final. The adapter records which form was used for every
  destination and defaults per product policy (wallets: the
  bounceable form for contract wallets).
- Workchain: Custodium operates on the basechain (workchain 0)
  in Phase 0; masterchain (`-1`) addresses are system addresses
  and are rejected as user destinations.

## 3. Transaction / message model and seqno specifics

- TON is an asynchronous actor system: a "transfer" is a chain
  of **messages** between contracts, not one atomic transaction.
  An external message triggers the sender wallet contract,
  which emits an internal message to the recipient (or to the
  recipient's Jetton wallet), which may emit notifications and
  bounces. Indexing follows the message graph by hash/`lt`.
- **Wallet contracts:** user funds sit in wallet contracts
  (e.g. v4/v5 families). Sending means calling the wallet with
  an external message signed by the owner's key. The signed
  payload includes:
  - **seqno** — strictly sequential per wallet contract; a
    replayed or out-of-order seqno is rejected by the contract.
    The seqno manager is therefore safety-critical: concurrent
    sends from one wallet must be serialised, and a lost
    transaction's seqno state must be reconciled from chain
    before the next send (never guessed).
  - **valid-until timestamp** — expired external messages are
    rejected; MPC signing latency is budgeted against it,
    as with Solana blockhash / TRON expiration.
  - subwallet id and the internal message(s) to send.
- The signable data is the hash of a constructed **cell**
  (TON's data structure), built per the exact wallet contract
  version. Changing wallet version changes the payload format
  — adapters version this explicitly.
- `sendmode` flags (pay fees separately, ignore errors, etc.)
  are part of the built message and of signer intent checking;
  dangerous modes (e.g. carry-all-balance, destroy-if-empty)
  are never set by Custodium-built transfers.

## 4. Fees and resources

- Fees are paid in TON and comprise storage fees, computation
  (gas) fees, and forward fees for messages, deducted along the
  message chain. The amount *delivered* can be less than the
  amount *sent* if fees are taken from the transferred value
  (sendmode-dependent) — the adapter and API state amounts with
  this in mind: "value attached" vs "value credited" are
  distinct fields for TON.
- Jetton transfers require attaching enough TON to the internal
  message to cover the recipient-side Jetton wallet gas and the
  forward notification; under-funded transfers bounce or strand.
  Fee estimation is per-operation and part of signer fee bounds.
- A new Jetton wallet deployment costs TON; first receipt of a
  Jetton by a fresh owner deploys their Jetton wallet contract.

## 5. Token (Jetton) parsing

- There is no global token account: each (master, owner) pair
  has a **Jetton wallet contract** whose address is derived
  from the master and owner. Deposits of USDT arrive at the
  wallet's Jetton wallet, as internal messages with the Jetton
  `internal_transfer` opcode, followed by a
  `transfer_notification` to the owner wallet carrying sender
  and amount.
- Parsing rules: credit from validated Jetton-wallet messages
  for the registered master, amount from the message payload,
  sender identified by the *owner* behind the source Jetton
  wallet (resolved via the message fields), per
  `../api/transaction-lookup.md` §5.4.
- Excess TON attached to a Jetton transfer returns to the
  sender as an `excesses` message — indexers must not mistake
  excess/forward messages for transfers.
- Bounced transfers restore the sender's Jetton balance: a
  transfer later bounced is not a completed deposit/withdrawal;
  status tracking follows the message chain to its end state.

## 6. Finality and reorg handling

- TON finality: a shardchain block is final for practical
  purposes once referenced by a masterchain block; masterchain
  blocks are produced by the validator set with BFT-style
  consensus. Deposit policy: credit after the deposit's
  shard block is referenced in the masterchain, plus the
  message chain reaching a terminal (non-bounced) state.
- Shard splits/merges and out-of-order message delivery are
  normal TON behaviour, not anomalies: the indexer is built
  around logical time (`lt`) and message hashes rather than
  assuming total ordering.
- Because delivery is asynchronous, a TON deposit has a longer
  honest "in flight" state than account-chain deposits; API
  statuses expose this rather than forcing TON into an
  EVM-shaped status machine.

## 7. MPC / Ed25519 compatibility caveats

- TON wallet contracts verify Ed25519 signatures, so
  frost-ed25519 output is the right *family* — but the signed
  object is a wallet-version-specific cell hash including
  seqno/valid-until, and aggregate-signature verification must
  be tested against the specific wallet contract version.
- No TON signing is claimed until: the adapter's payload
  construction, FROST aggregation, and the target wallet
  contract version pass testnet end-to-end tests and the
  independent review in `../mpc/protocol-evaluation.md`.
- If the reviewed FROST path cannot serve a chosen wallet
  contract version, the fallback is a different wallet contract
  version — never a single-key wallet presented as MPC.

## 8. Failure modes to test

Seqno desync after a dropped external message; valid-until
expiry during signing; bounceable/non-bounceable mix-up;
Jetton excess message misread as a transfer; bounced deposit
credited prematurely; user-friendly address with valid CRC
but testnet flag on mainnet; under-funded Jetton forward fees.
