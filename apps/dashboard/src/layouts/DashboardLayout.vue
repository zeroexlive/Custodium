<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { RouterLink, RouterView, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import Icon from '@/components/ui/Icon.vue'

const auth = useAuthStore()
const router = useRouter()
const dark = ref(false)
const navQuery = ref('')

interface NavItem { to: string; label: string; icon: string }
interface NavGroup { title: string; items: NavItem[] }

/** Our own section names (Custodium domain), grouped like the reference layout. */
const groups: NavGroup[] = [
  {
    title: 'Main Menu',
    items: [
      { to: '/', label: 'Overview', icon: 'grid' },
      { to: '/organizations', label: 'Organizations', icon: 'building' },
      { to: '/projects', label: 'Projects', icon: 'folder' },
      { to: '/api-keys', label: 'API Keys', icon: 'key' },
      { to: '/security', label: 'Security', icon: 'shield' },
    ],
  },
  {
    title: 'Wallets & Activity',
    items: [
      { to: '/wallets', label: 'Wallets', icon: 'wallet' },
      { to: '/addresses', label: 'Addresses', icon: 'pin' },
      { to: '/transactions', label: 'Transaction Explorer', icon: 'search' },
      { to: '/assets', label: 'Assets & Networks', icon: 'coins' },
      { to: '/sweeps', label: 'Sweeps', icon: 'refresh' },
      { to: '/sweep-endpoint', label: 'Sweep Endpoint', icon: 'signal' },
      { to: '/sweep-settings', label: 'Sweep Settings', icon: 'sliders' },
      { to: '/address-book', label: 'Address Book', icon: 'book' },
      { to: '/deposit-policies', label: 'Deposit Policies', icon: 'clipboard' },
      { to: '/gas-station', label: 'Gas Station', icon: 'fuel' },
    ],
  },
  {
    title: 'General',
    items: [
      { to: '/blacklist', label: 'Blacklist', icon: 'ban' },
      { to: '/withdrawals', label: 'Withdrawals', icon: 'arrow-up-circle' },
      { to: '/webhooks', label: 'Webhooks', icon: 'webhook' },
      { to: '/team', label: 'Team', icon: 'users' },
      { to: '/billing', label: 'Billing', icon: 'card' },
      { to: '/audit', label: 'Audit Logs', icon: 'file' },
    ],
  },
]

const visibleGroups = computed(() => {
  const q = navQuery.value.trim().toLowerCase()
  if (!q) return groups
  return groups
    .map((g) => ({ ...g, items: g.items.filter((i) => i.label.toLowerCase().includes(q)) }))
    .filter((g) => g.items.length > 0)
})

function applyTheme(): void {
  document.documentElement.classList.toggle('dark', dark.value)
  try { localStorage.setItem('custodium.theme', dark.value ? 'dark' : 'light') } catch { /* ignore */ }
}
function toggleTheme(): void { dark.value = !dark.value; applyTheme() }
onMounted(() => {
  try { dark.value = localStorage.getItem('custodium.theme') === 'dark' } catch { dark.value = false }
  applyTheme()
  void auth.fetchMe()
})
async function logout(): Promise<void> { await auth.logout(); await router.push('/login') }
</script>
<template>
  <div class="min-h-screen p-3 md:p-6">
    <div class="mx-auto flex min-h-[calc(100vh-3rem)] max-w-[1440px] flex-col overflow-hidden rounded-shell bg-surface shadow-shell md:flex-row">
      <aside class="shrink-0 text-ink md:w-72 md:border-r md:border-black/5" aria-label="Primary">
        <div class="flex items-center justify-between px-5 pt-6 pb-4">
          <span class="flex items-center gap-2.5 text-xl font-bold tracking-tight">
            <span class="flex h-9 w-9 items-center justify-center rounded-xl bg-brand-600 text-white shadow-card" aria-hidden="true"><Icon name="shield" :size="20" /></span>
            Custodium
          </span>
          <button type="button" class="rounded-full bg-surface-muted px-3 py-1.5 text-xs font-medium text-ink-muted" :aria-pressed="dark" aria-label="Toggle dark mode" @click="toggleTheme">
            <span class="inline-flex items-center gap-1.5"><Icon :name="dark ? 'sun' : 'moon'" :size="14" />{{ dark ? 'Light' : 'Dark' }}</span>
          </button>
        </div>

        <div class="px-5 pb-2">
          <label class="sr-only" for="nav-search">Search sections</label>
          <div class="flex items-center gap-2 rounded-full bg-surface-muted px-4 py-2.5">
            <span aria-hidden="true" class="text-ink-muted">⌕</span>
            <input id="nav-search" v-model="navQuery" type="search" placeholder="Search"
              class="w-full bg-transparent text-sm outline-none placeholder:text-ink-muted" />
            <kbd class="rounded-md bg-surface px-1.5 py-0.5 text-[10px] font-semibold text-ink-muted shadow-card" aria-hidden="true">⌘K</kbd>
          </div>
        </div>

        <nav aria-label="Dashboard sections" class="px-3 pb-4">
          <div v-for="group in visibleGroups" :key="group.title" class="mt-4">
            <p class="px-3 pb-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-muted">{{ group.title }}</p>
            <ul class="space-y-1">
              <li v-for="item in group.items" :key="item.to">
                <RouterLink :to="item.to"
                  class="flex items-center gap-2.5 rounded-xl px-3.5 py-2.5 text-sm text-ink-muted transition hover:bg-surface-muted hover:text-ink"
                  active-class="!bg-gray-900 !text-white font-medium shadow-card dark:!bg-white dark:!text-gray-900">
                  <Icon :name="item.icon" :size="18" />
                  {{ item.label }}
                </RouterLink>
              </li>
            </ul>
          </div>
          <p v-if="visibleGroups.length === 0" class="px-3 py-2 text-sm text-ink-muted">No sections match your search.</p>
        </nav>

        <div class="mt-auto p-4">
          <div class="rounded-card bg-surface-muted p-4">
            <p class="text-sm font-semibold">Account</p>
            <p v-if="auth.user" class="mb-3 truncate text-sm text-ink-muted">{{ auth.user.email }}</p>
            <p v-else class="mb-3 text-sm text-ink-muted">Not signed in</p>
            <button type="button" class="w-full rounded-xl border border-gray-300 bg-surface px-4 py-2 text-sm font-medium transition hover:bg-gray-50 dark:border-gray-600 dark:hover:bg-gray-800" @click="logout">
              <span class="inline-flex items-center justify-center gap-2"><Icon name="logout" :size="16" /> Log out</span>
            </button>
          </div>
        </div>
      </aside>

      <main class="min-w-0 flex-1 bg-surface-muted/60 p-4 md:p-8 dark:bg-transparent" id="main-content">
        <RouterView />
      </main>
    </div>
  </div>
</template>
