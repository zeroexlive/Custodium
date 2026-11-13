<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { api } from '@/api/client'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import Badge from '@/components/ui/Badge.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import Input from '@/components/ui/Input.vue'

const client = useQueryClient()
const projectId = ref('')
const projects = useQuery({ queryKey: ['projects'], queryFn: api.listProjects })
const networks = useQuery({ queryKey: ['networks'], queryFn: api.listNetworks })
const assets = useQuery({ queryKey: ['assets'], queryFn: api.listAssets })
const wallets = useQuery({
  queryKey: computed(() => ['wallets', projectId.value]),
  queryFn: () => api.listWallets({ project_id: projectId.value }),
  enabled: computed(() => projectId.value !== ''),
})
const policy = useQuery({
  queryKey: computed(() => ['sweep-policy', projectId.value]),
  queryFn: () => api.getSweepPolicy(projectId.value),
  enabled: computed(() => projectId.value !== ''),
})
const destinations = useQuery({
  queryKey: computed(() => ['sweep-destinations', projectId.value]),
  queryFn: () => api.listStaticDestinations(projectId.value),
  enabled: computed(() => projectId.value !== ''),
})
const rules = useQuery({
  queryKey: computed(() => ['auto-sweep-rules', projectId.value]),
  queryFn: () => api.listAutoSweepRules(projectId.value),
  enabled: computed(() => projectId.value !== ''),
})

const policyForm = ref({
  destination_mode: 'resolver' as 'resolver' | 'static',
  min_sweep_threshold: '0', leave_behind: '0', enabled: true,
})
watch(policy.data, (data) => {
  if (data) {
    policyForm.value = {
      destination_mode: data.destination_mode,
      min_sweep_threshold: data.min_sweep_threshold,
      leave_behind: data.leave_behind,
      enabled: data.enabled,
    }
  }
})
const policyError = ref('')
const savePolicy = useMutation({
  mutationFn: () => api.putSweepPolicy({ project_id: projectId.value, ...policyForm.value }),
  onSuccess: () => {
    policyError.value = ''
    void client.invalidateQueries({ queryKey: ['sweep-policy', projectId.value] })
  },
  onError: (e) => { policyError.value = e instanceof Error ? e.message : 'Request failed' },
})

const destForm = ref({ network: 'ethereum', address: '', label: '' })
const destError = ref('')
const saveDestination = useMutation({
  mutationFn: () => api.putStaticDestination({ project_id: projectId.value, ...destForm.value }),
  onSuccess: () => {
    destForm.value = { network: destForm.value.network, address: '', label: '' }
    destError.value = ''
    void client.invalidateQueries({ queryKey: ['sweep-destinations', projectId.value] })
  },
  onError: (e) => { destError.value = e instanceof Error ? e.message : 'Request failed' },
})
const removeDestination = useMutation({
  mutationFn: (id: string) => api.deleteStaticDestination(id),
  onSuccess: () => void client.invalidateQueries({ queryKey: ['sweep-destinations', projectId.value] }),
})

const ruleForm = ref({ wallet_id: '', network: 'ethereum', asset_id: '', threshold_amount: '' })
const ruleError = ref('')
const createRule = useMutation({
  mutationFn: () => api.createAutoSweepRule({ ...ruleForm.value, enabled: true }),
  onSuccess: () => {
    ruleForm.value = { wallet_id: '', network: ruleForm.value.network, asset_id: '', threshold_amount: '' }
    ruleError.value = ''
    void client.invalidateQueries({ queryKey: ['auto-sweep-rules', projectId.value] })
  },
  onError: (e) => { ruleError.value = e instanceof Error ? e.message : 'Request failed' },
})
const removeRule = useMutation({
  mutationFn: (id: string) => api.deleteAutoSweepRule(id),
  onSuccess: () => void client.invalidateQueries({ queryKey: ['auto-sweep-rules', projectId.value] }),
})
const projectAssets = computed(() =>
  (assets.data.value ?? []).filter((a) => a.network === ruleForm.value.network),
)
function assetSymbol(assetId: string): string {
  return (assets.data.value ?? []).find((a) => a.id === assetId)?.symbol ?? assetId
}
</script>

