<script setup lang="ts">
import { ref, onUnmounted } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { api } from '@/api/client'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'
import Card from '@/components/ui/Card.vue'
import Badge from '@/components/ui/Badge.vue'
import EmptyState from '@/components/ui/EmptyState.vue'

const name = ref(''); const projectId = ref(''); const scopes = ref('wallets:read')
const ipAllowlist = ref(''); const expiresAt = ref('')
/**
 * The newly-created secret lives ONLY in this local ref.
 * It is never written to Pinia, storage, or the query cache,
 * and is cleared when dismissed or when this view unmounts.
 */
const oneTimeSecret = ref<string | null>(null)
const copied = ref(false)
const client = useQueryClient()
const projects = useQuery({ queryKey: ['projects'], queryFn: api.listProjects })
const query = useQuery({ queryKey: ['api-keys'], queryFn: api.listApiKeys })
const create = useMutation({
  mutationFn: () => api.createApiKey({
    project_id: projectId.value, name: name.value,
    scopes: scopes.value.split(',').map((s) => s.trim()).filter(Boolean),
    ip_allowlist: ipAllowlist.value.split('\n').map((s) => s.trim()).filter(Boolean),
    expires_at: expiresAt.value ? new Date(expiresAt.value).toISOString() : null,
  }),
  onSuccess: async (created) => { oneTimeSecret.value = created.secret; name.value = ''; await client.invalidateQueries({ queryKey: ['api-keys'] }) },
})
const revoke = useMutation({
  mutationFn: (id: string) => api.revokeApiKey(id),
  onSuccess: async () => { await client.invalidateQueries({ queryKey: ['api-keys'] }) },
})
async function copySecret(): Promise<void> {
  if (!oneTimeSecret.value) return
  await navigator.clipboard.writeText(oneTimeSecret.value); copied.value = true
}
function dismissSecret(): void { oneTimeSecret.value = null; copied.value = false }
onUnmounted(dismissSecret)
function submit(): void { if (name.value.trim() && projectId.value) create.mutate() }
</script>
<template>
  <div class="space-y-6">
    <h1 class="text-2xl font-semibold">API Keys</h1>
    <div v-if="oneTimeSecret" role="alert" class="border border-warning rounded-card p-4 bg-amber-50 text-amber-900">
      <p class="font-semibold">Save this secret now — it will not be shown again.</p>
      <code class="block font-mono text-sm break-all my-2">{{ oneTimeSecret }}</code>
      <div class="flex gap-2">
        <Button type="button" @click="copySecret">{{ copied ? 'Copied' : 'Copy secret' }}</Button>
        <Button type="button" variant="secondary" @click="dismissSecret">I have saved it — dismiss</Button>
      </div>
    </div>
    <Card title="Create API key">
      <form class="space-y-4" @submit.prevent="submit">
        <div class="space-y-1">
          <label for="key-project" class="block text-sm font-medium">Project</label>
          <select id="key-project" v-model="projectId" required class="w-full rounded border border-gray-300 dark:border-gray-600 bg-surface px-3 py-2 text-sm">
            <option value="" disabled>Select a project</option>
            <option v-for="p in projects.data.value ?? []" :key="p.id" :value="p.id">{{ p.name }} ({{ p.environment }})</option>
          </select>
        </div>
        <Input id="key-name" v-model="name" label="Key name" required />
        <Input id="key-scopes" v-model="scopes" label="Scopes (comma-separated)" required />
        <div class="space-y-1">
          <label for="key-ip-allowlist" class="block text-sm font-medium">IP allowlist (optional, one per line)</label>
          <textarea id="key-ip-allowlist" v-model="ipAllowlist" rows="2" class="w-full rounded border border-gray-300 dark:border-gray-600 bg-surface px-3 py-2 text-sm" placeholder="203.0.113.10"></textarea>
          <p class="text-xs text-ink-muted">When set, only these source IPs can use the key. Empty means any IP.</p>
        </div>
        <div class="space-y-1">
          <label for="key-expires" class="block text-sm font-medium">Expires at (optional)</label>
          <input id="key-expires" v-model="expiresAt" type="datetime-local" class="w-full rounded border border-gray-300 dark:border-gray-600 bg-surface px-3 py-2 text-sm">
        </div>
        <Button type="submit" :disabled="create.isPending.value">Create key</Button>
        <p v-if="create.isError.value" role="alert" class="text-sm text-danger">{{ (create.error.value as Error).message }}</p>
      </form>
    </Card>
    <Card title="Your API keys">
      <p v-if="query.isPending.value">Loading…</p>
      <p v-else-if="query.isError.value" role="alert" class="text-danger">Could not load API keys.</p>
      <EmptyState v-else-if="!query.data.value?.length" title="No API keys yet" description="Create a key above. Secrets are shown only once at creation." />
      <ul v-else class="divide-y">
        <li v-for="k in query.data.value" :key="k.id" class="py-2 flex justify-between items-center gap-2">
          <span>
            <span class="font-medium">{{ k.name }}</span> <code class="font-mono text-xs">{{ k.key_id }}</code>
            <span class="block text-xs text-ink-muted">
              <template v-if="k.ip_allowlist?.length">IPs: {{ k.ip_allowlist.join(', ') }} · </template>
              <template v-if="k.expires_at">Expires {{ k.expires_at }}</template>
            </span>
          </span>
          <span class="flex items-center gap-2"><Badge :tone="k.status === 'active' ? 'success' : 'danger'">{{ k.status }}</Badge>
          <Button v-if="k.status === 'active'" type="button" variant="danger" @click="revoke.mutate(k.id)">Revoke</Button></span>
        </li>
      </ul>
    </Card>
  </div>
</template>
