<script setup lang="ts">
import { computed, ref } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { api } from '@/api/client'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import EmptyState from '@/components/ui/EmptyState.vue'

const client = useQueryClient()
const projectId = ref('')
const projects = useQuery({ queryKey: ['projects'], queryFn: api.listProjects })
const assets = useQuery({ queryKey: ['assets'], queryFn: api.listAssets })
const policies = useQuery({
  queryKey: computed(() => ['deposit-policies', projectId.value]),
  queryFn: () => api.listDepositPolicies(projectId.value),
  enabled: computed(() => projectId.value !== ''),
})

const drafts = ref<Record<string, string>>({})
const formError = ref('')
function currentMin(assetId: string): string {
  const row = (policies.data.value ?? []).find((p) => p.asset_id === assetId)
  return row ? row.min_amount : '0'
}
const save = useMutation({
  mutationFn: (assetId: string) =>
    api.putDepositPolicy({
      project_id: projectId.value,
      asset_id: assetId,
      min_amount: drafts.value[assetId] ?? currentMin(assetId),
    }),
  onSuccess: () => {
    formError.value = ''
    void client.invalidateQueries({ queryKey: ['deposit-policies', projectId.value] })
  },
  onError: (e) => { formError.value = e instanceof Error ? e.message : 'Request failed' },
})
</script>

<template>
  <div class="space-y-6">
    <div>
      <h1 class="text-2xl font-semibold">Deposit policies</h1>
      <p class="text-sm text-ink-muted">
        A minimum deposit per asset, in integer base units. Deposits below the minimum
        are held — never dropped — and accumulate per wallet until the total reaches the
        minimum, then credit together. There is deliberately no maximum: capping a
        deposit could strand funds on-chain. Zero means no minimum.
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

    <Card v-if="projectId" title="Minimum per asset">
      <p v-if="formError" role="alert" class="mb-2 text-sm text-danger">{{ formError }}</p>
      <EmptyState
        v-if="(assets.data.value ?? []).length === 0"
        title="No assets"
        description="The asset registry is empty."
      />
      <table v-else class="w-full text-left text-sm">
        <thead>
          <tr class="text-ink-muted">
            <th class="py-2 pr-4">Network</th>
            <th class="py-2 pr-4">Asset</th>
            <th class="py-2 pr-4">Minimum (base units)</th>
            <th class="py-2" />
          </tr>
        </thead>
        <tbody>
          <tr v-for="a in assets.data.value ?? []" :key="a.id" class="border-t border-line">
            <td class="py-2 pr-4">{{ a.network }}</td>
            <td class="py-2 pr-4">{{ a.symbol }}</td>
            <td class="py-2 pr-4">
              <input
                :value="drafts[a.id] ?? currentMin(a.id)"
                class="w-56 rounded-lg border border-line bg-white px-3 py-2"
                inputmode="numeric"
                @input="drafts[a.id] = ($event.target as HTMLInputElement).value"
              >
            </td>
            <td class="py-2 text-right">
              <Button variant="secondary" :disabled="save.isPending.value" @click="save.mutate(a.id)">Save</Button>
            </td>
          </tr>
        </tbody>
      </table>
    </Card>
  </div>
</template>
