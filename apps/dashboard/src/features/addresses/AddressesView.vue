<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { api } from '@/api/client'
import Card from '@/components/ui/Card.vue'
import Button from '@/components/ui/Button.vue'
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

const queryClient = useQueryClient()
const createNetwork = ref('ethereum')
const createdAddress = ref('')
const createError = ref('')
const create = useMutation({
  mutationFn: () => api.createWalletAddress(walletId.value, createNetwork.value),
  onSuccess: (data) => {
    createdAddress.value = data.address
    createError.value = ''
    void queryClient.invalidateQueries({ queryKey: ['wallet-addresses', walletId.value] })
  },
  onError: (e) => { createError.value = e instanceof Error ? e.message : 'Request failed' },
})

// Deposit addresses by customer UID — manual mode: the customer
// types the end user's UID from their own platform plus the chain,
// and receives that user's deposit address (the customer's server
// can do exactly the same through the API).
const uidInput = ref('')
const uidNetwork = ref('ethereum')
const uidResult = ref('')
const uidError = ref('')
const createByUid = useMutation({
  mutationFn: () => api.createDepositAddress({
    project_id: projectId.value,
    external_customer_id: uidInput.value.trim(),
    network: uidNetwork.value,
  }),
  onSuccess: (data) => {
    uidResult.value = `${data.address} (wallet ${data.wallet_status})`
    uidError.value = ''
    void queryClient.invalidateQueries({ queryKey: ['deposit-address-search'] })
  },
  onError: (e) => { uidError.value = e instanceof Error ? e.message : 'Request failed'; uidResult.value = '' },
})

