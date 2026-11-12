# Indexing Strategy — Custodium Database & Chain Indexing

| Field | Value |
|---|---|
| Phase | Phase 0 design |
| Status | Planned |
| Scope | (A) PostgreSQL indexes for API/ledger workloads; (B) blockchain indexing (scanning) design. Both are “indexing”; this doc keeps them distinct. |

## Part A — Database indexes

## A1. Principles
- Index the queries the product actually makes: tx-hash lookup, address
  history, tenant-scoped lists, ledger derivation, outbox/webhook polling,
  checkpoint reads. No speculative indexes on money tables without a query.
- Tenant-scoped indexes lead with the scope columns (organization/project)
  so isolation and selectivity align.
- Every unique business rule in `erd.md` §5 is a unique index, not app hope.
- Write cost matters on JournalLine / BlockchainTransfer / audit tables:
  each added index is justified in review with the query it serves.

## A2. Lookup: transaction hash
Primary pattern: “show me this transaction” from console, API, support.
```sql
CREATE UNIQUE INDEX ux_bctx_network_txhash
  ON blockchain_transaction (network_id, tx_hash);
CREATE INDEX ix_bctransfer_tx
  ON blockchain_transfer (blockchain_transaction_id, transfer_index);
CREATE UNIQUE INDEX ux_bctransfer_tx_index
  ON blockchain_transfer (blockchain_transaction_id, transfer_index);
```
- Tx hash stored in canonical form per network (e.g. EVM hex lowercased,
  with/without `0x` normalised at ingestion and at query time by the same
  function). Index alone cannot fix inconsistent normalisation.
- TRON/Solana/TON hash encodings are normalised per adapter contract in
  `chains/base` before storage.

## A3. Lookup: address history
Primary patterns: deposits to an address, all transfers involving an
address, operations touching an address, newest-first pagination.
```sql
CREATE UNIQUE INDEX ux_walletaddress_network_address
  ON wallet_address (network_id, address);
CREATE INDEX ix_txaddrrel_address_tx
  ON transaction_address_relation (wallet_address_id, blockchain_transaction_id DESC);
CREATE INDEX ix_bctransfer_to_from
  ON blockchain_transfer (to_address, blockchain_transaction_id DESC);
CREATE INDEX ix_bctransfer_from
  ON blockchain_transfer (from_address, blockchain_transaction_id DESC);
CREATE INDEX ix_deposit_address_status
  ON deposit (wallet_address_id, status, id DESC);
```
- Address strings stored in canonical per-network form (EVM checksum vs
  lower rule, TRON base58, Solana base58, TON friendly/raw mapping) —
  decided per adapter, applied at write AND lookup through one helper.
- `TransactionAddressRelation` is the indexed join path for known addresses;
  from/to text indexes serve explorer-style lookups for external addresses.
- Pagination is keyset (`id < cursor`) on history endpoints; OFFSET on
  transfer/deposit history is forbidden in new endpoints.

## A4. Tenant-scoped list indexes
```sql
-- pattern, applied per tenant table:
CREATE INDEX ix_wallet_project_status ON wallet (project_id, status, id DESC);
CREATE INDEX ix_custodyop_project_type_status
  ON custody_operation (project_id, type, status, id DESC);
CREATE INDEX ix_apikey_project_status ON api_key (project_id, status);
CREATE INDEX ix_audit_org_created ON security_audit_event (organization_id, created_at DESC);
CREATE INDEX ix_webhookendpoint_project ON webhook_endpoint (project_id, active);
```
- API list endpoints must filter by project/org from the principal — an
  index without the scope filter in the query is a review failure, because
  it risks both performance and tenant isolation mistakes.

## A5. Ledger indexes
```sql
CREATE INDEX ix_journalline_account_entry
  ON journal_line (ledger_account_id, journal_entry_id);
CREATE INDEX ix_journalentry_project_asset_posted
  ON journal_entry (project_id, asset_id, posted_at DESC);
CREATE UNIQUE INDEX ux_journalentry_idempotency
  ON journal_entry (idempotency_key);
CREATE INDEX ix_journalentry_operation
  ON journal_entry (custody_operation_id);
CREATE INDEX ix_reservation_account_status
  ON balance_reservation (ledger_account_id, status);
```
- Derived balance query groups by account over lines; for high-volume
  accounts a rebuilt-from-lines projection table (account, derived balance,
  last journal id) may be added later — projection lag must be observable,
  and the projection is never queried for posting decisions without the
  account-row lock + line check defined in the ledger design.
- Journal tables are append-only and grow monotonically: plan partitioning
  by posted_at month/range when volume justifies it; indexes above are
  partition-compatible (leading columns retained).

