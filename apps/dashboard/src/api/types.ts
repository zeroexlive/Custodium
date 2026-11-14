/** Shared API types — mirror the Phase 1 Django Ninja contracts in docs/api. */
export interface User { id: string; email: string; display_name?: string; is_email_verified?: boolean; totp_enabled?: boolean; is_staff?: boolean; is_superuser?: boolean }
/** A platform customer account, as listed for platform administrators. */
export interface CustomerAccount extends User { is_active?: boolean; date_joined?: string | null }
/** Returned once when an administrator creates a customer: the
 *  temporary password is shown to the admin a single time so it can
 *  be delivered to the customer. It is never stored client-side. */
export interface CustomerCreated extends CustomerAccount { temporary_password: string; credentials_email_sent: boolean }
/** A deposit address bound to a customer end-user UID, with its
 *  wallet status and observed-deposit summary for troubleshooting. */
export interface DepositAddressRecord extends WalletAddress {
  external_customer_id: string; wallet_status: string; wallet_label: string;
  created?: boolean;
  deposits: { count: number; held_count: number; credited_totals: { asset: string; amount: string }[] };
}
export interface Organization { id: string; name: string; slug?: string; role?: string; created_at?: string }
export interface Project { id: string; organization_id: string; name: string; environment: 'sandbox' | 'production'; created_at?: string }
export interface ApiKey {
  id: string; project_id: string; name: string; key_id: string;
  scopes: string[]; status: 'active' | 'revoked' | 'expired';
  ip_allowlist?: string[];
  created_at?: string; expires_at?: string | null; last_used_at?: string | null;
}
/** Returned exactly once at creation; the secret must never be persisted client-side. */
export interface ApiKeyCreated extends ApiKey { secret: string }
export interface Network { id: string; slug: string; name: string; native_symbol: string; signature_family: 'ecdsa_secp256k1' | 'ed25519'; is_testnet: boolean; operational_status?: string }
export interface Asset {
  id: string; network: string; symbol: string; name: string; decimals: number;
  contract_or_mint_address?: string | null; token_standard?: string;
  issuer_classification: string; verification_status: string;
  deposit_enabled?: boolean; withdrawal_enabled?: boolean;
}
export interface AuthResponse {
  access_token?: string | null; token?: string | null; user?: User;
  /** True when the login paused at the TOTP challenge (no token yet). */
  requires_totp?: boolean; mfa_token?: string | null;
}
export interface TotpSetup { secret: string; provisioning_uri: string }
export interface TotpEnabled { detail: string; recovery_codes: string[] }
export interface MatchedAddress { address_id: string; wallet_id: string; external_customer_id?: string | null; role: string }
export interface Transfer { transfer_id: string; direction: 'in' | 'out'; amount_base_units: string; decimals: number; asset?: string; from?: string; to?: string }
export interface TransactionLookup {
  network: string; transaction_hash: string; status: string; indexed: boolean;
  belongs_to_tenant: boolean; block_or_slot?: string | number | null; timestamp?: string | null;
  confirmations?: number | null; matched_addresses: MatchedAddress[]; transfers: Transfer[];
  tenant_record?: { type: string; transaction_id: string; wallet_id: string; external_customer_id?: string | null; status: string; held: boolean; withdrawal_request_id?: string | null; external_reference?: string };
}
/** Deposits observed by the Phase 5 indexer for one wallet. Amounts are
 *  integer base-unit strings. `held` deposits (blacklisted sender) stay
 *  pending for manual review and are never auto-credited. */
export interface DepositRecord {
  id: string; network: string; tx_hash: string; asset: string;
  contract_or_mint_address: string | null; amount: string;
  from_address: string; to_address: string; status: 'pending' | 'credited' | 'reorged_out';
  held: boolean; block_number: number; confirmations: number | null; confirmations_required: number;
}
export interface SweepDestinationEndpoint {
  endpoint_url: string; url: string; enabled: boolean; version: number;
  has_signing_secret: boolean; updated_by: string | null; updated_at?: string;
}
export interface SweepEndpointHistoryRow {
  action: string; actor_id: string; previous_url_hash: string;
  new_url_hash: string; created_at: string;
}
/** Sweeps (Phase 10). The destination comes only from the snapshot. */
export interface Sweep {
  id: string; wallet_id: string; network: string; asset: string;
  status: string; status_reason: string; amount: string | null;
  destination_address: string | null; approvals_required: number;
  approvals_received: number; chain_tx_hash: string;
  external_reference: string; created_at: string;
}
/** Gas station: per-(project, network) native-coin top-up config. */
export interface GasStation {
  id: string; project_id: string; network: string; funding_wallet_id: string;
  /** Where the client sends native coin to fund this station. */
  top_up_address?: string | null;
  enabled: boolean; min_native_balance: string; topup_amount: string;
  max_topups_per_day: number;
}
export interface AddressBookEntry {
  id: string; project_id: string; network: string; address: string; label: string;
}
export interface AutoSweepRule {
  id: string; project_id: string; wallet_id: string; network: string;
  asset_id: string; threshold_amount: string;
  enabled: boolean; trigger_count: number;
}
export interface SweepPolicy {
  project_id: string; destination_mode: 'resolver' | 'static';
  min_sweep_threshold: string; leave_behind: string; enabled: boolean;
}
export interface StaticSweepDestination {
  id: string; project_id: string; network: string; address: string;
  label: string; enabled: boolean;
}
export interface DepositPolicy {
  project_id: string; asset_id: string; asset: string; network: string;
  min_amount: string;
}
export interface GasTopUp {
  id: string; network: string; target_wallet_id: string; amount: string;
  status: string; operation_key: string; chain_tx_hash: string;
  failure_reason: string; created_at: string;
}
export interface Paginated<T> { items: T[]; total?: number }

