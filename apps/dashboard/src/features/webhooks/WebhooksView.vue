<script setup lang="ts">
import { computed, ref } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { api } from '@/api/client'
import { WEBHOOK_EVENT_TYPES } from '@/api/types'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'
import Card from '@/components/ui/Card.vue'
import Badge from '@/components/ui/Badge.vue'
import EmptyState from '@/components/ui/EmptyState.vue'

const client = useQueryClient()
const projectId = ref('')
const projects = useQuery({ queryKey: ['projects'], queryFn: api.listProjects })
const endpoints = useQuery({
  queryKey: computed(() => ['webhook-endpoints', projectId.value]),
  queryFn: () => api.listWebhookEndpoints(projectId.value),
  enabled: computed(() => projectId.value !== ''),
})
const deliveries = useQuery({
  queryKey: computed(() => ['webhook-deliveries', projectId.value]),
  queryFn: () => api.listWebhookDeliveries(projectId.value),
  enabled: computed(() => projectId.value !== ''),
})

const url = ref('')
const selectedEvents = ref<string[]>(['deposit.credited', 'withdrawal.completed', 'withdrawal.failed'])
const newSecret = ref('')
const formError = ref('')
const create = useMutation({
  mutationFn: () => api.createWebhookEndpoint(projectId.value, url.value.trim(), selectedEvents.value),
  onSuccess: (data) => {
    newSecret.value = data.signing_secret
    formError.value = ''
    void client.invalidateQueries({ queryKey: ['webhook-endpoints', projectId.value] })
  },
  onError: (e) => { formError.value = e instanceof Error ? e.message : 'Request failed' },
})
const rotate = useMutation({
  mutationFn: (id: string) => api.rotateWebhookSecret(id),
  onSuccess: (data) => { newSecret.value = data.signing_secret },
  onError: (e) => { formError.value = e instanceof Error ? e.message : 'Rotation failed' },
})
const disable = useMutation({
  mutationFn: (id: string) => api.disableWebhookEndpoint(id),
  onSuccess: () => void client.invalidateQueries({ queryKey: ['webhook-endpoints', projectId.value] }),
})
const replay = useMutation({
  mutationFn: (id: string) => api.replayWebhookDelivery(id),
  onSuccess: () => void client.invalidateQueries({ queryKey: ['webhook-deliveries', projectId.value] }),
})

function toggleEvent(event: string): void {
  selectedEvents.value = selectedEvents.value.includes(event)
    ? selectedEvents.value.filter((e) => e !== event)
    : [...selectedEvents.value, event]
}
function tone(status: string): 'neutral' | 'success' | 'warning' | 'danger' {
  if (status === 'delivered') return 'success'
  if (status === 'dead') return 'danger'
  return 'warning'
}
</script>

<template>
  <div class="space-y-6">
    <div>
      <h1 class="text-2xl font-semibold">Webhooks</h1>
      <p class="text-sm text-ink-muted">
        Signed event delivery to your HTTPS endpoints. Verify the
        <code class="font-mono">WaaS-Signature</code> header (HMAC-SHA256 over
        <code class="font-mono">timestamp + "." + body</code>) and deduplicate on the event id —
        delivery is at-least-once with a bounded retry ladder.
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
        <h2 class="font-medium">Add endpoint</h2>
        <div class="mt-3 space-y-3">
          <Input id="wh-url" v-model="url" label="Endpoint URL (HTTPS)" placeholder="https://tenant.example/hooks" />
          <div class="flex flex-wrap gap-2">
            <button
              v-for="event in WEBHOOK_EVENT_TYPES" :key="event" type="button"
              class="rounded-full border px-3 py-1 text-sm"
              :class="selectedEvents.includes(event) ? 'bg-slate-900 text-white' : ''"
              @click="toggleEvent(event)"
            >{{ event }}</button>
          </div>
          <p v-if="formError" class="text-sm text-red-600">{{ formError }}</p>
          <div v-if="newSecret" class="rounded-lg bg-amber-50 p-3 text-sm">
            <p class="font-medium">Signing secret — shown once, store it now:</p>
            <p class="mt-1 break-all font-mono">{{ newSecret }}</p>
          </div>
          <Button :disabled="create.isPending.value" @click="create.mutate()">Create endpoint</Button>
        </div>
      </Card>

      <Card>
        <h2 class="font-medium">Endpoints</h2>
        <EmptyState
          v-if="(endpoints.data.value ?? []).length === 0"
          title="No endpoints"
          description="Events are only delivered to endpoints registered here."
        />
        <table v-else class="mt-3 w-full text-sm">
          <thead><tr class="text-left text-slate-500"><th class="py-1">URL</th><th>Events</th><th>Status</th><th></th></tr></thead>
          <tbody>
            <tr v-for="e in endpoints.data.value ?? []" :key="e.id" class="border-t">
              <td class="max-w-[260px] truncate py-2 font-mono">{{ e.url }}</td>
              <td>{{ e.events.join(', ') }}</td>
              <td><Badge :tone="e.enabled ? 'success' : 'neutral'">{{ e.enabled ? 'enabled' : 'disabled' }}</Badge></td>
              <td class="whitespace-nowrap">
                <Button v-if="e.enabled" variant="secondary" :disabled="rotate.isPending.value" @click="rotate.mutate(e.id)">Rotate secret</Button>
                <Button v-if="e.enabled" @click="disable.mutate(e.id)">Disable</Button>
              </td>
            </tr>
          </tbody>
        </table>
      </Card>

      <Card>
        <h2 class="font-medium">Deliveries</h2>
        <EmptyState
          v-if="(deliveries.data.value ?? []).length === 0"
          title="No deliveries yet"
          description="Deliveries appear when subscribed events occur."
        />
        <table v-else class="mt-3 w-full text-sm">
          <thead>
            <tr class="text-left text-slate-500">
              <th class="py-1">Event</th><th>Endpoint</th><th>Status</th><th>Attempts</th><th>Last result</th><th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="d in deliveries.data.value ?? []" :key="d.id" class="border-t">
              <td class="py-2">{{ d.event_type }}</td>
              <td class="max-w-[200px] truncate font-mono">{{ d.endpoint_url }}</td>
              <td><Badge :tone="tone(d.status)">{{ d.status }}</Badge></td>
              <td>{{ d.attempts }}</td>
              <td>{{ d.last_status_code ?? d.last_error ?? '—' }}</td>
              <td><Button v-if="d.status !== 'pending'" @click="replay.mutate(d.id)">Replay</Button></td>
            </tr>
          </tbody>
        </table>
      </Card>
    </template>
  </div>
</template>
