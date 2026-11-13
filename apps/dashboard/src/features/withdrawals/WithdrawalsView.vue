<script setup lang="ts">
import { computed, ref } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { api } from '@/api/client'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'
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

const requests = useQuery({
  queryKey: computed(() => ['withdrawals', projectId.value]),
  queryFn: () => api.listWithdrawals(projectId.value),
  enabled: computed(() => projectId.value !== ''),
})
const policy = useQuery({
  queryKey: computed(() => ['withdrawal-policy', projectId.value]),
  queryFn: () => api.getWithdrawalPolicy(projectId.value),
  enabled: computed(() => projectId.value !== ''),
})

// Create form
const form = ref({
  wallet_id: '', network: '', asset_id: '', destination_address: '', amount: '',
})
const formError = ref('')
const networkAssets = computed(() =>
  (assets.data.value ?? []).filter((a) => a.network === form.value.network),
)

const create = useMutation({
  mutationFn: () =>
    api.createWithdrawal(
      { ...form.value },
      `dash-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`,
    ),
  onSuccess: () => {
    formError.value = ''
    void client.invalidateQueries({ queryKey: ['withdrawals', projectId.value] })
  },
  onError: (e) => { formError.value = e instanceof Error ? e.message : 'Request failed' },
})

const decide = useMutation({
  mutationFn: (args: { id: string; decision: 'approve' | 'reject' }) =>
    args.decision === 'approve' ? api.approveWithdrawal(args.id) : api.rejectWithdrawal(args.id),
  onSuccess: () => void client.invalidateQueries({ queryKey: ['withdrawals', projectId.value] }),
})

// Policy editor (project default policy)
const policyForm = ref({
  approvals_required: '1', min_single_amount: '', max_single_amount: '', daily_limit: '',
  auto_approve_below: '0', service_fee_flat: '0',
})
const savedPolicy = computed(() => policy.data.value)
const savePolicy = useMutation({
  mutationFn: () =>
    api.updateWithdrawalPolicy(projectId.value, {
      approvals_required: Number(policyForm.value.approvals_required || 1),
      min_single_amount: policyForm.value.min_single_amount || null,
      max_single_amount: policyForm.value.max_single_amount || null,
      daily_limit: policyForm.value.daily_limit || null,
      auto_approve_below: policyForm.value.auto_approve_below || '0',
      service_fee_flat: policyForm.value.service_fee_flat || '0',
    }),
  onSuccess: () => void client.invalidateQueries({ queryKey: ['withdrawal-policy', projectId.value] }),
})

function statusTone(status: string): 'neutral' | 'success' | 'warning' | 'danger' {
  if (status === 'completed') return 'success'
  if (status === 'failed' || status === 'rejected') return 'danger'
  if (status === 'pending_policy') return 'warning'
  return 'neutral'
}
</script>

<template>
  <div class="space-y-6">
    <div>
      <h1 class="text-xl font-semibold">Withdrawals</h1>
      <p class="text-sm text-slate-500">
        Tenant-instructed payouts with business approval policy. Amounts are integer base units.
        Dispatch runs in the background once a request is approved.
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
        <h2 class="font-medium">New withdrawal request</h2>
        <div class="mt-3 grid gap-3 md:grid-cols-2">
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
          <Input id="wd-amount" v-model="form.amount" label="Amount (base units)" placeholder="e.g. 250000" />
          <Input id="wd-destination" v-model="form.destination_address" label="Destination address" placeholder="External address on the selected network" />
        </div>
        <p v-if="formError" class="mt-2 text-sm text-red-600">{{ formError }}</p>
        <Button class="mt-3" :disabled="create.isPending.value" @click="create.mutate()">Request withdrawal</Button>
      </Card>

      <Card>
        <h2 class="font-medium">Requests</h2>
        <EmptyState v-if="(requests.data.value ?? []).length === 0" title="No withdrawal requests" description="Requests created via the API or this form will appear here." />
        <table v-else class="mt-3 w-full text-sm">
          <thead>
            <tr class="text-left text-slate-500">
              <th class="py-1">Created</th><th>Asset</th><th>Amount</th><th>Destination</th>
              <th>Status</th><th>Approvals</th><th>Fee (actual)</th><th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in requests.data.value ?? []" :key="r.id" class="border-t">
              <td class="py-2">{{ new Date(r.created_at).toLocaleString() }}</td>
              <td>{{ r.asset }} · {{ r.network }}</td>
              <td class="font-mono">{{ r.amount }}</td>
              <td class="max-w-[180px] truncate font-mono">{{ r.destination_address }}</td>
              <td>
                <Badge :tone="statusTone(r.status)">{{ r.status }}</Badge>
                <span v-if="r.status_reason" class="block text-xs text-slate-500">{{ r.status_reason }}</span>
              </td>
              <td>{{ r.approvals_received }}/{{ r.approvals_required }}</td>
              <td class="font-mono">{{ r.actual_fee ?? '—' }} {{ r.fee_asset ?? '' }}</td>
              <td class="space-x-2 whitespace-nowrap">
                <template v-if="r.status === 'pending_policy'">
                  <Button @click="decide.mutate({ id: r.id, decision: 'approve' })">Approve</Button>
                  <Button @click="decide.mutate({ id: r.id, decision: 'reject' })">Reject</Button>
                </template>
              </td>
            </tr>
          </tbody>
        </table>
      </Card>

      <Card>
        <h2 class="font-medium">Withdrawal policy (project default)</h2>
        <p v-if="savedPolicy" class="mt-1 text-sm text-slate-500">
          Current: {{ savedPolicy.approvals_required }} approval(s),
          auto-approve ≤ {{ savedPolicy.auto_approve_below }},
          min single {{ savedPolicy.min_single_amount ?? '0' }},
          max single {{ savedPolicy.max_single_amount ?? '∞' }},
          daily {{ savedPolicy.daily_limit ?? '∞' }},
          service fee {{ savedPolicy.service_fee_flat }}
        </p>
        <div class="mt-3 grid gap-3 md:grid-cols-3">
          <Input id="pol-approvals" v-model="policyForm.approvals_required" label="Approvals required" type="number" />
          <Input id="pol-auto" v-model="policyForm.auto_approve_below" label="Auto-approve at or below" />
          <Input id="pol-fee" v-model="policyForm.service_fee_flat" label="Service fee (flat, base units)" />
          <Input id="pol-min-single" v-model="policyForm.min_single_amount" label="Min single (blank = none)" />
          <Input id="pol-single" v-model="policyForm.max_single_amount" label="Max single (blank = none)" />
          <Input id="pol-daily" v-model="policyForm.daily_limit" label="Daily limit (blank = none)" />
        </div>
        <Button class="mt-3" :disabled="savePolicy.isPending.value" @click="savePolicy.mutate()">Save policy</Button>
      </Card>
    </template>
  </div>
</template>
