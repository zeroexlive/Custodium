<script setup lang="ts">
import { computed, ref } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { api } from '@/api/client'
import type { Wallet, WalletStatus } from '@/api/types'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'
import Card from '@/components/ui/Card.vue'
import Badge from '@/components/ui/Badge.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import BalancesTable from './BalancesTable.vue'

const client = useQueryClient()
const projects = useQuery({ queryKey: ['projects'], queryFn: api.listProjects })
const projectId = ref('')

// Create-wallet form (creates a Phase 2 wallet record in the selected project)
const label = ref('')
const externalCustomerId = ref('')

// List filters — applied explicitly so typing does not spam the API
const customerFilter = ref('')
const statusFilter = ref('')
const appliedCustomer = ref('')
const appliedStatus = ref('')

const wallets = useQuery({
  queryKey: computed(() => ['wallets', projectId.value, appliedCustomer.value, appliedStatus.value]),
  queryFn: () => api.listWallets({
    project_id: projectId.value,
    ...(appliedCustomer.value ? { external_customer_id: appliedCustomer.value } : {}),
    ...(appliedStatus.value ? { status: appliedStatus.value } : {}),
  }),
  enabled: computed(() => projectId.value !== ''),
})

const projectBalances = useQuery({
  queryKey: computed(() => ['project-balances', projectId.value]),
  queryFn: () => api.getProjectBalances(projectId.value),
  enabled: computed(() => projectId.value !== ''),
})

// Per-wallet balances panel, shown when a wallet row is selected
const selectedWalletId = ref('')
const walletBalances = useQuery({
  queryKey: computed(() => ['wallet-balances', selectedWalletId.value]),
  queryFn: () => api.getWalletBalances(selectedWalletId.value),
  enabled: computed(() => selectedWalletId.value !== ''),
})
const selectedWallet = computed(() => (wallets.data.value ?? []).find((w) => w.id === selectedWalletId.value) ?? null)

const create = useMutation({
  mutationFn: () => api.createWallet({
    project_id: projectId.value,
    label: label.value.trim(),
    external_customer_id: externalCustomerId.value.trim(),
  }),
  onSuccess: async () => {
    label.value = ''; externalCustomerId.value = ''
    await client.invalidateQueries({ queryKey: ['wallets'] })
  },
})

const setStatus = useMutation({
  mutationFn: (args: { id: string; status: 'active' | 'frozen' | 'archived' }) =>
    api.setWalletStatus(args.id, args.status),
  onSuccess: async () => { await client.invalidateQueries({ queryKey: ['wallets'] }) },
})