<template>
  <div class="space-y-6">
    <div>
      <h1 class="text-2xl font-semibold">Sweep settings</h1>
      <p class="text-sm text-ink-muted">
        Where sweeps go and when they fire. Destinations are always registered
        configuration — a sweep request never carries one — and are snapshotted
        before approval in both modes.
      </p>
    </div>

    <Card>
      <label class="text-sm">
        <span class="mb-1 block text-ink-muted">Project</span>
        <select v-model="projectId" class="rounded-lg border border-line bg-white px-3 py-2">
          <option value="">Select a project</option>
          <option v-for="p in projects.data.value ?? []" :key="p.id" :value="p.id">{{ p.name }}</option>
        </select>
      </label>
    </Card>

    <template v-if="projectId">
      <Card title="Sweep policy">
        <form class="flex flex-wrap items-end gap-3" @submit.prevent="savePolicy.mutate()">
          <label class="text-sm">
            <span class="mb-1 block text-ink-muted">Destination mode</span>
            <select v-model="policyForm.destination_mode" class="rounded-lg border border-line bg-white px-3 py-2">
              <option value="resolver">Resolver endpoint (recommended)</option>
              <option value="static">Static hot-wallet addresses</option>
            </select>
          </label>
          <Input id="sp-threshold" v-model="policyForm.min_sweep_threshold" label="Min sweep threshold (base units)" />
          <Input id="sp-leave" v-model="policyForm.leave_behind" label="Leave behind (base units)" />
          <label class="flex items-center gap-2 text-sm">
            <input v-model="policyForm.enabled" type="checkbox"> Enabled
          </label>
          <Button type="submit" :disabled="savePolicy.isPending.value">Save policy</Button>
        </form>
        <p v-if="policyError" role="alert" class="mt-2 text-sm text-danger">{{ policyError }}</p>
        <p class="mt-2 text-sm text-ink-muted">
          Resolver mode fetches the destination from the project's registered endpoint at
          sweep time. Static mode uses the registered hot-wallet address for the sweep's
          network. There is no fallback between modes — a missing destination fails the sweep closed.
        </p>
      </Card>

      <Card title="Static hot-wallet destinations">
        <form class="flex flex-wrap items-end gap-3" @submit.prevent="saveDestination.mutate()">
          <label class="text-sm">
            <span class="mb-1 block text-ink-muted">Network</span>
            <select v-model="destForm.network" class="rounded-lg border border-line bg-white px-3 py-2">
              <option v-for="n in networks.data.value ?? []" :key="n.slug" :value="n.slug">{{ n.slug }}</option>
            </select>
          </label>
          <Input id="sd-address" v-model="destForm.address" label="Hot-wallet address" required class="min-w-80" />
          <Input id="sd-label" v-model="destForm.label" label="Label (optional)" />
          <Button type="submit" :disabled="saveDestination.isPending.value">Save destination</Button>
        </form>
        <p v-if="destError" role="alert" class="mt-2 text-sm text-danger">{{ destError }}</p>
        <EmptyState
          v-if="(destinations.data.value ?? []).length === 0"
          title="No static destinations"
          description="Register one hot-wallet address per network to use static mode."
        />
        <table v-else class="mt-3 w-full text-left text-sm">
          <thead>
            <tr class="text-ink-muted">
              <th class="py-2 pr-4">Network</th>
              <th class="py-2 pr-4">Address</th>
              <th class="py-2 pr-4">Label</th>
              <th class="py-2" />
            </tr>
          </thead>
          <tbody>
            <tr v-for="d in destinations.data.value ?? []" :key="d.id" class="border-t border-line">
              <td class="py-2 pr-4">{{ d.network }}</td>
              <td class="py-2 pr-4 font-mono break-all">{{ d.address }}</td>
              <td class="py-2 pr-4">{{ d.label }}</td>
              <td class="py-2 text-right">
                <Button variant="secondary" :disabled="removeDestination.isPending.value" @click="removeDestination.mutate(d.id)">Remove</Button>
              </td>
            </tr>
          </tbody>
        </table>
      </Card>

      <Card title="Auto-sweep rules">
        <p class="mb-3 text-sm text-ink-muted">
          When a wallet's available balance for an asset reaches the threshold, a sweep is
          created automatically (at most one open auto-sweep per rule). It still resolves,
          snapshots, and waits for approvals like any other sweep.
        </p>
        <form class="flex flex-wrap items-end gap-3" @submit.prevent="createRule.mutate()">
          <label class="text-sm">
            <span class="mb-1 block text-ink-muted">Wallet</span>
            <select v-model="ruleForm.wallet_id" required class="rounded-lg border border-line bg-white px-3 py-2">
              <option value="">Select a wallet</option>
              <option v-for="w in wallets.data.value ?? []" :key="w.id" :value="w.id">{{ w.label }} ({{ w.external_customer_id }})</option>
            </select>
          </label>
          <label class="text-sm">
            <span class="mb-1 block text-ink-muted">Network</span>
            <select v-model="ruleForm.network" class="rounded-lg border border-line bg-white px-3 py-2">
              <option v-for="n in networks.data.value ?? []" :key="n.slug" :value="n.slug">{{ n.slug }}</option>
            </select>
          </label>
          <label class="text-sm">
            <span class="mb-1 block text-ink-muted">Asset</span>
            <select v-model="ruleForm.asset_id" required class="rounded-lg border border-line bg-white px-3 py-2">
              <option value="">Select an asset</option>
              <option v-for="a in projectAssets" :key="a.id" :value="a.id">{{ a.symbol }}</option>
            </select>
          </label>
          <Input id="asr-threshold" v-model="ruleForm.threshold_amount" label="Threshold (base units)" required />
          <Button type="submit" :disabled="createRule.isPending.value">Add rule</Button>
        </form>
        <p v-if="ruleError" role="alert" class="mt-2 text-sm text-danger">{{ ruleError }}</p>
        <EmptyState
          v-if="(rules.data.value ?? []).length === 0"
          title="No auto-sweep rules"
          description="Add a rule to sweep automatically when a balance threshold is reached."
        />
        <table v-else class="mt-3 w-full text-left text-sm">
          <thead>
            <tr class="text-ink-muted">
              <th class="py-2 pr-4">Network</th>
              <th class="py-2 pr-4">Asset</th>
              <th class="py-2 pr-4">Threshold</th>
              <th class="py-2 pr-4">Triggered</th>
              <th class="py-2 pr-4">Status</th>
              <th class="py-2" />
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in rules.data.value ?? []" :key="r.id" class="border-t border-line">
              <td class="py-2 pr-4">{{ r.network }}</td>
              <td class="py-2 pr-4">{{ assetSymbol(r.asset_id) }}</td>
              <td class="py-2 pr-4">{{ r.threshold_amount }}</td>
              <td class="py-2 pr-4">{{ r.trigger_count }}×</td>
              <td class="py-2 pr-4">
                <Badge :tone="r.enabled ? 'success' : 'neutral'">{{ r.enabled ? 'Enabled' : 'Disabled' }}</Badge>
              </td>
              <td class="py-2 text-right">
                <Button variant="secondary" :disabled="removeRule.isPending.value" @click="removeRule.mutate(r.id)">Remove</Button>
              </td>
            </tr>
          </tbody>
        </table>
      </Card>
    </template>
  </div>
</template>
