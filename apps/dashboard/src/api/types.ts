/** Shared API types — mirror the Phase 1 Django Ninja contracts in docs/api. */
export interface User { id: string; email: string; display_name?: string; is_email_verified?: boolean }
export interface Organization { id: string; name: string; slug?: string; role?: string; created_at?: string }
export interface Project { id: string; organization_id: string; name: string; environment: 'sandbox' | 'production'; created_at?: string }
export interface ApiKey {
  id: string; project_id: string; name: string; key_id: string;
  scopes: string[]; status: 'active' | 'revoked' | 'expired';
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
export interface AuthResponse { access_token?: string; token?: string; user?: User }
export interface MatchedAddress { address_id: string; wallet_id: string; external_customer_id?: string | null; role: string }
export interface Transfer { transfer_id: string; direction: 'in' | 'out'; amount_base_units: string; decimals: number; asset?: string; from?: string; to?: string }
export interface TransactionLookup {
  network: string; transaction_hash: string; status: string; indexed: boolean;
  belongs_to_tenant: boolean; block_or_slot?: string | number | null; timestamp?: string | null;
  confirmations?: number | null; matched_addresses: MatchedAddress[]; transfers: Transfer[];
  tenant_record?: { type: string; transaction_id: string; wallet_id: string; external_customer_id?: string | null; status: string; held: boolean };
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
export interface SweepDestinationEndpoint { endpoint_url: string; status?: string; updated_at?: string }
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
