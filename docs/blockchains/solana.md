# Solana

Status: Phase 0 — chain integration design.
Network id: `solana`. Cluster: mainnet-beta. Signature:
Ed25519 via frost-ed25519 candidate (PENDING review).

## 1. Identity and assets

- Native asset: SOL, 9 decimals (lamports), `asset_id:
  native:solana`.
- **USDT: mint `Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB`,
  6 decimals, native SPL token issued by Tether.** Asset
  identity is the mint; the SPL Token program
  (`TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA`) is part of
  the parsing context. Token-2022 (Token Extensions) mints are
  a distinct program context and are registered as such.
- Arbitrary SPL tokens: registered by mint address; decimals
  from the mint account, verified at registration.

## 2. Address validation

- Wallet addresses are Base58 encodings of 32-byte Ed25519
  public keys (32–44 characters in practice).
- Validation: Base58-decodable to exactly 32 bytes. There is no
  checksum — a mistyped address is usually still well-formed,
  so UI/API confirmation of destination is more important here
  than format checks alone.
- **Token accounts are not wallet addresses.** An SPL token is
  held in an Associated Token Account (ATA) — a program-derived
  address computed from owner + mint + token program. APIs
  accept and return the *owner* wallet address plus mint; the
  adapter derives the ATA. Accepting a raw token account
  address where an owner is expected is a classic bug source
  and is validated against (lookup attribution also resolves
  token account → owner, see `../api/transaction-lookup.md`).
- PDAs are off-curve addresses with no private key: they can
  receive funds but can never be Custodium MPC wallets. The
  adapter distinguishes on-curve (signable) from PDA addresses.

## 3. Transaction model and blockhash specifics

- Transactions are atomic bundles of instructions across
  programs, signed by one or more keypairs; fee payer is the
  first signer. Custodium wallet transactions are built with
  the wallet as fee payer unless an explicit fee-payer design
  says otherwise.
- **Recent blockhash:** every transaction includes a recent
  blockhash and is valid only while that blockhash is recent
  (roughly 150 slots). The build → MPC-sign → broadcast
  pipeline must fit in that window; a lapsed blockhash means
  rebuilding with a fresh blockhash and a **new signing
  session** (signatures do not transfer across blockhashes).
- **Durable nonces** are the alternative for offline/delayed
  signing flows; Phase 0 defaults to recent blockhash with
  pipeline timing engineered around it, and durable nonce
  accounts are an explicitly separate design if adopted.
- Address Lookup Tables (v0 transactions) may be used for
  multi-instruction transfers; adapters must resolve ALT-
  referenced accounts before parsing or signing verification.
- Compute budget: instructions declare/request compute units
  and optionally a priority fee (price per compute unit). The
  requested compute-unit price is part of fee bounds in the
  signer intent.

## 4. Fees and resources

- Fee: base fee per signature (historically 5,000 lamports per
  signature) plus optional prioritisation fees
  (compute-unit price × units). Fee asset is SOL.
- **Rent:** accounts must hold a rent-exempt minimum; creating
  an ATA costs the payer a rent-exempt deposit in SOL
  (recoverable on close). First-deposit flows for a new mint
  therefore carry a SOL cost the tenant must see in estimates.
- A wallet holding USDT but no SOL cannot transact: SOL funding
  for fees/rent is an explicit, ledger-visible flow.

## 5. Token parsing

- Parse the transaction's instructions **and inner
  instructions**: SPL `Transfer` / `TransferChecked` may appear
  as inner instructions under another program's call.
- Cross-check with `meta.preTokenBalances` /
  `postTokenBalances` (by account index + mint + owner): the
  balance delta for the tenant's token accounts is the
  creditable amount; instruction-level parsing alone can be
  fooled by failed or nested calls.
- `meta.err != null` ⇒ the transaction failed ⇒ no transfers
  happened, regardless of what instructions were attempted.
- `TransferChecked` (with mint + decimals in the instruction)
  is preferred for Custodium-built transfers; parsing handles
  both checked and unchecked forms.
- Token-2022 extensions (transfer fees etc.) change net
  received amounts: a mint with a transfer-fee extension is
  credited by balance delta, never by instruction amount, and
  is onboarded with that note or not at all.

## 6. Finality and reorg handling

- Commitment levels: `processed` < `confirmed` (optimistically
  confirmed by supermajority vote) < `finalized` (rooted,
  ~31+ slots behind tip under normal operation).
- Deposit policy: credit at `finalized` for standard tiers;
  display `confirming` at `confirmed`. Forks can drop
  `processed`/`confirmed` transactions; finalised slots are
  not reverted in normal operation.
- Indexer keys on slots + blockhashes and re-checks inclusion
  after slot skips; skipped slots are normal and must not be
  treated as gaps in transaction history.

## 7. Indexing and RPC specifics

- Account subscription / block streaming for the token program
  filtered to tenant ATAs, plus signature history per ATA.
- Solana RPC rate limits are a real capacity constraint:
  batching, dedicated endpoints, and webhook-style ingestion
  (where the provider supports it) are part of the design.
- Historical parsing requires `maxSupportedTransactionVersion`
  awareness (v0 vs legacy) in RPC calls.

## 8. Failure modes to test

Blockhash expiry during MPC signing; failed transaction with
plausible-looking instructions; inner-instruction transfer
missed; ATA-vs-owner confusion; Token-2022 transfer fee
miscrediting; SOL-less wallet attempting a USDT send.
