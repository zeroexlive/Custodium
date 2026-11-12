# Entity-Relationship Diagram — Custodium Database

| Field | Value |
|---|---|
| Phase | Phase 0 design |
| Status | Planned — schema design, not a migration |
| Engine | PostgreSQL |
| Conventions | `bigint` PKs or UUIDv7 (choose per table family, consistently); `created_at/updated_at timestamptz`; money = integer base units; tenant rows carry `organization_id` and/or `project_id` |

## 1. Reading notes
- The Mermaid ERD below is the logical model. Physical details (indexes,
  constraints) are summarised in §3–§5 and in `indexing-strategy.md`.
- Cardinality in Mermaid is indicative; the text table in §3 is normative
  for ownership and delete behaviour (almost everything is soft-restricted:
  financial/audit rows are never hard-deleted).
- KeyShareReference stores an opaque locator only — no share material column
  exists anywhere in this schema, by design.

## 2. ERD (Mermaid)

```mermaid
erDiagram
    User ||--o{ Membership : "belongs via"
    Organization ||--o{ Membership : has
    Role ||--o{ Membership : "assigned in"
    Role }o--o{ Permission : grants
    Organization ||--o{ Project : owns
    Project ||--o{ Environment : has
    Project ||--o{ APIKey : issues
    User ||--o{ APIKey : "created by"
    BlockchainNetwork ||--o{ NetworkEndpoint : served_by
    BlockchainNetwork ||--o{ Asset : "has native/token"
    Asset ||--|| TokenMetadata : "described by"
    BlockchainNetwork ||--o{ IndexingCheckpoint : tracked_by
    Project ||--o{ MPCWalletGroup : owns
    MPCWalletGroup ||--o{ MPCParticipant : comprises
    MPCParticipant ||--|| KeyShareReference : "locates share for"
    MPCWalletGroup ||--o{ Wallet : backs
    BlockchainNetwork ||--o{ Wallet : "scoped to"
    Wallet ||--o{ WalletAddress : derives
    BlockchainNetwork ||--o{ WalletAddress : "on network"
    WalletAddress ||--o{ AddressAssignment : assigned_via
    ExternalCustomerReference ||--o{ AddressAssignment : receives
    BlockchainNetwork ||--o{ BlockchainTransaction : "recorded on"
    BlockchainTransaction ||--o{ BlockchainTransfer : contains
    Asset ||--o{ BlockchainTransfer : denominates
    BlockchainTransfer }o--o{ WalletAddress : "involves"
    BlockchainTransaction ||--o{ TransactionAddressRelation : "links addresses"
    WalletAddress ||--o{ TransactionAddressRelation : appears_in
    CustodyOperation ||--o{ BlockchainTransaction : "settles via"
    CustodyOperation ||--o{ Deposit : specialises
    CustodyOperation ||--o{ Withdrawal : specialises
    CustodyOperation ||--o{ TreasuryOperation : specialises
    WalletAddress ||--o{ Deposit : receives
    Withdrawal ||--o{ TransactionAttempt : attempted_via
    BlockchainTransaction ||--o{ TransactionAttempt : "is an attempt"
    Withdrawal ||--o{ WithdrawalApproval : approved_by
    User ||--o{ WithdrawalApproval : gives
    Project ||--o{ SweepDestinationResolver : registers
    SweepDestinationResolver ||--o{ SweepJob : "resolves for"
    SweepJob ||--o{ SweepAttempt : attempted_via
    SweepJob ||--|| ResolvedDestinationSnapshot : "uses snapshot"
    SweepDestinationResolver ||--o{ ResolvedDestinationSnapshot : produced
    TreasuryOperation ||--o{ SweepJob : drives
    CustodyOperation ||--o{ SigningSession : signed_via
    SigningPolicy ||--o{ SigningSession : "governs"
    MPCWalletGroup ||--o{ SigningSession : "signs for"
    Project ||--o{ SigningPolicy : defines
    Organization ||--o{ BlacklistEntry : maintains
    BlockchainNetwork ||--o{ BlacklistEntry : "scoped to"
    User ||--o{ SecurityAuditEvent : acts_in
    Organization ||--o{ SecurityAuditEvent : "scoped to"
    Project ||--o{ LedgerAccount : owns
    Asset ||--o{ LedgerAccount : denominates
    JournalEntry ||--o{ JournalLine : contains
    LedgerAccount ||--o{ JournalLine : posted_to
    JournalEntry ||--o{ JournalEntry : "reverses (self ref)"
    LedgerAccount ||--o{ BalanceReservation : holds
    CustodyOperation ||--o{ BalanceReservation : "reserves for"
    Project ||--o{ ReconciliationRun : runs
    BlockchainNetwork ||--o{ ReconciliationRun : covers
    Project ||--o{ WebhookEndpoint : registers
    WebhookEndpoint ||--o{ WebhookDelivery : receives
    OutboxEvent ||--o{ WebhookDelivery : "materialised as"
    APIKey ||--o{ APIUsageRecord : metered_by
    Project ||--o{ APIUsageRecord : metered_in

    User { bigint id PK; string email UK; string password_hash; bool mfa_enabled; timestamptz created_at }
    Organization { bigint id PK; string name; string status; timestamptz created_at }
    Membership { bigint id PK; bigint user_id FK; bigint organization_id FK; bigint role_id FK; string status }
    Role { bigint id PK; bigint organization_id FK "nullable=platform role"; string name }
    Permission { bigint id PK; string code UK; string description }
    Project { bigint id PK; bigint organization_id FK; string name; string status }
    Environment { bigint id PK; bigint project_id FK; string kind "testnet/mainnet"; string name }
    APIKey { bigint id PK; bigint project_id FK; bigint environment_id FK; string key_id UK; string secret_hash; string scopes; string status; timestamptz expires_at; timestamptz last_used_at }
    BlockchainNetwork { bigint id PK; string code UK "ETH/BSC/TRON/SOLANA/TON"; string chain_identifier; int confirmation_policy; string finality_model; bool enabled }
    NetworkEndpoint { bigint id PK; bigint network_id FK; string provider; string url_ref "secret ref, not raw cred"; int priority; string health }
    Asset { bigint id PK; bigint network_id FK; string symbol; string kind "native/USDT/token"; string contract_or_mint "nullable for native"; int decimals; bool enabled }
    TokenMetadata { bigint id PK; bigint asset_id FK; string name; string issuer_info; string metadata_uri }
    IndexingCheckpoint { bigint id PK; bigint network_id FK; bigint endpoint_id FK; string cursor "block/slot/height"; string block_hash; timestamptz updated_at }
    MPCWalletGroup { bigint id PK; bigint project_id FK; string curve "secp256k1/ed25519"; int threshold; int participant_count; string status }
    MPCParticipant { bigint id PK; bigint wallet_group_id FK; string participant_ref; string host_ref; string status }
    KeyShareReference { bigint id PK; bigint participant_id FK; string share_locator "opaque"; string key_version; string checksum_hint }
    Wallet { bigint id PK; bigint wallet_group_id FK; bigint network_id FK; bigint project_id FK; string status; string label }
    WalletAddress { bigint id PK; bigint wallet_id FK; bigint network_id FK; string address; string derivation_path; string status }
    AddressAssignment { bigint id PK; bigint wallet_address_id FK; bigint external_customer_id FK; timestamptz assigned_at; timestamptz released_at }
    ExternalCustomerReference { bigint id PK; bigint project_id FK; string external_id; string label }
    BlockchainTransaction { bigint id PK; bigint network_id FK; string tx_hash; string block_ref; int confirmations; string status; timestamptz observed_at }
    BlockchainTransfer { bigint id PK; bigint blockchain_transaction_id FK; int transfer_index; bigint asset_id FK; string from_address; string to_address; bigint amount_base_units; string direction }
    TransactionAddressRelation { bigint id PK; bigint blockchain_transaction_id FK; bigint wallet_address_id FK; string role "source/destination/internal" }
    CustodyOperation { bigint id PK; bigint project_id FK; string type "deposit/withdrawal/sweep/treasury"; string status; string idempotency_key; bigint asset_id FK }
    Deposit { bigint id PK; bigint custody_operation_id FK; bigint wallet_address_id FK; bigint blockchain_transfer_id FK; bigint amount_base_units; string status }
    Withdrawal { bigint id PK; bigint custody_operation_id FK; bigint wallet_id FK; string destination_address; bigint amount_base_units; string status }
    TransactionAttempt { bigint id PK; bigint withdrawal_id FK "nullable"; bigint sweep_job_id FK "nullable"; bigint blockchain_transaction_id FK "nullable"; int attempt_no; string status; string error }
    WithdrawalApproval { bigint id PK; bigint withdrawal_id FK; bigint approver_user_id FK; string decision; timestamptz decided_at }
    SweepDestinationResolver { bigint id PK; bigint project_id FK; string https_url; string auth_ref "secret ref"; string network_scope; string status }
    SweepJob { bigint id PK; bigint treasury_operation_id FK; bigint resolver_id FK; bigint asset_id FK; bigint amount_base_units; string status; string trigger }
    SweepAttempt { bigint id PK; bigint sweep_job_id FK; int attempt_no; string status; string error }
    ResolvedDestinationSnapshot { bigint id PK; bigint resolver_id FK; bigint sweep_job_id FK; string resolved_address; string response_hash; timestamptz resolved_at }
    TreasuryOperation { bigint id PK; bigint custody_operation_id FK; string kind "sweep/consolidation/fee_funding"; string status }
    SigningSession { bigint id PK; bigint custody_operation_id FK; bigint wallet_group_id FK; bigint signing_policy_id FK; string payload_hash; string status; timestamptz expires_at }
    SigningPolicy { bigint id PK; bigint project_id FK; int version; string rules_json; string status }
    BlacklistEntry { bigint id PK; bigint organization_id FK "nullable=platform"; bigint network_id FK; string address; string reason; bigint created_by FK; bool active }
    SecurityAuditEvent { bigint id PK; bigint organization_id FK; bigint actor_user_id FK "nullable"; string action; string resource_type; string resource_id; string metadata_json; timestamptz created_at }
    LedgerAccount { bigint id PK; bigint project_id FK; bigint asset_id FK; string account_type; string sub_scope_ref "wallet/customer nullable" }
    JournalEntry { bigint id PK; bigint project_id FK; bigint asset_id FK; bigint custody_operation_id FK "nullable"; string idempotency_key; bigint reverses_journal_id FK "nullable"; timestamptz posted_at; string memo }
    JournalLine { bigint id PK; bigint journal_entry_id FK; bigint ledger_account_id FK; string side "debit/credit"; bigint amount_base_units }
    BalanceReservation { bigint id PK; bigint ledger_account_id FK; bigint custody_operation_id FK; bigint amount_base_units; string status; timestamptz expires_at }
    ReconciliationRun { bigint id PK; bigint project_id FK; bigint network_id FK; string status; int break_count; timestamptz started_at; timestamptz finished_at }
    WebhookEndpoint { bigint id PK; bigint project_id FK; string https_url; string secret_ref; string event_types; bool active }
    WebhookDelivery { bigint id PK; bigint webhook_endpoint_id FK; bigint outbox_event_id FK; string status; int attempts; timestamptz next_retry_at }
    OutboxEvent { bigint id PK; bigint organization_id FK; bigint project_id FK; string event_type; string aggregate_type; string aggregate_id; string payload_json; timestamptz created_at; timestamptz published_at }
    APIUsageRecord { bigint id PK; bigint api_key_id FK; bigint project_id FK; string endpoint; int request_count; string window_start }
```

