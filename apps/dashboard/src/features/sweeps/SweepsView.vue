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
const assets = useQuery({ queryKey: ['assets'], queryFn: api.listAssets })
const sweeps = useQuery({
  queryKey: computed(() => ['sweeps', projectId.value]),
  queryFn: () => api.listSweeps(projectId.value),
  enabled: computed(() => projectId.value !== ''),
})

const form = ref({ wallet_id: '', network: '', asset_id: '' })
const formError = ref('')
const networkAssets = computed(() =>
  (assets.data.value ?? []).filter((a) => a.network === form.value.network),
)
const create = useMutation({
  mutationFn: () =>
    api.createSweep({ ...form.value }, `dash-swp-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`),
  onSuccess: () => {
    formError.value = ''
    void client.invalidateQueries({ queryKey: ['sweeps', projectId.value] })
  },
  onError: (e) => { formError.value = e instanceof Error ? e.message : 'Request failed' },
})
const decide = useMutation({
  mutationFn: (args: { id: string; decision: 'approve' | 'reject' }) =>
    args.decision === 'approve' ? api.approveSweep(args.id) : api.rejectSweep(args.id),
  onSuccess: () => void client.invalidateQueries({ queryKey: ['sweeps', projectId.value] }),
})

function tone(status: string): 'neutral' | 'success' | 'warning' | 'danger' {
  if (status === 'completed') return 'success'
  if (['failed', 'rejected', 'resolution_failed', 'policy_denied'].includes(status)) return 'danger'
  if (status === 'awaiting_approval') return 'warning'
  return 'neutral'
}
</script>

<template>
  <div class="space-y-6">
    <div>
      <h1 class="text-2xl font-semibold">Sweeps</h1>
      <p class="text-sm text-ink-muted">
        A sweep consolidates a wallet's available balance to the destination returned by your
        registered resolver endpoint — resolved fresh per sweep, snapshotted immutably, and never
        taken from the request. Configure the endpoint under “Sweep Endpoint”.
      </p>
    </div>

    <Card>
      <label class="text-sm font-medium">Project</label>
      <select v-model="projectId" class="mt-1 block w-full rounded-lg border px-3 py-2">
        <option value="">Select a project…</option>
        <option v-for="p in projects.data.value ?? []" :key="p.id" :value="p.id">
          {{ p.name }} ({{ p.environment }})
        </option>
      </select>
    </Card>

    <template v-if="projectId">
      <Card>
        <h2 class="font-medium">New sweep</h2>
        <div class="mt-3 grid gap-3 md:grid-cols-3">
          <select v-model="form.wallet_id" class="rounded-lg border px-3 py-2">
            <option value="">Wallet…</option>
            <option v-for="w in wallets.data.value ?? []" :key="w.id" :value="w.id">{{ w.label }}</option>
          </select>
          <select v-model="form.network" class="rounded-lg border px-3 py-2">
            <option value="">Network…</option>
            <option v-for="n in networks.data.value ?? []" :key="n.slug" :value="n.slug">{{ n.name }}</option>
          </select>
          <select v-model="form.asset_id" class="rounded-lg border px-3 py-2">
            <option value="">Asset…</option>
            <option v-for="a in networkAssets" :key="a.id" :value="a.id">{{ a.symbol }}</option>
          </select>
        </div>
        <p v-if="formError" class="mt-2 text-sm text-red-600">{{ formError }}</p>
        <Button class="mt-3" :disabled="create.isPending.value" @click="create.mutate()">Request sweep</Button>
      </Card>

      <Card>
        <h2 class="font-medium">Sweep history</h2>
        <EmptyState
          v-if="(sweeps.data.value ?? []).length === 0"
          title="No sweeps yet"
          description="Sweeps requested via the API or this form will appear here with their resolved destination snapshot."
        />
        <table v-else class="mt-3 w-full text-sm">
          <thead>
            <tr class="text-left text-slate-500">
              <th class="py-1">Created</th><th>Asset</th><th>Amount</th>
              <th>Destination (snapshot)</th><th>Status</th><th>Approvals</th><th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="s in sweeps.data.value ?? []" :key="s.id" class="border-t">
              <td class="py-2">{{ new Date(s.created_at).toLocaleString() }}</td>
              <td>{{ s.asset }} · {{ s.network }}</td>
              <td class="font-mono">{{ s.amount ?? '—' }}</td>
              <td class="max-w-[200px] truncate font-mono">{{ s.destination_address ?? '—' }}</td>
              <td>
                <Badge :tone="tone(s.status)">{{ s.status }}</Badge>
                <span v-if="s.status_reason" class="block text-xs text-slate-500">{{ s.status_reason }}</span>
              </td>
              <td>{{ s.approvals_received }}/{{ s.approvals_required }}</td>
              <td class="space-x-2 whitespace-nowrap">
                <template v-if="s.status === 'awaiting_approval'">
                  <Button @click="decide.mutate({ id: s.id, decision: 'approve' })">Approve</Button>
                  <Button @click="decide.mutate({ id: s.id, decision: 'reject' })">Reject</Button>
                </template>
              </td>
            </tr>
          </tbody>
        </table>
      </Card>
    </template>
  </div>
</template>
