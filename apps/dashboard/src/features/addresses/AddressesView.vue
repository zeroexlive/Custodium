<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useQuery } from '@tanstack/vue-query'
import { api } from '@/api/client'
import Card from '@/components/ui/Card.vue'
import Badge from '@/components/ui/Badge.vue'
import EmptyState from '@/components/ui/EmptyState.vue'

const projectId = ref('')
const walletId = ref('')
const networkSlug = ref('')

const projects = useQuery({ queryKey: ['projects'], queryFn: api.listProjects })
const networks = useQuery({ queryKey: ['networks'], queryFn: api.listNetworks })
const wallets = useQuery({
  queryKey: computed(() => ['wallets', projectId.value]),
  queryFn: () => api.listWallets({ project_id: projectId.value }),
  enabled: computed(() => projectId.value !== ''),
})
const addresses = useQuery({
  queryKey: computed(() => ['wallet-addresses', walletId.value, networkSlug.value]),
  queryFn: () => api.listWalletAddresses(walletId.value, networkSlug.value || undefined),
  enabled: computed(() => walletId.value !== ''),
})

watch(projectId, () => { walletId.value = '' })
</script>
<template>
  <div class="space-y-6">
    <h1 class="text-2xl font-semibold">Addresses</h1>

    <Card title="Address generation — arrives with the MPC phase">
      <p class="text-sm text-ink-muted">
        Deriving a deposit address requires MPC threshold key generation (Phase 3) and per-chain
        integration (Phase 4 onwards). Until then the API deliberately answers address creation with
        <span class="font-mono">501 Not Implemented</span> and no address is fabricated. Addresses that
        already exist for a wallet are listed below, read-only.
      </p>
    </Card>

    <Card title="Select wallet">
      <div class="grid gap-4 md:grid-cols-3">
        <div class="space-y-1">
          <label for="addr-project" class="block text-sm font-medium">Project</label>
          <select id="addr-project" v-model="projectId" class="w-full rounded border border-gray-300 dark:border-gray-600 bg-surface px-3 py-2 text-sm">
            <option value="" disabled>Select a project</option>
            <option v-for="p in projects.data.value ?? []" :key="p.id" :value="p.id">{{ p.name }} ({{ p.environment }})</option>
          </select>
          <p v-if="projects.isError.value" role="alert" class="text-sm text-danger">Could not load projects.</p>
        </div>
        <div class="space-y-1">
          <label for="addr-wallet" class="block text-sm font-medium">Wallet</label>
          <select id="addr-wallet" v-model="walletId" :disabled="!projectId" class="w-full rounded border border-gray-300 dark:border-gray-600 bg-surface px-3 py-2 text-sm disabled:opacity-50">
            <option value="" disabled>Select a wallet</option>
            <option v-for="w in wallets.data.value ?? []" :key="w.id" :value="w.id">
              {{ w.label }}{{ w.external_customer_id ? ` — ${w.external_customer_id}` : '' }} ({{ w.status }})
            </option>
          </select>
          <p v-if="projectId && wallets.isError.value" role="alert" class="text-sm text-danger">Could not load wallets.</p>
          <p v-else-if="projectId && !wallets.isPending.value && !(wallets.data.value ?? []).length" class="text-sm text-ink-muted">
            This project has no wallets yet — create one on the Wallets page.
          </p>
        </div>
        <div class="space-y-1">
          <label for="addr-network" class="block text-sm font-medium">Network filter</label>
          <select id="addr-network" v-model="networkSlug" :disabled="!walletId" class="w-full rounded border border-gray-300 dark:border-gray-600 bg-surface px-3 py-2 text-sm disabled:opacity-50">
            <option value="">All networks</option>
            <option v-for="n in networks.data.value ?? []" :key="n.id" :value="n.slug">{{ n.name }}{{ n.is_testnet ? ' (testnet)' : '' }}</option>
          </select>
        </div>
      </div>
    </Card>

    <Card v-if="walletId" title="Addresses">
      <p v-if="addresses.isPending.value">Loading…</p>
      <p v-else-if="addresses.isError.value" role="alert" class="text-danger">Could not load addresses.</p>
      <EmptyState v-else-if="!(addresses.data.value ?? []).length" title="No addresses derived yet"
        description="This wallet has no addresses. Address derivation becomes available with MPC key generation in Phase 3 — nothing is generated or simulated in the meantime." />
      <div v-else class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead><tr class="text-left border-b">
            <th scope="col" class="py-2 pr-3">Network</th><th scope="col" class="py-2 pr-3">Address</th>
            <th scope="col" class="py-2 pr-3">Derivation path</th><th scope="col" class="py-2 pr-3">Index</th>
            <th scope="col" class="py-2 pr-3">Memo</th><th scope="col" class="py-2 pr-3">Status</th>
            <th scope="col" class="py-2">Created</th>
          </tr></thead>
          <tbody>
            <tr v-for="a in addresses.data.value" :key="a.id" class="border-b align-top">
              <td class="py-2 pr-3">{{ a.network }}</td>
              <td class="py-2 pr-3 font-mono text-xs break-all">{{ a.address }}</td>
              <td class="py-2 pr-3 font-mono text-xs">{{ a.derivation_path }}</td>
              <td class="py-2 pr-3">{{ a.derivation_index }}</td>
              <td class="py-2 pr-3">{{ a.memo ?? '—' }}</td>
              <td class="py-2 pr-3"><Badge :tone="a.status === 'active' ? 'success' : 'neutral'">{{ a.status }}</Badge></td>
              <td class="py-2 font-mono text-xs">{{ a.created_at ?? '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </Card>
  </div>
</template>