## A6. Queue / polling indexes (partial indexes)
```sql
CREATE INDEX ix_outbox_unpublished
  ON outbox_event (created_at) WHERE published_at IS NULL;
CREATE INDEX ix_webhookdelivery_due
  ON webhook_delivery (next_retry_at) WHERE status IN ('pending','retrying');
CREATE INDEX ix_indexingcheckpoint_network
  ON indexing_checkpoint (network_id);
CREATE INDEX ix_signingsession_expiry
  ON signing_session (expires_at) WHERE status IN ('open','pending');
```
- Partial indexes keep worker polling cheap as history grows.
- Workers claim rows with `FOR UPDATE SKIP LOCKED`; indexes support the
  claim query's WHERE + ORDER BY exactly.

## A7. Other required indexes
| Table | Index | Serves |
|---|---|---|
| membership | unique (user_id, organization_id) | Membership integrity |
| api_key | unique (key_id) | HMAC auth lookup per request |
| asset | unique (network_id, contract_or_mint) where token; unique (network_id) where native | Token registration |
| blacklist_entry | (network_id, address, active) | Pre-signing blacklist check (hot path) |
| signing_policy | unique (project_id, version) | Policy binding |
| withdrawal_approval | unique (withdrawal_id, approver_user_id) | Approval integrity |
| balance_reservation | (custody_operation_id) | Operation → reservation trace |
| reconciliation_run | (project_id, network_id, started_at DESC) | Run history |
| api_usage_record | (api_key_id, window_start) | Metering aggregation |
| resolved_destination_snapshot | (sweep_job_id) | Sweep audit trace |
| sweep_job | (project via treasury op, status, id DESC) pattern via custody_operation | Sweep lists |

## A8. Anti-patterns (forbidden)
- Indexing JSON payload columns as a substitute for relational columns on
  tx hash, address, amount, status or tenant scope.
- `LIKE '%hash%'` / substring searches on tx hashes or addresses.
- Full-table balance scans per API request.
- Adding indexes to “fix” a query that lacks tenant scoping.
- Float columns with indexes for amount range queries — amounts are ints;
  range queries use integer comparisons.

## A9. Verification
- Each Phase-1+ migration PR includes `EXPLAIN (ANALYZE, BUFFERS)` evidence
  for the hot queries it touches, on a seeded dataset, in the PR description.
- A slow-query log review is part of staging readiness (not a prod claim).

## Part B — Blockchain indexing (scanning)

## B1. Model
- One scanner family per chain type: EVM (ETH+BSC), TRON, Solana, TON.
- Scanners consume RPC via `integrations/rpc_providers` through `chains/*`
  adapters and write observations + `IndexingCheckpoint` atomically per batch.
- Checkpoint = (network, scope, cursor, block hash at cursor). Reorg
  detection compares stored hash with the chain's hash at that height.

## B2. Scanning rules
- Scan in bounded ranges; confirm the range fully before advancing.
- Filter early by known WalletAddress set (loaded incrementally), but record
  transfers via TransactionAddressRelation so late-registered addresses can
  be backfilled for their history window per product policy.
- Token transfers (ERC-20/TRC-20/SPL/jetton) and native transfers are both
  normalised to BlockchainTransfer with transfer_index ordering within a tx.
- Mempool/pending observations, if used, are marked unconfirmed and can
  never credit a deposit.

## B3. Finality per network (policy, not assumption)
| Network | Confirmation basis | Notes |
|---|---|---|
| Ethereum | Block confirmations + reorg depth policy | Configurable per asset value tier if required |
| BSC | Block confirmations, shorter cadence | Faster blocks ≠ instant finality |
| TRON | Solidified blocks | Use solidity status, not latest block |
| Solana | Commitment level (confirmed/finalized) | Credit only at configured commitment, default finalized for value |
| TON | Masterchain/block confirmation semantics | Message-based; validate via adapter-specific rules |

Exact numbers are network configuration (`confirmation_policy`), reviewed
per network before any mainnet use — they are not asserted here.

## B4. Reorgs and gaps
- On hash mismatch at/below checkpoint: mark affected observations reorged,
  rewind checkpoint to the common ancestor, rescan. Deposits already credited
  follow INV-DEP-05 (reversal + alert).
- On scanner downtime: resume from checkpoint, backfill the gap range;
  lag is a metric/alert (scanner lag per network).
- On RPC provider disagreement: prefer the configured quorum/majority of
  endpoints for crediting decisions; log provider divergence.

## B5. Performance and rate limits
- Batch RPC calls where the provider supports it; respect per-endpoint rate
  limits with backoff — a 429 from a provider is a hard stop for that
  endpoint's burst, not a retry storm.
- Address-set membership checks are in-memory Bloom/set + DB verification,
  so scanning cost does not grow linearly with tenant count per block.
- Scanner workers scale per network family independently (deployment doc).

## B6. Observability
- Metrics: head lag (blocks/slots/seconds) per network, transfers/min,
  reorg count, checkpoint age, RPC error rate per endpoint.
- Every transfer record retains: network, tx hash, transfer index, block
  reference, observed_at, endpoint id — enough to replay indexing decisions.
