<script setup lang="ts">
import { computed, ref } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { api } from '@/api/client'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import Badge from '@/components/ui/Badge.vue'
import EmptyState from '@/components/ui/EmptyState.vue'

const client = useQueryClient()
const projectId = ref('')
const projects = useQuery({ queryKey: ['projects'], queryFn: api.listProjects })
const wallets = useQuery({
  queryKey: computed(() => ['wallets', projectId.value]),
  queryFn: () => api.listWallets({ project_id: projectId.value }),
  enabled: computed(() => projectId.value !== ''),
})
const networks = useQuery({ queryKey: ['networks'], queryFn: api.listNetworks })
const stations = useQuery({
  queryKey: computed(() => ['gas-stations', projectId.value]),
  queryFn: () => api.listGasStations(projectId.value),
  enabled: computed(() => projectId.value !== ''),
})
const topups = useQuery({
  queryKey: computed(() => ['gas-topups', projectId.value]),
  queryFn: () => api.listGasTopups(projectId.value),
  enabled: computed(() => projectId.value !== ''),
})

const form = ref({
  network: 'ethereum', funding_wallet_id: '',
  min_native_balance: '500000000000000', topup_amount: '2000000000000000',
  max_topups_per_day: 100, enabled: true,
})
const formError = ref('')
const save = useMutation({
  mutationFn: () => api.putGasStation({ project_id: projectId.value, ...form.value }),
  onSuccess: () => {
    formError.value = ''
    void client.invalidateQueries({ queryKey: ['gas-stations', projectId.value] })
  },
  onError: (e) => { formError.value = e instanceof Error ? e.message : 'Request failed' },
})

function tone(status: string): 'neutral' | 'success' | 'warning' | 'danger' {
  if (status === 'confirmed') return 'success'
  if (status === 'failed') return 'danger'
  if (status === 'broadcast') return 'warning'
  return 'neutral'
}
</script>

<template>
  <div class="space-y-6">
    <div>
      <h1 class="text-2xl font-semibold">Gas station</h1>
      <p class="text-sm text-ink-muted">
        Token transfers pay network fees in the chain's native coin. When a wallet's on-chain
        native balance falls below the threshold, the station tops it up from the project's
        funding wallet and the withdrawal or sweep continues automatically on the next pass.
        Amounts are integer base units of the native asset.
      </p>
    </div>

    <Card>
      <div class="flex flex-wrap items-end gap-3">
        <label class="text-sm">
          <span class="mb-1 block text-ink-muted">Project</span>
          <select v-model="projectId" class="rounded-lg border border-line bg-white px-3 py-2">
            <option value="">Select a project</option>
            <option v-for="p in projects.data.value ?? []" :key="p.id" :value="p.id">{{ p.name }}</option>
          </select>
        </label>
      </div>
    </Card>

    <template v-if="projectId">
      <Card>
        <h2 class="mb-3 font-medium">Configure a station</h2>
        <div class="flex flex-wrap items-end gap-3">
          <label class="text-sm">
            <span class="mb-1 block text-ink-muted">Network</span>
            <select v-model="form.network" class="rounded-lg border border-line bg-white px-3 py-2">
              <option v-for="n in networks.data.value ?? []" :key="n.slug" :value="n.slug">{{ n.slug }}</option>
            </select>
          </label>
          <label class="text-sm">
            <span class="mb-1 block text-ink-muted">Funding wallet</span>
            <select v-model="form.funding_wallet_id" class="rounded-lg border border-line bg-white px-3 py-2">
              <option value="">Select a wallet</option>
              <option v-for="w in wallets.data.value ?? []" :key="w.id" :value="w.id">
                {{ w.label }} ({{ w.external_customer_id || w.id.slice(0, 8) }})
              </option>
            </select>
          </label>
          <label class="text-sm">
            <span class="mb-1 block text-ink-muted">Min native balance</span>
            <input v-model="form.min_native_balance" class="w-52 rounded-lg border border-line bg-white px-3 py-2" />
          </label>
          <label class="text-sm">
            <span class="mb-1 block text-ink-muted">Top-up amount</span>
            <input v-model="form.topup_amount" class="w-52 rounded-lg border border-line bg-white px-3 py-2" />
          </label>
          <label class="text-sm">
            <span class="mb-1 block text-ink-muted">Max top-ups / day</span>
            <input v-model.number="form.max_topups_per_day" type="number" min="0" class="w-28 rounded-lg border border-line bg-white px-3 py-2" />
          </label>
          <label class="flex items-center gap-2 text-sm">
            <input v-model="form.enabled" type="checkbox" /> Enabled
          </label>
          <Button :disabled="save.isPending.value || !form.funding_wallet_id" @click="save.mutate()">Save station</Button>
        </div>
        <p v-if="formError" class="mt-2 text-sm text-danger">{{ formError }}</p>
      </Card>

      <Card>
        <h2 class="mb-3 font-medium">Configured stations</h2>
        <EmptyState
          v-if="(stations.data.value ?? []).length === 0"
          title="No gas stations yet"
          description="Configure a station above to enable automatic native-coin top-ups for this project."
        />
        <table v-else class="w-full text-sm">
          <thead>
            <tr class="text-left text-ink-muted">
              <th class="py-1">Network</th><th>Funding wallet</th><th>Top-up address</th><th>Min balance</th>
              <th>Top-up</th><th>Daily cap</th><th>Enabled</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="s in stations.data.value ?? []" :key="s.id" class="border-t border-line">
              <td class="py-2">{{ s.network }}</td>
              <td>{{ s.funding_wallet_id.slice(0, 8) }}…</td>
              <td class="font-mono break-all">{{ s.top_up_address ?? '— (funding wallet not provisioned)' }}</td>
              <td>{{ s.min_native_balance }}</td>
              <td>{{ s.topup_amount }}</td>
              <td>{{ s.max_topups_per_day }}</td>
              <td><Badge :tone="s.enabled ? 'success' : 'neutral'">{{ s.enabled ? 'enabled' : 'disabled' }}</Badge></td>
            </tr>
          </tbody>
        </table>
      </Card>

      <Card>
        <h2 class="mb-3 font-medium">Recent top-ups</h2>
        <EmptyState
          v-if="(topups.data.value ?? []).length === 0"
          title="No top-ups yet"
          description="Top-ups appear here when a withdrawal or sweep waits for gas."
        />
        <table v-else class="w-full text-sm">
          <thead>
            <tr class="text-left text-ink-muted">
              <th class="py-1">When</th><th>Network</th><th>Amount</th><th>Status</th><th>Operation</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="t in topups.data.value ?? []" :key="t.id" class="border-t border-line">
              <td class="py-2">{{ new Date(t.created_at).toLocaleString() }}</td>
              <td>{{ t.network }}</td>
              <td>{{ t.amount }}</td>
              <td><Badge :tone="tone(t.status)">{{ t.status }}</Badge></td>
              <td>{{ t.operation_key }}</td>
            </tr>
          </tbody>
        </table>
      </Card>
    </template>
  </div>
</template>
