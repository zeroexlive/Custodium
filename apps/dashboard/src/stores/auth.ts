import { defineStore } from 'pinia'
import { api, setAuthToken } from '@/api/client'
import type { User } from '@/api/types'

const STORAGE_KEY = 'custodium.session'

interface AuthState { user: User | null; token: string | null; loading: boolean; error: string | null; mfaToken: string | null }

function restore(): string | null {
  try { return sessionStorage.getItem(STORAGE_KEY) } catch { return null }
}

export const useAuthStore = defineStore('auth', {
  state: (): AuthState => ({ user: null, token: restore(), loading: false, error: null, mfaToken: null }),
  getters: {
    isAuthenticated: (s): boolean => s.token !== null || s.user !== null,
    /** Platform owner / global administrators manage customer accounts. */
    isPlatformAdmin: (s): boolean => Boolean(s.user?.is_staff || s.user?.is_superuser),
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
    /** Returns 'totp' when the account requires a two-factor code
     *  (complete with completeTotp), otherwise 'done'. */
    async login(email: string, password: string): Promise<'done' | 'totp'> {
      this.loading = true; this.error = null
      try {
        const res = await api.login({ email, password })
        if (res.requires_totp) {
          this.mfaToken = res.mfa_token ?? null
          return 'totp'
        }
        if (res.access_token ?? res.token) this.persist(res.access_token ?? res.token ?? null)
        this.user = res.user ?? (await api.me())
        return 'done'
      } catch (e) {
        this.error = e instanceof Error ? e.message : 'Login failed'
        throw e
      } finally { this.loading = false }
    },
    async completeTotp(code: string): Promise<void> {
      if (!this.mfaToken) throw new Error('No two-factor challenge in progress')
      this.loading = true; this.error = null
      try {
        const res = await api.verifyTotp({ mfa_token: this.mfaToken, code })
        if (res.access_token ?? res.token) this.persist(res.access_token ?? res.token ?? null)
        this.user = res.user ?? (await api.me())
        this.mfaToken = null
      } catch (e) {
        this.error = e instanceof Error ? e.message : 'Two-factor verification failed'
        throw e
      } finally { this.loading = false }
    },
    async fetchMe(): Promise<void> {
      if (!this.token) return
      try { this.user = await api.me() } catch { this.persist(null); this.user = null }
    },
    /** The dashboard's authentication gate: a session counts only
     *  when the server confirms it. A stored token is validated
     *  against /me; anything else (no token, an expired or revoked
     *  token, stray cookies) is NOT a session. */
    async ensureSession(): Promise<boolean> {
      if (this.user) return true
      if (!this.token) return false
      await this.fetchMe()
      return this.user !== null
    },
    async logout(): Promise<void> {
      try { await api.logout() } catch { /* local logout must still succeed */ }
      this.persist(null); this.user = null
    },
  },
})
