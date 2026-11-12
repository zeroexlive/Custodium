import type {
  ApiKey, ApiKeyCreated, Asset, AuthResponse, Network, Organization, Project,
  SweepDestinationEndpoint, TransactionLookup, User,
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

async function request<T>(method: Method, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
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

  // Sweep destination resolver endpoint
  getSweepEndpoint: () => request<SweepDestinationEndpoint>('GET', '/sweep-destination-endpoint'),
  putSweepEndpoint: (endpoint_url: string) =>
    request<SweepDestinationEndpoint>('PUT', '/sweep-destination-endpoint', { endpoint_url }),
  deleteSweepEndpoint: () => request<void>('DELETE', '/sweep-destination-endpoint'),
}
export type Api = typeof api
