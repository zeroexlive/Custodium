import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { api } from '@/api/client'
import { useAuthStore } from '@/stores/auth'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function captureFetch(responseBody: unknown = {}) {
  const fetchMock = vi.fn(async () => jsonResponse(responseBody))
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function lastCall(fetchMock: ReturnType<typeof vi.fn>): [string, RequestInit] {
  return fetchMock.mock.calls[fetchMock.mock.calls.length - 1] as unknown as [string, RequestInit]
}

describe('PR #22/#24 feature endpoints (client)', () => {
  beforeEach(() => { vi.restoreAllMocks() })

  it('createApiKey sends the IP allowlist and expiry', async () => {
    const fetchMock = captureFetch({ secret: 's' })
    await api.createApiKey({
      project_id: 'p1', name: 'ci', scopes: ['read'],
      ip_allowlist: ['127.0.0.1'], expires_at: '2027-01-01T00:00:00.000Z',
    })
    const [url, init] = lastCall(fetchMock)
    expect(url).toBe('/api/v1/api-keys')
    expect(JSON.parse(String(init.body))).toMatchObject({
      ip_allowlist: ['127.0.0.1'], expires_at: '2027-01-01T00:00:00.000Z',
    })
  })

  it('address book: list unwraps items, policy PATCHes', async () => {
    const fetchMock = captureFetch({ items: [{ id: 'e1' }] })
    const rows = await api.listAddressBook('p1')
    expect(rows).toHaveLength(1)
    expect(lastCall(fetchMock)[0]).toBe('/api/v1/address-book?project_id=p1')

    const fetchMock2 = captureFetch({ project_id: 'p1', withdrawal_allowlist_required: true })
    await api.setAddressBookPolicy('p1', true)
    const [url, init] = lastCall(fetchMock2)
    expect(url).toBe('/api/v1/address-book/policy')
    expect(init.method).toBe('PATCH')
    expect(JSON.parse(String(init.body))).toEqual({ project_id: 'p1', required: true })
  })

  it('deposit policies: PUT carries project, asset and min_amount', async () => {
    const fetchMock = captureFetch({})
    await api.putDepositPolicy({ project_id: 'p1', asset_id: 'a1', min_amount: '250' })
    const [url, init] = lastCall(fetchMock)
    expect(url).toBe('/api/v1/deposit-policies')
    expect(init.method).toBe('PUT')
    expect(JSON.parse(String(init.body))).toEqual({ project_id: 'p1', asset_id: 'a1', min_amount: '250' })
  })

  it('sweep settings: policy, static destination, auto-sweep rule endpoints', async () => {
    const fetchMock = captureFetch({})
    await api.putSweepPolicy({
      project_id: 'p1', destination_mode: 'static',
      min_sweep_threshold: '0', leave_behind: '0', enabled: true,
    })
    expect(lastCall(fetchMock)[0]).toBe('/api/v1/sweep-policy')

    await api.putStaticDestination({ project_id: 'p1', network: 'ethereum', address: '0x1111111111111111111111111111111111111111' })
    expect(lastCall(fetchMock)[0]).toBe('/api/v1/sweep-destinations')

    await api.createAutoSweepRule({
      wallet_id: 'w1', network: 'ethereum', asset_id: 'a1',
      threshold_amount: '1000', enabled: true,
    })
    const [url, init] = lastCall(fetchMock)
    expect(url).toBe('/api/v1/auto-sweep-rules')
    expect(init.method).toBe('POST')
  })

  it('rotateWebhookSecret posts to the rotation endpoint', async () => {
    const fetchMock = captureFetch({ id: 'e1', signing_secret: 'whsec_new' })
    const out = await api.rotateWebhookSecret('e1')
    expect(out.signing_secret).toBe('whsec_new')
    const [url, init] = lastCall(fetchMock)
    expect(url).toBe('/api/v1/webhooks/endpoints/e1/rotate-secret')
    expect(init.method).toBe('POST')
  })
})

describe('auth store two-factor flow', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    sessionStorage.clear()
    vi.restoreAllMocks()
  })

  it('login pauses at the challenge; completeTotp finishes it', async () => {
    const fetchMock = vi.fn(async (input: unknown, _init?: RequestInit) => {
      void _init
      const url = String(input)
      if (url.endsWith('/auth/login')) {
        return jsonResponse({ token: null, access_token: null, requires_totp: true, mfa_token: 'signed-challenge' })
      }
      if (url.endsWith('/auth/2fa/verify')) {
        return jsonResponse({ access_token: 'test-token', user: { id: 'u1', email: 'a@example.com', totp_enabled: true } })
      }
      return jsonResponse({}, 404)
    })
    vi.stubGlobal('fetch', fetchMock)

    const store = useAuthStore()
    const outcome = await store.login('a@example.com', 'secret-password')
    expect(outcome).toBe('totp')
    expect(store.token).toBeNull()
    expect(sessionStorage.getItem('custodium.session')).toBeNull()

    await store.completeTotp('123456')
    expect(store.token).toBe('test-token')
    expect(sessionStorage.getItem('custodium.session')).toBe('test-token')
    const verifyCall = fetchMock.mock.calls.find((c) => String(c[0]).endsWith('/auth/2fa/verify'))
    expect(JSON.parse(String((verifyCall?.[1] as unknown as RequestInit).body))).toEqual({
      mfa_token: 'signed-challenge', code: '123456',
    })
  })
})
