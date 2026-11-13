import type {
  AddressBookEntry, ApiKey, ApiKeyCreated, Asset, AuditLogEntry, AuthResponse, AutoSweepRule, BlacklistCheckResult,
  BlacklistEntry, BlacklistScope, DepositPolicy, Network, Organization, Project,
  GasStation, GasTopUp, StaticSweepDestination, SweepPolicy, TotpEnabled, TotpSetup,
  ProjectBalances, Sweep, SweepDestinationEndpoint, SweepEndpointHistoryRow, TransactionLookup, DepositRecord, User, Wallet,
  Invoice, OrgMember, Plan, UsageSnapshot, WalletAddress, WalletBalances,
  WebhookDelivery, WebhookEndpoint, WebhookEndpointCreated, WithdrawalPolicy, WithdrawalRequest,
} from './types'

export class ApiError extends Error {
  readonly status: number
  readonly detail: unknown
  constructor(status: number, message: string, detail?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

const BASE = '/api/v1'
let authToken: string | null = null
/** Called by the auth store; the dashboard session token is never an API secret. */
export function setAuthToken(token: string | null): void { authToken = token }

type Method = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'

async function request<T>(method: Method, path: string, body?: unknown, extraHeaders?: Record<string, string>): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json', ...(extraHeaders ?? {}) }
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (authToken) headers.Authorization = `Bearer ${authToken}`
  let response: Response
  try {
    response = await fetch(`${BASE}${path}`, {
      method, headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: 'include',
    })
  } catch (cause) {
    throw new ApiError(0, 'Network error — is the API reachable?', cause)
  }
  const text = await response.text()
  let data: unknown = null
  if (text) { try { data = JSON.parse(text) } catch { data = text } }
  if (!response.ok) {
    const msg = (data as { detail?: string } | null)?.detail ?? `Request failed (${response.status})`
    throw new ApiError(response.status, String(msg), data)
  }
  return data as T
}

/** Backends may return a bare array or {items: [...]} — normalise both. */
function listOf<T>(data: T[] | { items: T[] }): T[] {
  return Array.isArray(data) ? data : data.items
}

export const api = {
  // Auth / identity
  register: (payload: { email: string; password: string; display_name?: string }) =>
    request<AuthResponse>('POST', '/auth/register', payload),
  login: (payload: { email: string; password: string }) =>
    request<AuthResponse>('POST', '/auth/login', payload),
  logout: () => request<void>('POST', '/auth/logout'),
  me: () => request<User>('GET', '/me'),

  // Two-factor authentication (TOTP). Setup returns the secret once;
  // enable returns the recovery codes once.
  verifyTotp: (payload: { mfa_token: string; code: string }) =>
    request<AuthResponse>('POST', '/auth/2fa/verify', payload),
  totpSetup: () => request<TotpSetup>('POST', '/auth/2fa/setup'),
  totpEnable: (code: string) => request<TotpEnabled>('POST', '/auth/2fa/enable', { code }),
  totpDisable: (code: string) => request<{ detail: string }>('POST', '/auth/2fa/disable', { code }),

  // Organizations & projects
  listOrganizations: async (): Promise<Organization[]> => listOf(await request<Organization[] | { items: Organization[] }>('GET', '/organizations')),
  createOrganization: (payload: { name: string }) =>
    request<Organization>('POST', '/organizations', payload),
  listProjects: async (): Promise<Project[]> => listOf(await request<Project[] | { items: Project[] }>('GET', '/projects')),
  createProject: (payload: { organization_id: string; name: string; environment: 'sandbox' | 'production' }) =>
    request<Project>('POST', '/projects', payload),

  // API credentials (secrets are shown once — see ApiKeysView)
  listApiKeys: async (): Promise<ApiKey[]> => listOf(await request<ApiKey[] | { items: ApiKey[] }>('GET', '/api-keys')),
  createApiKey: (payload: {
    project_id: string; name: string; scopes: string[];
    ip_allowlist?: string[]; expires_at?: string | null;
  }) => request<ApiKeyCreated>('POST', '/api-keys', payload),
  rotateApiKey: (id: string) => request<ApiKeyCreated>('POST', `/api-keys/${encodeURIComponent(id)}/rotate`),
  revokeApiKey: (id: string) => request<void>('POST', `/api-keys/${encodeURIComponent(id)}/revoke`),

  // Networks & assets
  listNetworks: async (): Promise<Network[]> => listOf(await request<Network[] | { items: Network[] }>('GET', '/networks')),
  listAssets: async (): Promise<Asset[]> => listOf(await request<Asset[] | { items: Asset[] }>('GET', '/assets')),

  // Transaction hash explorer
  lookupTransaction: (network: string, hash: string) =>
    request<TransactionLookup>('GET', `/transactions/lookup?network=${encodeURIComponent(network)}&hash=${encodeURIComponent(hash)}`),
  listWalletDeposits: (walletId: string, projectId: string) =>
    request<{ deposits: DepositRecord[] }>('GET', `/wallets/${encodeURIComponent(walletId)}/deposits?project_id=${encodeURIComponent(projectId)}`),

  // Wallets (Phase 2 records; MPC key generation itself is Phase 3)
  listWallets: async (filters: { project_id: string; external_customer_id?: string; status?: string }): Promise<Wallet[]> => {
    const params = new URLSearchParams({ project_id: filters.project_id })
    if (filters.external_customer_id) params.set('external_customer_id', filters.external_customer_id)
    if (filters.status) params.set('status', filters.status)
    return listOf(await request<Wallet[] | { items: Wallet[] }>('GET', `/wallets?${params.toString()}`))
  },
  createWallet: (payload: { project_id: string; label: string; external_customer_id?: string }) =>
    request<Wallet>('POST', '/wallets', payload),
  getWallet: (id: string) => request<Wallet>('GET', `/wallets/${encodeURIComponent(id)}`),
  /** Invalid transitions are rejected with 409 — e.g. a provisioning wallet
   *  cannot be activated through the API before MPC key generation. */
  setWalletStatus: (id: string, status: 'active' | 'frozen' | 'archived') =>
    request<Wallet>('PATCH', `/wallets/${encodeURIComponent(id)}/status`, { status }),

  // Addresses — listing, plus create: returns the existing address or
  // derives + records it from the wallet's group public key (409 when
  // the wallet is not provisioned yet; nothing is fabricated).
  createWalletAddress: (walletId: string, network: string) =>
    request<WalletAddress>('POST', `/wallets/${encodeURIComponent(walletId)}/addresses`, { network }),
  listWalletAddresses: async (walletId: string, network?: string): Promise<WalletAddress[]> => {
    const query = network ? `?network=${encodeURIComponent(network)}` : ''
    return listOf(await request<WalletAddress[] | { items: WalletAddress[] }>('GET', `/wallets/${encodeURIComponent(walletId)}/addresses${query}`))
  },

  // Balances — integer base-unit strings, displayed raw by the views.
  getProjectBalances: (projectId: string) =>
    request<ProjectBalances>('GET', `/projects/${encodeURIComponent(projectId)}/balances`),
  getWalletBalances: (walletId: string) =>
    request<WalletBalances>('GET', `/wallets/${encodeURIComponent(walletId)}/balances`),

  // Financial operations — withdrawal requests and policy (Phase 9).
  listWithdrawals: async (projectId: string) =>
    listOf(await request<WithdrawalRequest[] | { items: WithdrawalRequest[] }>('GET', `/withdrawals?project_id=${encodeURIComponent(projectId)}`)),
  createWithdrawal: (payload: {
    wallet_id: string; network: string; asset_id: string;
    destination_address: string; amount: string; external_reference?: string;
  }, idempotencyKey: string) =>
    request<WithdrawalRequest>('POST', '/withdrawals', payload, { 'Idempotency-Key': idempotencyKey }),
  approveWithdrawal: (id: string) =>
    request<WithdrawalRequest>('POST', `/withdrawals/${encodeURIComponent(id)}/approve`, { note: '' }),
  rejectWithdrawal: (id: string) =>
    request<WithdrawalRequest>('POST', `/withdrawals/${encodeURIComponent(id)}/reject`, { note: '' }),
  refundWithdrawal: (id: string, amount: string, reason: string) =>
    request<WithdrawalRequest>('POST', `/withdrawals/${encodeURIComponent(id)}/refund`, { amount, reason }),
  getWithdrawalPolicy: (projectId: string) =>
    request<WithdrawalPolicy>('GET', `/projects/${encodeURIComponent(projectId)}/withdrawal-policy`),
  updateWithdrawalPolicy: (projectId: string, payload: {
    approvals_required: number; min_single_amount?: string | null;
    max_single_amount?: string | null; daily_limit?: string | null;
    auto_approve_below: string; service_fee_flat: string;
  }) => request<WithdrawalPolicy>('PUT', `/projects/${encodeURIComponent(projectId)}/withdrawal-policy`, payload),

  // Manual blacklist — a manually curated list only, not an AML/KYT system.
  listBlacklistEntries: async (organizationId: string): Promise<BlacklistEntry[]> =>
    listOf(await request<BlacklistEntry[] | { items: BlacklistEntry[] }>('GET', `/blacklist/entries?organization_id=${encodeURIComponent(organizationId)}`)),
  createBlacklistEntry: (payload: {
    scope: BlacklistScope; organization_id?: string; project_id?: string;
    network: string; address: string; reason: string; expires_at?: string;
  }) => request<BlacklistEntry>('POST', '/blacklist/entries', payload),
  disableBlacklistEntry: (id: string) =>
    request<BlacklistEntry>('POST', `/blacklist/entries/${encodeURIComponent(id)}/disable`),
  checkBlacklist: (params: { address: string; network: string; organization_id?: string }) => {
    const query = new URLSearchParams({ address: params.address, network: params.network })
    if (params.organization_id) query.set('organization_id', params.organization_id)
    return request<BlacklistCheckResult>('GET', `/blacklist/check?${query.toString()}`)
  },

  // Sweep destination resolver endpoint (Phase 10)
  getSweepEndpoint: (projectId: string) =>
    request<SweepDestinationEndpoint>('GET', `/sweep-destination-endpoint?project_id=${encodeURIComponent(projectId)}`),
  putSweepEndpoint: (projectId: string, endpoint_url: string, signing_secret = '') =>
    request<SweepDestinationEndpoint>('PUT', '/sweep-destination-endpoint', { project_id: projectId, endpoint_url, signing_secret }),
  deleteSweepEndpoint: (projectId: string) =>
    request<SweepDestinationEndpoint>('DELETE', `/sweep-destination-endpoint?project_id=${encodeURIComponent(projectId)}`),
  getSweepEndpointHistory: async (projectId: string) =>
    listOf(await request<SweepEndpointHistoryRow[] | { items: SweepEndpointHistoryRow[] }>('GET', `/sweep-destination-endpoint/history?project_id=${encodeURIComponent(projectId)}`)),
  testSweepEndpoint: (projectId: string, network: string) =>
    request<{ address: string; normalized: string; network: string }>('POST', '/sweep-destination-endpoint/test', { project_id: projectId, network }),

  // Sweeps (Phase 10) — requests never carry a destination.
  listSweeps: async (projectId: string) =>
    listOf(await request<Sweep[] | { items: Sweep[] }>('GET', `/sweeps?project_id=${encodeURIComponent(projectId)}`)),
  createSweep: (payload: { wallet_id: string; network: string; asset_id: string }, idempotencyKey: string) =>
    request<Sweep>('POST', '/sweeps', payload, { 'Idempotency-Key': idempotencyKey }),
  approveSweep: (id: string) => request<Sweep>('POST', `/sweeps/${encodeURIComponent(id)}/approve`, { note: '' }),
  rejectSweep: (id: string) => request<Sweep>('POST', `/sweeps/${encodeURIComponent(id)}/reject`, { note: '' }),

  // Gas station — per-(project, network) top-up configuration.
  listGasStations: async (projectId: string) =>
    listOf(await request<GasStation[] | { items: GasStation[] }>('GET', `/gas-stations?project_id=${encodeURIComponent(projectId)}`)),
  putGasStation: (payload: {
    project_id: string; network: string; funding_wallet_id: string;
    min_native_balance: string; topup_amount: string; max_topups_per_day: number; enabled: boolean;
  }) => request<GasStation>('PUT', '/gas-stations', payload),
  listGasTopups: async (projectId: string) =>
    listOf(await request<GasTopUp[] | { items: GasTopUp[] }>('GET', `/gas-stations/topups?project_id=${encodeURIComponent(projectId)}`)),

  // Webhooks (Phase 11)
  listWebhookEndpoints: async (projectId: string) =>
    listOf(await request<WebhookEndpoint[] | { items: WebhookEndpoint[] }>('GET', `/webhooks/endpoints?project_id=${encodeURIComponent(projectId)}`)),
  createWebhookEndpoint: (projectId: string, url: string, events: string[]) =>
    request<WebhookEndpointCreated>('POST', '/webhooks/endpoints', { project_id: projectId, url, events }),
  disableWebhookEndpoint: (id: string) =>
    request<WebhookEndpoint>('DELETE', `/webhooks/endpoints/${encodeURIComponent(id)}`),
  listWebhookDeliveries: async (projectId: string) =>
    listOf(await request<WebhookDelivery[] | { items: WebhookDelivery[] }>('GET', `/webhooks/deliveries?project_id=${encodeURIComponent(projectId)}`)),
  replayWebhookDelivery: (id: string) =>
    request<{ id: string; status: string }>('POST', `/webhooks/deliveries/${encodeURIComponent(id)}/replay`),

  // Destination address book + withdrawal allowlist policy.
  listAddressBook: async (projectId: string): Promise<AddressBookEntry[]> =>
    listOf(await request<AddressBookEntry[] | { items: AddressBookEntry[] }>('GET', `/address-book?project_id=${encodeURIComponent(projectId)}`)),
  addAddressBookEntry: (payload: { project_id: string; network: string; address: string; label?: string }) =>
    request<AddressBookEntry>('POST', '/address-book', payload),
  deleteAddressBookEntry: (id: string) => request<{ detail: string }>('DELETE', `/address-book/${encodeURIComponent(id)}`),
  getAddressBookPolicy: (projectId: string) =>
    request<{ project_id: string; withdrawal_allowlist_required: boolean }>('GET', `/address-book/policy?project_id=${encodeURIComponent(projectId)}`),
  setAddressBookPolicy: (projectId: string, required: boolean) =>
    request<{ project_id: string; withdrawal_allowlist_required: boolean }>('PATCH', '/address-book/policy', { project_id: projectId, required }),

  // Deposit policies — per-asset minimums (no maximum exists by design).
  listDepositPolicies: async (projectId: string): Promise<DepositPolicy[]> =>
    listOf(await request<DepositPolicy[] | { items: DepositPolicy[] }>('GET', `/deposit-policies?project_id=${encodeURIComponent(projectId)}`)),
  putDepositPolicy: (payload: { project_id: string; asset_id: string; min_amount: string }) =>
    request<DepositPolicy>('PUT', '/deposit-policies', payload),

  // Sweep policy, static destinations, auto-sweep rules.
  getSweepPolicy: (projectId: string) =>
    request<SweepPolicy>('GET', `/sweep-policy?project_id=${encodeURIComponent(projectId)}`),
  putSweepPolicy: (payload: {
    project_id: string; destination_mode: 'resolver' | 'static';
    min_sweep_threshold: string; leave_behind: string; enabled: boolean;
  }) => request<SweepPolicy>('PUT', '/sweep-policy', payload),
  listStaticDestinations: async (projectId: string): Promise<StaticSweepDestination[]> =>
    listOf(await request<StaticSweepDestination[] | { items: StaticSweepDestination[] }>('GET', `/sweep-destinations?project_id=${encodeURIComponent(projectId)}`)),
  putStaticDestination: (payload: { project_id: string; network: string; address: string; label?: string }) =>
    request<StaticSweepDestination>('PUT', '/sweep-destinations', payload),
  deleteStaticDestination: (id: string) =>
    request<{ detail: string }>('DELETE', `/sweep-destinations/${encodeURIComponent(id)}`),
  listAutoSweepRules: async (projectId: string): Promise<AutoSweepRule[]> =>
    listOf(await request<AutoSweepRule[] | { items: AutoSweepRule[] }>('GET', `/auto-sweep-rules?project_id=${encodeURIComponent(projectId)}`)),
  createAutoSweepRule: (payload: {
    wallet_id: string; network: string; asset_id: string;
    threshold_amount: string; enabled: boolean;
  }) => request<AutoSweepRule>('POST', '/auto-sweep-rules', payload),
  deleteAutoSweepRule: (id: string) =>
    request<{ detail: string }>('DELETE', `/auto-sweep-rules/${encodeURIComponent(id)}`),

  // Webhook signing-secret rotation (new secret returned once).
  rotateWebhookSecret: (id: string) =>
    request<{ id: string; signing_secret: string }>('POST', `/webhooks/endpoints/${encodeURIComponent(id)}/rotate-secret`),

  // Audit log — the caller's organizations, most recent 100 events.
  listAuditLogs: async (): Promise<AuditLogEntry[]> =>
    listOf(await request<AuditLogEntry[] | { items: AuditLogEntry[] }>('GET', '/audit-logs')),

  // Plans & billing (Phase 11)
  listPlans: async () => listOf(await request<Plan[] | { items: Plan[] }>('GET', '/plans')),
  getUsage: (organizationId: string) =>
    request<UsageSnapshot>('GET', `/organizations/${encodeURIComponent(organizationId)}/usage`),
  setSubscription: (organizationId: string, planSlug: string) =>
    request<{ plan: string; status: string }>('POST', `/organizations/${encodeURIComponent(organizationId)}/subscription`, { plan_slug: planSlug }),
  listInvoices: async (organizationId: string) =>
    listOf(await request<Invoice[] | { items: Invoice[] }>('GET', `/organizations/${encodeURIComponent(organizationId)}/invoices`)),
  markInvoicePaid: (invoiceId: string) =>
    request<{ id: string; status: string }>('POST', `/invoices/${encodeURIComponent(invoiceId)}/mark-paid`),

  // Team management (Phase 11)
  listMembers: async (organizationId: string) =>
    listOf(await request<OrgMember[] | { items: OrgMember[] }>('GET', `/organizations/${encodeURIComponent(organizationId)}/members`)),
  addMember: (organizationId: string, email: string, role: string) =>
    request<OrgMember>('POST', `/organizations/${encodeURIComponent(organizationId)}/members`, { email, role }),
  updateMemberRole: (organizationId: string, membershipId: string, role: string) =>
    request<OrgMember>('PATCH', `/organizations/${encodeURIComponent(organizationId)}/members/${encodeURIComponent(membershipId)}`, { role }),
  removeMember: (organizationId: string, membershipId: string) =>
    request<{ removed: string }>('DELETE', `/organizations/${encodeURIComponent(organizationId)}/members/${encodeURIComponent(membershipId)}`),
}
export type Api = typeof api
