# TRON — Phase 6 Implementation Record

Status: **Implemented** (2026-11-12). Code:
`apps/backend/waas/modules/tron/`. Chains: TRON mainnet + Nile
testnet (registry slugs `tron`, `tron-nile`; 19 confirmations per
the registry's solidity policy).

## 1. What was built

| Piece | Notes |
|---|---|
| `addresses.py` | Base58Check encode/decode with double-SHA256 checksum verification, `41…`-hex ↔ `T…` conversion, key→address derivation (0x41 + last 20 bytes of keccak(pubkey) — same MPC group key as EVM). Verified against the USDT pair `41a614f8…` ↔ `TR7NHqje…`. |
| `protobuf.py` | Minimal canonical protobuf encoder. Field numbers **verified against the official `tronprotocol/protocol` definitions** (fetched 2026-11-12): `Transaction.raw` ref_block_bytes=1, **ref_block_num=3**, ref_block_hash=4, expiration=8, contract=11, timestamp=14, fee_limit=18; TransferContract owner=1/to=2/amount=3 (type 1); TriggerSmartContract owner=1/contract=2/call_value=3/data=4 (type 31). |
| `transactions.py` | TRX `TransferContract` and TRC-20 `TriggerSmartContract` builders (ABI payload identical to EVM's `transfer(address,uint256)`); txID = sha256(raw protobuf); broadcast JSON assembly. Fee model: native transfers carry no fee_limit (bandwidth); TRC-20 calls carry a 15 TRX fee_limit in SUN (unused portion unconsumed). |
| `provider.py` | TronGrid-style HTTP provider: endpoint failover, `getnowblock`/`getblockbynum`/`gettransactioninfobyid`/`getaccount`/`broadcasttransaction`, duplicate-broadcast resolves to the txID (idempotent), rejections surface the node's code/message. Optional `TRON-PRO-API-KEY` header from settings. |
| `service.py` | Withdrawal pipeline with Phase 4 semantics: blacklist → reserve → build (ref block = node head, 1-hour expiry for slow MPC ceremonies) → sign via the shared signer port (digest = txID; signature r‖s‖v with v found by trial recovery against the wallet's own TRON address) → broadcast (rejection aborts + releases; unknown outcome → `dropped`, reservation HELD) → confirm (receipt SUCCESS + 19-block policy settles; failure releases). |
| `indexing.py` | TRON scanner on the Phase 5 framework: shared cursor/scanned-block/reorg walk-back and deposit lifecycle. Native deposits from successful TransferContracts in blocks; TRC-20 deposits from Transfer logs in transaction info (logs do not live in TRON blocks). `run_indexer` dispatches TRON networks here. |
| Wiring | Transaction lookup now resolves TRON withdrawals too; the reconciliation report counts settled TRON withdrawals alongside EVM ones. |

Bugs caught by tests during the build: (1) TRON hex form must be
canonical lowercase — the EVM helper returns EIP-55 mixed case,
now normalised at derivation; (2) the ledger reservation API's
real signature (scope travels as the reservation's `external_ref`,
returns `BalanceReservation`) — the TRON service initially called
it with invented kwargs; fixed to match Phase 4 exactly.

## 2. Verification performed

Backend suite: see `AGENTS.md` for the exact count. Highlights:

- **Golden protobuf bytes**: the test hand-assembles the expected
  raw transaction from the protocol field numbers (explicit tag
  bytes) and asserts byte equality with the builder, and that the
  txID is the sha256 of those bytes. This is the strongest offline
  check available for wire compatibility.
- Address vectors (USDT pair both directions, checksum rejection,
  0x4646… test key → known EVM address + TRON forms).
- Pipeline vs an in-memory TronGrid double: TRX round-trip with
  the broadcast signature **recovering to the wallet's TRON
  address**; USDT trigger-contract withdrawal (fee_limit 15 TRX);
  signer-unavailable abort + release; unknown broadcast outcome
  holds the reservation; blacklisted destination refused before
  any row exists.
- Indexing: TRX deposit credited after threshold + replay-safe;
  TRC-20 deposit from tx-info logs; reorg reverses a credited TRX
  deposit (balances zero, reconciliation balanced).

## 3. NOT verified / deferred

- **Live node interaction**: no TronGrid/Nile access from this
  sandbox (egress policy). The broadcast JSON form follows the
  documented TronGrid contract; acceptance by a live node, the
  signature recovery-id convention (plain 0/1 vs 27/28 — our
  signatures are self-consistently recoverable, and java-tron
  accepts the plain recovery id), and a funded Nile round-trip
  must be verified from an open network before testnet enablement.
  The exit criterion "testnet round-trip reconciles exactly" is
  therefore met only against the provider double.
- **Resource model**: bandwidth/energy are represented by the fee
  limit + actual `fee` recorded at confirmation; proactive
  energy/bandwidth *estimation* and delegation (freezing) are not
  implemented — TRX fees are paid from the sending wallet's own
  balance by the network.
- TRC-10 (TransferAssetContract) transfers: not supported; TRC-20
  + native cover the mandated assets.
- Production signing remains disabled (Phase 3 review gate).