## 3. Entity notes (normative)
| Entity | Key rules |
|---|---|
| User / Membership / Role / Permission | Membership unique (user, org). Role–Permission is M:N via a join table. Platform roles have null organisation. |
| Project / Environment | Project unique per (org, name). Environment gates API keys, endpoints and wallet network family usage. |
| APIKey | Only hash of secret stored. `key_id` is public identifier. Plain secret shown once, never persisted. |
| BlockchainNetwork / NetworkEndpoint | Network code enum-like: ETH, BSC, TRON, SOLANA, TON. Endpoint URL credentials referenced via secrets, not columns. |
| Asset / TokenMetadata | Unique (network, contract_or_mint) for tokens; unique (network) for native. Decimals immutable after first transfer (INV-NET-01). |
| IndexingCheckpoint | Unique (network, endpoint/scope). Cursor semantics per chain (block number, slot, etc.) stored as string + numeric helper where needed. |
| MPCWalletGroup / Participant / KeyShareReference | Threshold ≤ participant_count. KeyShareReference.locator is opaque; a CHECK/review rule forbids seed/share-shaped values — enforced operationally, not by regex alone. |
| Wallet / WalletAddress | WalletAddress unique (network, address). Derivation path unique per wallet where deterministic derivation applies. |
| AddressAssignment | Partial unique: one active assignment per address; history retained after release. |
| ExternalCustomerReference | Unique (project, external_id). Stores tenant's id only — no end-customer PII by default. |
| BlockchainTransaction / Transfer | Unique (network, tx_hash). Transfer unique (transaction, transfer_index). Amount is bigint base units. |
| TransactionAddressRelation | Links known addresses to a transaction with a role; enables address-history without parsing JSON payloads. |
| CustodyOperation | Common spine: type, status, idempotency_key unique per project. Subtypes hold 1:1 detail rows. |
| Deposit | Unique on blockchain_transfer_id (one deposit per transfer). Credit journal linked via CustodyOperation → JournalEntry. |
| Withdrawal / TransactionAttempt / WithdrawalApproval | Attempt numbers unique per parent. Approvals unique (withdrawal, approver). |
| SweepDestinationResolver / SweepJob / SweepAttempt / ResolvedDestinationSnapshot | Resolver URL must be HTTPS (CHECK + service validation). Snapshot is mandatory FK from the job's execution: a job that signed has exactly one snapshot used. No `destination_address` column exists on SweepJob — by design. |
| TreasuryOperation | Subtype of CustodyOperation for sweeps/consolidations; links SweepJobs. |
| SigningSession | payload_hash only; no payload secrets. Status expiry enforced. Unique per operation + attempt semantics defined by MPC gateway contract. |
| SigningPolicy | Unique (project, version). Versions immutable once used by a session. |
| BlacklistEntry | Unique active (network, address, scope). Manual creation only; created_by + reason NOT NULL. |
| SecurityAuditEvent | Append-only. No updated_at semantics; corrections are new events. |
| LedgerAccount / JournalEntry / JournalLine / BalanceReservation | See §4. Lines amount > 0 CHECK. Entry idempotency_key unique. Reversal is a self-FK. |
| ReconciliationRun | Stores summary + break_count; individual breaks reference accounts/transactions in child/detail records or payload with stable ids. |
| WebhookEndpoint / WebhookDelivery / OutboxEvent | Endpoint HTTPS only. Delivery unique (endpoint, outbox_event) per attempt generation; retries update attempts/next_retry_at on the delivery row. |
| APIUsageRecord | Aggregated per key + window; raw request logs are not stored here. |

