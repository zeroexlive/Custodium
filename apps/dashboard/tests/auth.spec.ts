import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useAuthStore } from '@/stores/auth'

describe('auth store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    sessionStorage.clear()
    vi.restoreAllMocks()
  })

  it('login stores the returned token in sessionStorage and sets the user', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(
      JSON.stringify({ access_token: 'test-token', user: { id: 'u1', email: 'a@example.com' } }),
      { status: 200, headers: { 'Content-Type': 'application/json' } },
    )))
    const store = useAuthStore()
    await store.login('a@example.com', 'secret-password')
    expect(store.token).toBe('test-token')
    expect(store.user?.email).toBe('a@example.com')
    expect(sessionStorage.getItem('custodium.session')).toBe('test-token')
  })

  it('ensureSession is false with no token — cookies alone are not a session', async () => {
    const store = useAuthStore()
    expect(store.token).toBeNull()
    await expect(store.ensureSession()).resolves.toBe(false)
  })

  it('ensureSession validates a stored token against the API and rejects a bad one', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(
      JSON.stringify({ detail: 'unauthorized' }),
      { status: 401, headers: { 'Content-Type': 'application/json' } },
    )))
    const store = useAuthStore()
    store.persist('stale-token')
    await expect(store.ensureSession()).resolves.toBe(false)
    expect(store.token).toBeNull()
    expect(store.user).toBeNull()
  })

  it('ensureSession accepts a stored token the API confirms', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(
      JSON.stringify({ id: 'u1', email: 'a@example.com', is_staff: true }),
      { status: 200, headers: { 'Content-Type': 'application/json' } },
    )))
    const store = useAuthStore()
    store.persist('good-token')
    await expect(store.ensureSession()).resolves.toBe(true)
    expect(store.user?.email).toBe('a@example.com')
    expect(store.isPlatformAdmin).toBe(true)
  })

  it('logout clears the session even if the API call fails', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('nope', { status: 500 })))
    const store = useAuthStore()
    store.persist('test-token')
    await store.logout()
    expect(store.token).toBeNull()
    expect(sessionStorage.getItem('custodium.session')).toBeNull()
  })
})
