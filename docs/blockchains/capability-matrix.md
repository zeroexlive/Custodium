# Blockchain Capability Matrix and Adapter Interface

Status: Phase 0 — normative design. Chains: Ethereum, BSC,
TRON, Solana, TON. Assets: native coin, USDT per chain, and
arbitrary tokens meeting the adapter's token standards.

## 1. Asset identity rule (applies everywhere)

An asset is identified by **network + contract / mint / master
address (+ program where applicable)** — **NEVER by symbol
alone**. `USDT` on five networks is five different assets with
different issuers, contracts, and decimals. Symbols are display
strings; two unrelated tokens can share a symbol, and a
malicious token can copy any symbol and name. All APIs, ledger
accounts, snapshots, and signer intents carry the full
`asset_id`, defined as a slug encoding that identity, e.g.
`usdt-ethereum`, resolved server-side to the full tuple.

### Verified USDT identities

| Network | Contract / mint / master | Decimals | Nature |
|---|---|---|---|
| Ethereum | `0xdAC17F958D2ee523a2206206994597C13D831ec7` | 6 | Issuer-native (Tether) |
| BSC | `0x55d398326f99059fF775485246999027B3197955` | 18 | Binance-Peg; NOT Tether-native — Tether does not list BSC as a native issuance network |
| TRON | `TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t` | 6 | Native issuance (TRC-20) |
| Solana | mint `Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB` | 6 | Native SPL token |
| TON | master `EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs` | 6 | Native Jetton |

The BSC row is the classic integration trap: 18 decimals (not
6) and pegged-token provenance. Any code assuming "USDT = 6
decimals" corrupts BSC amounts by 10^12. Decimals come from
the asset record, never from the symbol and never hard-coded
per symbol.

## 2. Capability matrix

| Capability | Ethereum | BSC | TRON | Solana | TON |
|---|---|---|---|---|---|
| Signature scheme | ECDSA secp256k1 | ECDSA secp256k1 | ECDSA secp256k1 | Ed25519 | Ed25519 |
| MPC candidate | cggmp21 | cggmp21 | cggmp21 | frost-ed25519 | frost-ed25519 (caveats) |
| Account model | EOA / contract | EOA / contract | Account + resources | Keypair + PDAs + token accounts | Smart-contract wallets |
| Address form | 0x hex, EIP-55 | 0x hex, EIP-55 | Base58Check `T…` | Base58 pubkey | Raw / user-friendly forms |
| Native asset | ETH | BNB | TRX | SOL | TON |
| Token standard | ERC-20 | BEP-20 | TRC-20 | SPL Token / Token-2022 | Jetton (TEP-74 style) |
| Fee payer asset | ETH | BNB | TRX (bandwidth/energy) | SOL | TON |
| Ordering primitive | Account nonce | Account nonce | Tx expiration / ref block | Recent blockhash / durable nonce | Wallet seqno + valid-until |
| Finality type | Probabilistic → finalised checkpoints | Fast blocks, validator finality | DPoS block confirmation | Optimistic → finalised slots | Shard/masterchain confirmation |
| Smart-contract dest. | Yes (care: hooks) | Yes | Yes | Program accounts | Everything is a contract |
| Mempool visibility | Public (mostly) | Public | Public | Leader-forwarded | Via external messages |
| Typical deposit credit | After finality policy | After conf. policy | After conf. policy | After finalised | After masterchain ref. |

"Caveats" for TON signing are specified in
`../mpc/protocol-evaluation.md` §4.2 and `ton.md`: Ed25519 is
necessary, not sufficient — wallet contract version decides
the signable payload.

## 3. Adapter interface

Every chain is implemented behind one adapter interface in the
indexer/signer pipeline. Business logic, ledger, and APIs never
call chain RPC directly. An adapter MUST implement:

```text
validate_address(address) -> bool + normalised form
parse_address(address) -> chain-specific components
derive_address(wallet_pubkey_material, params) -> address
get_chain_tip() -> height/slot/seqno + hash
get_transaction(hash) -> normalised tx | not_found
parse_transfers(tx) -> [Transfer{asset_id, from, to, amount}]
get_balance(address, asset_id) -> integer smallest units
estimate_fee(tx_template) -> {fee_asset, amount, bounds}
build_transfer(intent_fields) -> signable payload template
signable_hash(payload) -> digest for the MPC layer
submit(signed_tx) -> hash
confirmation_status(hash) -> {confirmations, finalised, reorged}
token_info(contract/mint/master) -> {decimals, symbol, name}
```

Contract rules for adapters:

- **Integer money only.** All amounts are integers in smallest
  units in and out. Adapters never return floats or decimal
  strings with exponents.
- **Deterministic parsing.** `parse_transfers` on the same raw
  transaction returns the same result; parsing is pure over the
  fetched transaction + token registry.
- **Token registry is explicit.** Arbitrary tokens are onboarded
  by registering their full identity tuple + decimals (verified
  against the contract/mint/master on-chain where possible).
  An unregistered token in a transaction is reported as an
  unknown-asset transfer, never guessed from its symbol.
- **Unknown / unsupported instructions fail loudly.** An adapter
  that cannot fully parse a transaction marks it
  `parse_incomplete`; consumers (credit, lookup) treat that as
  not-yet-creditable, never as zero transfers.
- **Idempotent indexing.** Adapters expose block/slot ranges so
  the indexer can re-scan after reorgs without double-crediting.

## 4. Cross-chain concerns

### 4.1 Finality and reorg policy

Each chain doc defines: what "confirmed" means, the platform
credit threshold, and what happens on reorg (deposit status
reversal, alerting, ledger compensating entries — the ledger
is double-entry and append-only, so a reversal is a new entry,
never an edit).

### 4.2 Fee handling pattern

- Estimate via adapter → fee *bounds* enter the signer intent
  (see `../mpc/signer-security.md`) → actual fee is read back
  from the confirmed transaction and posted to the ledger in
  the fee asset, which may differ from the moved asset.
- Tenants are never charged a fee denominated in an asset the
  API did not name. Fee top-up / gas-funding for token-only
  wallets (e.g. an ERC-20 wallet holding no ETH) is an explicit
  product flow, not an adapter side effect.

### 4.3 Address validation pattern

Validation is chain-specific and total: wrong checksum, wrong
prefix, wrong length, or a valid address *for a different
chain* all fail. Cross-chain lookalikes (Ethereum vs BSC share
a format) are distinguished by the `network` field everywhere;
format validity alone never implies network correctness.

### 4.4 What adapters never do

- Hold keys or shares, or sign anything. Adapters build
  payloads and parse results; the MPC signer tier signs.
- Decide policy (blacklist, limits, approvals).
- Resolve sweep destinations (that is `../api/sweep-resolver.md`
  exclusively).

## 5. Adding a chain or token

New chain: implement the full interface, write the per-chain
document in this folder's format, define finality policy, pass
reorg and parse test vectors, independent review if a new
signature scheme is involved. New token on an existing chain:
register identity tuple, verify decimals/metadata on-chain,
add parse test vectors including a same-symbol impostor token
to prove identity is not symbol-based.