## 4. Ledger physical rules
- `JournalLine.amount_base_units` BIGINT, CHECK > 0. Assets exceeding int64
  range require a pre-launch decision to NUMERIC(78,0) for amount columns —
  flagged here so it is decided before data exists, not after.
- Balance is a view/query over lines (optionally a materialised projection
  rebuilt from lines). No `balance` column on LedgerAccount is authoritative.
- JournalEntry + lines are inserted in one transaction after a balance check
  in the posting service; DB grants deny UPDATE/DELETE to the app role.
- BalanceReservation has a partial unique / exclusion concern handled in the
  service transaction (account row lock), not by a simple unique index.

## 5. Uniqueness and idempotency summary
| Constraint | Protects against |
|---|---|
| (network, tx_hash) unique | Duplicate transaction ingestion |
| (transaction, transfer_index) unique | Duplicate deposit credit (INV-DEP-01/02) |
| (project, idempotency_key) on CustodyOperation | Duplicate withdrawals/sweeps from retries |
| JournalEntry.idempotency_key unique | Duplicate postings from Temporal retries |
| (network, address) on WalletAddress | Double-tracking one address |
| (withdrawal, approver) on WithdrawalApproval | Double approval by one person |
| (endpoint, outbox_event) on WebhookDelivery | Duplicate deliveries per endpoint |

## 6. Delete / retention behaviour
- Financial, ledger, audit, snapshot and journal rows: no hard delete.
- Reference data (networks, assets): disable via `enabled/status`, never
  delete once referenced.
- Personal data (User email): handled by account lifecycle policy; audit
  events retain actor id with tombstoned user display data if erased.

## 7. What is deliberately NOT in the schema
- No key share / seed / mnemonic / private key columns anywhere.
- No sweep destination column on SweepJob / SweepAttempt / resolver requests.
- No AML/KYT score, screening status or provider reference columns.
- No float/double amount columns anywhere.
- No cached “total tenant balance” column treated as truth.
