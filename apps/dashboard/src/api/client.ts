import type {
  ApiKey, ApiKeyCreated, Asset, AuthResponse, BlacklistCheckResult,
  BlacklistEntry, BlacklistScope, Network, Organization, Project,
  ProjectBalances, Sweep, SweepDestinationEndpoint, SweepEndpointHistoryRow, TransactionLookup, DepositRecord, User, Wallet,
  WalletAddress, WalletBalances, WithdrawalPolicy, WithdrawalRequest,
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

  // Organizations & projects
  listOrganizations: async (): Promise<Organization[]> => listOf(await request<Organization[] | { items: Organization[] }>('GET', '/organizations')),
  createOrganization: (payload: { name: string }) =>
    request<Organization>('POST', '/organizations', payload),
  listProjects: async (): Promise<Project[]> => listOf(await request<Project[] | { items: Project[] }>('GET', '/projects')),
  createProject: (payload: { organization_id: string; name: string; environment: 'sandbox' | 'production' }) =>
    request<Project>('POST', '/projects', payload),

  // API credentials (secrets are shown once — see ApiKeysView)
  listApiKeys: async (): Promise<ApiKey[]> => listOf(await request<ApiKey[] | { items: ApiKey[] }>('GET', '/api-keys')),
  createApiKey: (payload: { project_id: string; name: string; scopes: string[] }) =>
    request<ApiKeyCreated>('POST', '/api-keys', payload),
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

  // Addresses — listing only. Derivation arrives with MPC Phase 3/4 and the
  // POST endpoint returns 501 until then; there is deliberately no create call.
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
    approvals_required: number; max_single_amount?: string | null; daily_limit?: string | null;
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
}
export type Api = typeof api