function submitCreate(): void { if (projectId.value && label.value.trim()) create.mutate() }
function applyFilters(): void {
  appliedCustomer.value = customerFilter.value.trim()
  appliedStatus.value = statusFilter.value
}
function changeStatus(wallet: Wallet, status: 'active' | 'frozen' | 'archived'): void {
  const verb = status === 'frozen' ? 'Freeze' : status === 'active' ? 'Reactivate' : 'Archive'
  if (!window.confirm(`${verb} wallet "${wallet.label}"?`)) return
  setStatus.mutate({ id: wallet.id, status })
}
function statusTone(status: WalletStatus): 'success' | 'warning' | 'danger' | 'neutral' {
  return status === 'active' ? 'success' : status === 'provisioning' ? 'warning' : status === 'frozen' ? 'danger' : 'neutral'
}
</script>
<template>
  <div class="space-y-6">
    <h1 class="text-2xl font-semibold">Wallets</h1>
    <p class="text-sm text-ink-muted max-w-3xl">
      New wallets start in <span class="font-medium">provisioning</span> status. A wallet becomes active only when
      MPC threshold key generation completes (Phase 3) — the API refuses to activate a provisioning wallet
      before then, and no signing is possible in this phase.
    </p>

    <Card title="Project">
      <p v-if="projects.isPending.value">Loading…</p>
      <p v-else-if="projects.isError.value" role="alert" class="text-danger">Could not load projects.</p>
      <EmptyState v-else-if="!(projects.data.value ?? []).length" title="No projects yet"
        description="Create a project first — wallets belong to a project." />
      <div v-else class="space-y-1">
        <label for="wallet-project" class="block text-sm font-medium">Project</label>
        <select id="wallet-project" v-model="projectId" class="w-full rounded border border-gray-300 dark:border-gray-600 bg-surface px-3 py-2 text-sm">
          <option value="" disabled>Select a project</option>
          <option v-for="p in projects.data.value ?? []" :key="p.id" :value="p.id">{{ p.name }} ({{ p.environment }})</option>
        </select>
      </div>
    </Card>

    <template v-if="projectId">
      <Card title="Create wallet">
        <form class="space-y-4" @submit.prevent="submitCreate">
          <Input id="wallet-label" v-model="label" label="Wallet label" required />
          <Input id="wallet-customer" v-model="externalCustomerId" label="External customer ID (optional)"
            placeholder="Your own customer reference, e.g. cust_123" />
          <Button type="submit" :disabled="create.isPending.value">Create wallet</Button>
          <p v-if="create.isError.value" role="alert" class="text-sm text-danger">{{ (create.error.value as Error).message }}</p>
          <p class="text-xs text-ink-muted">Creates an MPC-threshold wallet record. Key generation runs in Phase 3;
            until then the wallet stays in provisioning status and holds no keys.</p>
        </form>
      </Card>

      <Card title="Wallets in this project">
        <form class="flex flex-wrap items-end gap-3 mb-4" @submit.prevent="applyFilters">
          <div class="grow min-w-48"><Input id="wallet-filter-customer" v-model="customerFilter" label="External customer ID" /></div>
          <div class="space-y-1">
            <label for="wallet-filter-status" class="block text-sm font-medium">Status</label>
            <select id="wallet-filter-status" v-model="statusFilter" class="rounded border border-gray-300 dark:border-gray-600 bg-surface px-3 py-2 text-sm">
              <option value="">Any status</option>
              <option value="provisioning">Provisioning</option>
              <option value="active">Active</option>
              <option value="frozen">Frozen</option>
              <option value="archived">Archived</option>
            </select>
          </div>
          <Button type="submit" variant="secondary">Filter</Button>
        </form>
        <p v-if="setStatus.isError.value" role="alert" class="text-sm text-danger mb-3">{{ (setStatus.error.value as Error).message }}</p>
        <p v-if="wallets.isPending.value">Loading…</p>
        <p v-else-if="wallets.isError.value" role="alert" class="text-danger">Could not load wallets.</p>
        <EmptyState v-else-if="!(wallets.data.value ?? []).length" title="No wallets found"
          description="No wallets match the current filters in this project. Create one above." />
        <div v-else class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead><tr class="text-left border-b">
              <th scope="col" class="py-2 pr-3">Label</th><th scope="col" class="py-2 pr-3">External customer</th>
              <th scope="col" class="py-2 pr-3">Status</th><th scope="col" class="py-2 pr-3">MPC key references</th>
              <th scope="col" class="py-2 pr-3">Policy</th><th scope="col" class="py-2 pr-3">Created</th>
              <th scope="col" class="py-2">Actions</th>
            </tr></thead>
            <tbody>
              <tr v-for="w in wallets.data.value" :key="w.id" class="border-b align-top">
                <td class="py-2 pr-3 font-medium">{{ w.label }}
                  <span class="block font-mono text-xs text-ink-muted">{{ w.id }}</span></td>
                <td class="py-2 pr-3">{{ w.external_customer_id || '—' }}</td>
                <td class="py-2 pr-3"><Badge :tone="statusTone(w.status)">{{ w.status }}</Badge></td>
                <td class="py-2 pr-3 font-mono text-xs">
                  <div>ECDSA: {{ w.key_generation.ecdsa_key_ref ?? 'not generated yet' }}</div>
                  <div>Ed25519: {{ w.key_generation.ed25519_key_ref ?? 'not generated yet' }}</div>
                </td>
                <td class="py-2 pr-3">{{ w.policy_name ? `${w.policy_name} (v${w.policy_version})` : '—' }}</td>
                <td class="py-2 pr-3 font-mono text-xs">{{ w.created_at ?? '—' }}</td>
                <td class="py-2">
                  <div class="flex flex-wrap gap-2">
                    <Button type="button" variant="secondary" @click="selectedWalletId = w.id">Balances</Button>
                    <Button v-if="w.status === 'active'" type="button" variant="danger"
                      :disabled="setStatus.isPending.value" @click="changeStatus(w, 'frozen')">Freeze</Button>
                    <Button v-if="w.status === 'frozen'" type="button" variant="secondary"
                      :disabled="setStatus.isPending.value" @click="changeStatus(w, 'active')">Reactivate</Button>
                    <Button v-if="w.status !== 'archived'" type="button" variant="danger"
                      :disabled="setStatus.isPending.value" @click="changeStatus(w, 'archived')">Archive</Button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </Card>

      <Card v-if="selectedWalletId" :title="`Balances — ${selectedWallet?.label ?? 'wallet'}`">
        <p v-if="walletBalances.isPending.value">Loading…</p>
        <p v-else-if="walletBalances.isError.value" role="alert" class="text-danger">Could not load wallet balances.</p>
        <EmptyState v-else-if="!(walletBalances.data.value?.items ?? []).length" title="No ledger balances"
          description="This wallet has no ledger accounts yet. Balances appear once assets are credited." />
        <BalancesTable v-else :items="walletBalances.data.value?.items ?? []" />
      </Card>

      <Card title="Project balances">
        <p class="text-sm text-ink-muted mb-3">
          Amounts are shown as raw integer base units exactly as stored in the ledger (for example,
          <span class="font-mono">1500000</span> with 6 decimals is 1.5 tokens). No fiat conversion is shown.
        </p>
        <p v-if="projectBalances.isPending.value">Loading…</p>
        <p v-else-if="projectBalances.isError.value" role="alert" class="text-danger">Could not load project balances.</p>
        <EmptyState v-else-if="!(projectBalances.data.value?.items ?? []).length" title="No ledger balances yet"
          description="This project has no ledger accounts yet. Balances appear here once assets are credited through deposits." />
        <BalancesTable v-else :items="projectBalances.data.value?.items ?? []" />
      </Card>
    </template>
  </div>
</template>