// Address search — by address (finds the owning UID) or by UID
// (lists every address for that user), with status and the deposit
// summary used for troubleshooting.
const searchAddress = ref('')
const searchUid = ref('')
const searchParams = ref<{ address?: string; external_customer_id?: string } | null>(null)
const searchResults = useQuery({
  queryKey: computed(() => ['deposit-address-search', projectId.value, searchParams.value]),
  queryFn: () => api.listDepositAddresses({ project_id: projectId.value, ...(searchParams.value ?? {}) }),
  enabled: computed(() => projectId.value !== '' && searchParams.value !== null),
})
function runSearch(): void {
  searchParams.value = {
    address: searchAddress.value.trim() || undefined,
    external_customer_id: searchUid.value.trim() || undefined,
  }
}
</script>
<template>
  <div class="space-y-6">
    <h1 class="text-2xl font-semibold">Addresses</h1>

    <Card title="Create or get an address">
      <p class="text-sm text-ink-muted">
        Returns the wallet's address for a network — deriving and recording it from the
        wallet's group public key when it does not exist yet. A wallet that has not been
        provisioned has no key and honestly returns an error instead of a fabricated address.
        Select a project and wallet below first.
      </p>
      <div class="mt-3 flex flex-wrap items-end gap-3">
        <label class="text-sm">
          <span class="mb-1 block text-ink-muted">Network</span>
          <select v-model="createNetwork" class="rounded-lg border border-line bg-white px-3 py-2">
            <option v-for="n in networks.data.value ?? []" :key="n.slug" :value="n.slug">{{ n.slug }}</option>
          </select>
        </label>
        <Button :disabled="!walletId || create.isPending.value" @click="create.mutate()">Create / get address</Button>
        <p v-if="createdAddress" class="font-mono text-sm break-all">{{ createdAddress }}</p>
      </div>
      <p v-if="createError" role="alert" class="mt-2 text-sm text-danger">{{ createError }}</p>
    </Card>

    <Card title="Deposit address by customer UID">
      <p class="text-sm text-ink-muted">
        Manual mode: enter the end user's UID from your own platform and the
        chain — the user's wallet is found or created and its deposit address
        for that chain is returned. (Your server can do the same via
        <span class="font-mono text-xs">POST /deposit-addresses</span>.) Uses the
        project selected below; a wallet that has not been provisioned yet
        returns an error instead of a fabricated address.
      </p>
      <div class="mt-3 flex flex-wrap items-end gap-3">
        <label class="text-sm">
          <span class="mb-1 block text-ink-muted">User UID</span>
          <input v-model="uidInput" type="text" placeholder="e.g. user-12345"
            class="rounded-lg border border-line bg-white px-3 py-2" />
        </label>
        <label class="text-sm">
          <span class="mb-1 block text-ink-muted">Network</span>
          <select v-model="uidNetwork" class="rounded-lg border border-line bg-white px-3 py-2">
            <option v-for="n in networks.data.value ?? []" :key="n.slug" :value="n.slug">{{ n.slug }}</option>
          </select>
        </label>
        <Button :disabled="!projectId || !uidInput.trim() || createByUid.isPending.value" @click="createByUid.mutate()">
          Get deposit address
        </Button>
        <p v-if="uidResult" class="font-mono text-sm break-all">{{ uidResult }}</p>
      </div>
      <p v-if="uidError" role="alert" class="mt-2 text-sm text-danger">{{ uidError }}</p>
    </Card>

    <Card title="Search addresses">
      <p class="text-sm text-ink-muted">
        Search by address to find which customer UID it belongs to, or by UID
        to list all of that user's addresses — with each address's status and
        deposit summary for troubleshooting. Uses the project selected below.
      </p>
      <div class="mt-3 flex flex-wrap items-end gap-3">
        <label class="text-sm">
          <span class="mb-1 block text-ink-muted">Address contains</span>
          <input v-model="searchAddress" type="text" placeholder="0x…"
            class="rounded-lg border border-line bg-white px-3 py-2 font-mono" />
        </label>
        <label class="text-sm">
          <span class="mb-1 block text-ink-muted">Customer UID</span>
          <input v-model="searchUid" type="text" placeholder="user-12345"
            class="rounded-lg border border-line bg-white px-3 py-2" />
        </label>
        <Button :disabled="!projectId || searchResults.isFetching.value" @click="runSearch()">Search</Button>
      </div>
      <div v-if="searchParams" class="mt-4">
        <p v-if="searchResults.isPending.value">Loading…</p>
        <p v-else-if="searchResults.isError.value" role="alert" class="text-sm text-danger">Search failed.</p>
        <EmptyState v-else-if="!(searchResults.data.value ?? []).length" title="No addresses found"
          description="No deposit addresses in this project match that search." />
        <div v-else class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead><tr class="text-left border-b">
              <th scope="col" class="py-2 pr-3">Network</th><th scope="col" class="py-2 pr-3">Address</th>
              <th scope="col" class="py-2 pr-3">Customer UID</th><th scope="col" class="py-2 pr-3">Wallet status</th>
              <th scope="col" class="py-2 pr-3">Status</th><th scope="col" class="py-2 pr-3">Deposits</th>
              <th scope="col" class="py-2">Credited totals</th>
            </tr></thead>
            <tbody>
              <tr v-for="a in searchResults.data.value" :key="a.id" class="border-b align-top">
                <td class="py-2 pr-3">{{ a.network }}</td>
                <td class="py-2 pr-3 font-mono text-xs break-all">{{ a.address }}</td>
                <td class="py-2 pr-3">{{ a.external_customer_id || '—' }}</td>
                <td class="py-2 pr-3"><Badge :tone="a.wallet_status === 'active' ? 'success' : 'neutral'">{{ a.wallet_status }}</Badge></td>
                <td class="py-2 pr-3"><Badge :tone="a.status === 'active' ? 'success' : 'neutral'">{{ a.status }}</Badge></td>
                <td class="py-2 pr-3">{{ a.deposits.count }}<span v-if="a.deposits.held_count"> ({{ a.deposits.held_count }} held)</span></td>
                <td class="py-2 font-mono text-xs">
                  <span v-if="a.deposits.credited_totals.length">
                    {{ a.deposits.credited_totals.map((t) => `${t.amount} ${t.asset}`).join(', ') }}
                  </span><span v-else>—</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
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
