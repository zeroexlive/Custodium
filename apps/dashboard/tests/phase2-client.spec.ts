import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError } from '@/api/client'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

describe('Phase 2 API client', () => {
  beforeEach(() => { vi.restoreAllMocks() })

  it('listWallets builds the project + filter query string', async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ items: [], total: 0 }))
    vi.stubGlobal('fetch', fetchMock)
    const wallets = await api.listWallets({ project_id: 'p1', external_customer_id: 'cust_9', status: 'frozen' })
    expect(wallets).toEqual([])
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/v1/wallets?project_id=p1&external_customer_id=cust_9&status=frozen')
    expect(init.method).toBe('GET')
  })

  it('setWalletStatus PATCHes and surfaces the 409 provisioning message verbatim', async () => {
    const message = 'A provisioning wallet becomes active only when MPC key generation completes (Phase 3); it cannot be activated through the API.'
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ detail: message }, 409)))
    const err = await api.setWalletStatus('w1', 'active').catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect((err as ApiError).status).toBe(409)
    expect((err as ApiError).message).toBe(message)
  })

  it('getProjectBalances passes integer base-unit strings through untouched', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({
      project_id: 'p1', total: 1,
      items: [{
        asset_id: 'a1', symbol: 'USDT', network: 'ethereum', decimals: 6,
        accounts: { customer_available: '1500000' },
        available: '1500000', reserved: '0', pending: '0',
      }],
    })))
    const balances = await api.getProjectBalances('p1')
    expect(balances.items[0]?.available).toBe('1500000')
    expect(typeof balances.items[0]?.available).toBe('string')
  })

  it('checkBlacklist encodes address, network and organization', async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ blacklisted: true, matched_scopes: ['platform'], network: 'ethereum' }))
    vi.stubGlobal('fetch', fetchMock)
    const result = await api.checkBlacklist({ address: '0xAb C', network: 'ethereum', organization_id: 'o1' })
    expect(result.blacklisted).toBe(true)
    const [url] = fetchMock.mock.calls[0] as unknown as [string]
    expect(url).toBe('/api/v1/blacklist/check?address=0xAb+C&network=ethereum&organization_id=o1')
  })

  it('createBlacklistEntry posts the payload and returns the entry', async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ id: 'e1', scope: 'tenant' }, 201))
    vi.stubGlobal('fetch', fetchMock)
    await api.createBlacklistEntry({
      scope: 'tenant', organization_id: 'o1', network: 'tron',
      address: 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t', reason: 'reported stolen funds',
    })
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/v1/blacklist/entries')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body as string)).toMatchObject({ scope: 'tenant', organization_id: 'o1', network: 'tron' })
  })
})
