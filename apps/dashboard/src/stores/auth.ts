import { defineStore } from 'pinia'
import { api, setAuthToken } from '@/api/client'
import type { User } from '@/api/types'

const STORAGE_KEY = 'custodium.session'

interface AuthState { user: User | null; token: string | null; loading: boolean; error: string | null }

function restore(): string | null {
  try { return sessionStorage.getItem(STORAGE_KEY) } catch { return null }
}

export const useAuthStore = defineStore('auth', {
  state: (): AuthState => ({ user: null, token: restore(), loading: false, error: null }),
  getters: {
    isAuthenticated: (s): boolean => s.token !== null || s.user !== null,
  },
  actions: {
    init(): void { setAuthToken(this.token) },
    persist(token: string | null): void {
      this.token = token
      setAuthToken(token)
      try {
        if (token) sessionStorage.setItem(STORAGE_KEY, token)
        else sessionStorage.removeItem(STORAGE_KEY)
      } catch { /* sessionStorage may be unavailable; in-memory session still works */ }
    },
    async login(email: string, password: string): Promise<void> {
      this.loading = true; this.error = null
      try {
        const res = await api.login({ email, password })
        if (res.access_token ?? res.token) this.persist(res.access_token ?? res.token ?? null)
        this.user = res.user ?? (await api.me())
      } catch (e) {
        this.error = e instanceof Error ? e.message : 'Login failed'
        throw e
      } finally { this.loading = false }
    },
    async register(email: string, password: string, displayName?: string): Promise<void> {
      this.loading = true; this.error = null
      try {
        const res = await api.register({ email, password, display_name: displayName })
        if (res.access_token ?? res.token) this.persist(res.access_token ?? res.token ?? null)
        this.user = res.user ?? null
      } catch (e) {
        this.error = e instanceof Error ? e.message : 'Registration failed'
        throw e
      } finally { this.loading = false }
    },
    async fetchMe(): Promise<void> {
      if (!this.token) return
      try { this.user = await api.me() } catch { this.persist(null); this.user = null }
    },
    async logout(): Promise<void> {
      try { await api.logout() } catch { /* local logout must still succeed */ }
      this.persist(null); this.user = null
    },
  },
})
