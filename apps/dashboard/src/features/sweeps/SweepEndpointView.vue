<script setup lang="ts">
import { computed, ref } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { api } from '@/api/client'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'
import Card from '@/components/ui/Card.vue'
import Badge from '@/components/ui/Badge.vue'

const client = useQueryClient()
const projectId = ref('')
const endpointUrl = ref('')
const signingSecret = ref('')
const testNetwork = ref('')
const testResult = ref('')
const testError = ref('')

const projects = useQuery({ queryKey: ['projects'], queryFn: api.listProjects })
const networks = useQuery({ queryKey: ['networks'], queryFn: api.listNetworks })
const query = useQuery({
  queryKey: computed(() => ['sweep-endpoint', projectId.value]),
  queryFn: () => api.getSweepEndpoint(projectId.value),
  enabled: computed(() => projectId.value !== ''),
  retry: false,
})
const history = useQuery({
  queryKey: computed(() => ['sweep-endpoint-history', projectId.value]),
  queryFn: () => api.getSweepEndpointHistory(projectId.value),
  enabled: computed(() => projectId.value !== ''),
  retry: false,
})
const save = useMutation({
  mutationFn: () => api.putSweepEndpoint(projectId.value, endpointUrl.value.trim(), signingSecret.value),
  onSuccess: async () => {
    signingSecret.value = ''
    await client.invalidateQueries({ queryKey: ['sweep-endpoint', projectId.value] })
    await client.invalidateQueries({ queryKey: ['sweep-endpoint-history', projectId.value] })
  },
})
const remove = useMutation({
  mutationFn: () => api.deleteSweepEndpoint(projectId.value),
  onSuccess: async () => {
    await client.invalidateQueries({ queryKey: ['sweep-endpoint', projectId.value] })
    await client.invalidateQueries({ queryKey: ['sweep-endpoint-history', projectId.value] })
  },
})
const test = useMutation({
  mutationFn: () => api.testSweepEndpoint(projectId.value, testNetwork.value),
  onSuccess: (data) => { testResult.value = data.address; testError.value = '' },
  onError: (e) => { testResult.value = ''; testError.value = e instanceof Error ? e.message : 'Test failed' },
})
function submit(): void { if (endpointUrl.value.trim().startsWith('https://')) save.mutate() }
</script>
<template>
  <div class="space-y-6">
    <h1 class="text-2xl font-semibold">External Sweep Destination Endpoint</h1>
    <p class="text-ink-muted">
      Register one HTTPS endpoint per project. Before each sweep, Custodium calls it (with network / asset
      headers) and expects exactly one plain-text wallet address in the response. Destinations are never
      supplied in sweep requests or read from local files. Registration is validated with the same SSRF
      rules used at sweep time, and every change is recorded in the history below.
    </p>

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
      <Card title="Registered endpoint">
        <p v-if="query.isPending.value">Loading…</p>
        <template v-else-if="query.data.value?.endpoint_url">
          <p class="font-mono text-sm break-all">{{ query.data.value.endpoint_url }}</p>
          <p class="mt-1 text-sm text-ink-muted">
            Version {{ query.data.value.version }} ·
            <Badge :tone="query.data.value.enabled ? 'success' : 'danger'">
              {{ query.data.value.enabled ? 'enabled' : 'disabled' }}
            </Badge>
            · signing secret {{ query.data.value.has_signing_secret ? 'configured' : 'not set' }}
          </p>
        </template>
        <p v-else class="text-sm text-ink-muted">No endpoint registered for this project yet.</p>
        <form class="space-y-4 mt-4" @submit.prevent="submit">
          <Input id="sweep-endpoint-url" v-model="endpointUrl" label="Endpoint URL (HTTPS only)" type="url" required placeholder="https://exchange.example.com/api/hot-wallet" />
          <Input id="sweep-endpoint-secret" v-model="signingSecret" label="Signing secret (optional; stored encrypted, never shown)" type="password" autocomplete="off" placeholder="Leave blank to keep the current secret" />
          <div class="flex gap-2">
            <Button type="submit" :disabled="save.isPending.value">Save endpoint</Button>
            <Button type="button" variant="danger" @click="remove.mutate()">Disable</Button>
          </div>
          <p v-if="endpointUrl && !endpointUrl.startsWith('https://')" role="alert" class="text-sm text-danger">HTTPS is required.</p>
          <p v-if="save.isError.value" role="alert" class="text-sm text-danger">{{ (save.error.value as Error).message }}</p>
          <p v-if="save.isSuccess.value" role="status" class="text-sm text-success">Endpoint saved.</p>
        </form>
      </Card>

      <Card title="Test resolution">
        <p class="text-sm text-ink-muted">
          Performs one live resolution against the registered endpoint. A test never creates a sweep,
          and its result can never be reused as a sweep destination.
        </p>
        <div class="mt-3 flex items-end gap-3">
          <select v-model="testNetwork" class="rounded-lg border px-3 py-2">
            <option value="">Network…</option>
            <option v-for="n in networks.data.value ?? []" :key="n.slug" :value="n.slug">{{ n.name }}</option>
          </select>
          <Button :disabled="test.isPending.value || !testNetwork" @click="test.mutate()">Test</Button>
        </div>
        <p v-if="testResult" class="mt-2 font-mono text-sm">Resolved: {{ testResult }}</p>
        <p v-if="testError" role="alert" class="mt-2 text-sm text-danger">{{ testError }}</p>
      </Card>

      <Card title="Change history">
        <table class="w-full text-sm">
          <thead>
            <tr class="text-left text-slate-500"><th class="py-1">When</th><th>Action</th><th>New URL hash</th></tr>
          </thead>
          <tbody>
            <tr v-for="row in history.data.value ?? []" :key="row.created_at + row.action" class="border-t">
              <td class="py-2">{{ new Date(row.created_at).toLocaleString() }}</td>
              <td>{{ row.action }}</td>
              <td class="font-mono text-xs">{{ row.new_url_hash.slice(0, 16) }}…</td>
            </tr>
          </tbody>
        </table>
        <p v-if="(history.data.value ?? []).length === 0" class="text-sm text-ink-muted">No changes recorded.</p>
      </Card>
    </template>
  </div>
</template>
