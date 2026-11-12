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
export interface Transfer { transfer_id: string; asset_id: string; direction: 'incoming' | 'outgoing'; amount_base_units: string; decimals: number }
export interface TransactionLookup {
  network: string; transaction_hash: string; status: string; indexed: boolean;
  belongs_to_tenant: boolean; block_or_slot?: string | number | null; timestamp?: string | null;
  confirmations?: number | null; matched_addresses: MatchedAddress[]; transfers: Transfer[];
}
export interface SweepDestinationEndpoint { endpoint_url: string; status?: string; updated_at?: string }
export interface Paginated<T> { items: T[]; total?: number }
