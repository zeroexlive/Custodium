<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { RouterLink, RouterView, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()
const dark = ref(false)
const navQuery = ref('')

interface NavItem { to: string; label: string }
interface NavGroup { title: string; items: NavItem[] }

/** Our own section names (Custodium domain), grouped like the reference layout. */
const groups: NavGroup[] = [
  {
    title: 'Main Menu',
    items: [
      { to: '/', label: 'Overview' },
      { to: '/organizations', label: 'Organizations' },
      { to: '/projects', label: 'Projects' },
      { to: '/api-keys', label: 'API Keys' },
    ],
  },
  {
    title: 'Wallets & Activity',
    items: [
      { to: '/wallets', label: 'Wallets' },
      { to: '/addresses', label: 'Addresses' },
      { to: '/transactions', label: 'Transaction Explorer' },
      { to: '/assets', label: 'Assets & Networks' },
      { to: '/sweeps', label: 'Sweeps' },
      { to: '/sweep-endpoint', label: 'Sweep Endpoint' },
      { to: '/gas-station', label: 'Gas Station' },
    ],
  },
  {
    title: 'General',
    items: [
      { to: '/blacklist', label: 'Blacklist' },
      { to: '/withdrawals', label: 'Withdrawals' },
      { to: '/webhooks', label: 'Webhooks' },
      { to: '/team', label: 'Team' },
      { to: '/billing', label: 'Billing' },
      { to: '/webhooks', label: 'Webhooks' },
      { to: '/audit', label: 'Audit Logs' },
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
            <span class="flex h-9 w-9 items-center justify-center rounded-xl bg-brand-600 font-black text-white shadow-card" aria-hidden="true">C</span>
            Custodium
          </span>
          <button type="button" class="rounded-full bg-surface-muted px-3 py-1.5 text-xs font-medium text-ink-muted" :aria-pressed="dark" aria-label="Toggle dark mode" @click="toggleTheme">
            {{ dark ? '☀ Light' : '☾ Dark' }}
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
                  class="block rounded-xl px-3.5 py-2.5 text-sm text-ink-muted transition hover:bg-surface-muted hover:text-ink"
                  active-class="!bg-gray-900 !text-white font-medium shadow-card dark:!bg-white dark:!text-gray-900">
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
              Log out
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