/** Wallets (Phase 2). A wallet stays `provisioning` until MPC key generation
 *  completes in Phase 3 — the API refuses to activate it before then. */
export type WalletStatus = 'provisioning' | 'active' | 'frozen' | 'archived'
export interface Wallet {
  id: string; project_id: string; label: string; external_customer_id: string;
  wallet_type: string; status: WalletStatus;
  key_generation: { ecdsa_key_ref: string | null; ed25519_key_ref: string | null };
  policy_name: string; policy_version: string;
  created_at?: string | null;
}
export interface WalletAddress {
  id: string; wallet_id: string; network: string; address: string;
  derivation_path: string; derivation_index: number;
  memo: string | null; status: 'active' | 'disabled';
  created_at?: string | null;
}
/** Ledger balances. All amounts are integer strings in base units — the
 *  dashboard displays them raw and never converts them to floats. */
export interface BalanceItem {
  asset_id: string; symbol: string; network: string; decimals: number;
  accounts: Record<string, string>;
  available: string; reserved: string; pending: string;
}
export interface ProjectBalances { project_id: string; items: BalanceItem[]; total: number }
export interface WalletBalances { wallet_id: string; items: BalanceItem[]; total: number }

/** Manual blacklist (Phase 2) — a manually curated list maintained by
 *  people. It is NOT an AML/KYT or risk-scoring system. */
export type BlacklistScope = 'platform' | 'tenant'
export interface BlacklistEntry {
  id: string; scope: BlacklistScope;
  organization_id: string | null; project_id: string | null;
  network: string; address: string; normalized_address: string;
  reason: string; active: boolean; effective: boolean;
  expires_at: string | null; created_at?: string | null;
}
export interface BlacklistCheckResult {
  blacklisted: boolean; matched_scopes: BlacklistScope[]; network: string;
}

/** Withdrawal operations (Phase 9). Amounts are integer base-unit strings. */
export interface WithdrawalRequest {
  id: string; wallet_id: string; external_customer_id?: string; network: string; asset: string;
  destination_address: string; amount: string; status: string;
  status_reason: string; external_reference: string;
  approvals_required: number; approvals_received: number;
  service_fee: string; actual_fee: string | null; fee_asset: string | null;
  chain_tx_hash: string; refunded_amount: string; created_at: string;
}

export interface WithdrawalPolicy {
  approvals_required: number;
  min_single_amount?: string | null;
  max_single_amount: string | null;
  daily_limit: string | null;
  auto_approve_below: string;
  service_fee_flat: string;
}

/** Webhooks (Phase 11). */
export interface WebhookEndpoint {
  id: string; url: string; events: string[]; enabled: boolean; created_at: string;
}
export interface WebhookEndpointCreated extends WebhookEndpoint { signing_secret: string }
export interface WebhookDelivery {
  id: string; event_id: string; event_type: string; endpoint_url: string;
  status: string; attempts: number; last_status_code: number | null;
  last_error: string; next_attempt_at: string | null; delivered_at: string | null;
}
export const WEBHOOK_EVENT_TYPES = [
  'deposit.credited', 'withdrawal.completed', 'withdrawal.failed',
  'sweep.completed', 'sweep.failed',
] as const

/** Plans & billing (Phase 11, fiat only). */
export interface Plan {
  slug: string; name: string; monthly_price_cents: number;
  quotas: Record<string, number>;
}
export interface UsageSnapshot {
  plan: string; period_start: string; period_end: string;
  wallets: { used: number; limit: number };
  api_keys: { used: number; limit: number };
  withdrawals_this_period: { used: number; included: number };
}
export interface Invoice {
  id: string; period_start: string; period_end: string;
  line_items: { label: string; quantity: number; unit_cents: number; amount_cents: number }[];
  total_cents: number; currency: string; status: string;
}
/** Team management (Phase 11). */
export interface OrgMember {
  membership_id: string; user_id: string; email: string; role: string; created_at: string;
}

export interface AuditLogEntry {
  id: string; event_type: string;
  organization_id: string | null; project_id: string | null;
  metadata: Record<string, unknown>; created_at: string;
}
