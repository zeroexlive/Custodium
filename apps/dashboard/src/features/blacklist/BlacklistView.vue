<script setup lang="ts">
import { computed, ref } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { api } from '@/api/client'
import type { BlacklistEntry, BlacklistScope } from '@/api/types'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'
import Card from '@/components/ui/Card.vue'
import Badge from '@/components/ui/Badge.vue'
import EmptyState from '@/components/ui/EmptyState.vue'

const client = useQueryClient()
const orgId = ref('')

const orgs = useQuery({ queryKey: ['organizations'], queryFn: api.listOrganizations })
const projects = useQuery({ queryKey: ['projects'], queryFn: api.listProjects })
const networks = useQuery({ queryKey: ['networks'], queryFn: api.listNetworks })
const orgProjects = computed(() => (projects.data.value ?? []).filter((p) => p.organization_id === orgId.value))

const entries = useQuery({
  queryKey: computed(() => ['blacklist-entries', orgId.value]),
  queryFn: () => api.listBlacklistEntries(orgId.value),
  enabled: computed(() => orgId.value !== ''),
})

// Add-entry form
const scope = ref<BlacklistScope>('tenant')
const entryProjectId = ref('')
const entryNetwork = ref('')
const entryAddress = ref('')
const entryReason = ref('')
const entryExpires = ref('')

const create = useMutation({
  mutationFn: () => api.createBlacklistEntry({
    scope: scope.value,
    ...(scope.value === 'tenant'
      ? { organization_id: orgId.value, ...(entryProjectId.value ? { project_id: entryProjectId.value } : {}) }
      : {}),
    network: entryNetwork.value,
    address: entryAddress.value.trim(),
    reason: entryReason.value.trim(),
    // datetime-local has no timezone; convert to an ISO-8601 instant.
    ...(entryExpires.value ? { expires_at: new Date(entryExpires.value).toISOString() } : {}),
  }),
  onSuccess: async () => {
    entryAddress.value = ''; entryReason.value = ''; entryExpires.value = ''; entryProjectId.value = ''
    await client.invalidateQueries({ queryKey: ['blacklist-entries'] })
  },
})

const disable = useMutation({
  mutationFn: (id: string) => api.disableBlacklistEntry(id),
  onSuccess: async () => { await client.invalidateQueries({ queryKey: ['blacklist-entries'] }) },
})

function submitCreate(): void {
  if (!entryNetwork.value || !entryAddress.value.trim() || !entryReason.value.trim()) return
  if (scope.value === 'tenant' && !orgId.value) return
  create.mutate()
}
function disableEntry(entry: BlacklistEntry): void {
  if (!window.confirm(`Disable the blacklist entry for ${entry.address} on ${entry.network}? It will stop matching checks.`)) return
  disable.mutate(entry.id)
}

// Address check tool
const checkAddress = ref('')
const checkNetwork = ref('')
const check = useMutation({
  mutationFn: () => api.checkBlacklist({
    address: checkAddress.value.trim(),
    network: checkNetwork.value,
    ...(orgId.value ? { organization_id: orgId.value } : {}),
  }),
})
function submitCheck(): void { if (checkAddress.value.trim() && checkNetwork.value) check.mutate() }
</script>
<template>
  <div class="space-y-6">
    <h1 class="text-2xl font-semibold">Manual Address Blacklist</h1>
    <p class="text-sm text-ink-muted max-w-3xl">
      A manually curated list, maintained by people — entries are added and disabled by hand and are checked
      during withdrawal validation. This is a manual list only: Custodium does not integrate AML/KYT,
      sanctions-screening or risk-scoring services, and this list is not an AML system.
    </p>

    <Card title="Organization">
      <p v-if="orgs.isPending.value">Loading…</p>
      <p v-else-if="orgs.isError.value" role="alert" class="text-danger">Could not load organizations.</p>
      <EmptyState v-else-if="!(orgs.data.value ?? []).length" title="No organizations yet"
        description="Create an organization first — blacklist entries are viewed per organization." />
      <div v-else class="space-y-1">
        <label for="blacklist-org" class="block text-sm font-medium">Organization</label>
        <select id="blacklist-org" v-model="orgId" class="w-full rounded border border-gray-300 dark:border-gray-600 bg-surface px-3 py-2 text-sm">
          <option value="" disabled>Select an organization</option>
          <option v-for="org in orgs.data.value ?? []" :key="org.id" :value="org.id">{{ org.name }}</option>
        </select>
        <p class="text-xs text-ink-muted">The list shows this organization's tenant entries plus platform-wide entries set by Custodium operators.</p>
      </div>
    </Card>

    <Card title="Add entry">
      <form class="space-y-4" @submit.prevent="submitCreate">
        <div class="grid gap-4 md:grid-cols-2">
          <div class="space-y-1">
            <label for="entry-scope" class="block text-sm font-medium">Scope</label>
            <select id="entry-scope" v-model="scope" class="w-full rounded border border-gray-300 dark:border-gray-600 bg-surface px-3 py-2 text-sm">
              <option value="tenant">Tenant (this organization)</option>
              <option value="platform">Platform (all tenants)</option>
            </select>
          </div>
          <div v-if="scope === 'tenant'" class="space-y-1">
            <label for="entry-project" class="block text-sm font-medium">Project (optional)</label>
            <select id="entry-project" v-model="entryProjectId" :disabled="!orgId" class="w-full rounded border border-gray-300 dark:border-gray-600 bg-surface px-3 py-2 text-sm disabled:opacity-50">
              <option value="">All projects in the organization</option>
              <option v-for="p in orgProjects" :key="p.id" :value="p.id">{{ p.name }} ({{ p.environment }})</option>
            </select>
          </div>
          <div class="space-y-1">
            <label for="entry-network" class="block text-sm font-medium">Network</label>
            <select id="entry-network" v-model="entryNetwork" required class="w-full rounded border border-gray-300 dark:border-gray-600 bg-surface px-3 py-2 text-sm">
              <option value="" disabled>Select a network</option>
              <option v-for="n in networks.data.value ?? []" :key="n.id" :value="n.slug">{{ n.name }}{{ n.is_testnet ? ' (testnet)' : '' }}</option>
            </select>
          </div>
          <Input id="entry-expires" v-model="entryExpires" label="Expires at (optional)" type="datetime-local" />
        </div>
        <Input id="entry-address" v-model="entryAddress" label="Address" required placeholder="Chain address exactly as it appears on-chain" />
        <Input id="entry-reason" v-model="entryReason" label="Reason" required placeholder="Why is this address being listed? (required, kept with the entry)" />
        <Button type="submit" :disabled="create.isPending.value || (scope === 'tenant' && !orgId)">Add entry</Button>
        <p v-if="create.isError.value" role="alert" class="text-sm text-danger">{{ (create.error.value as Error).message }}</p>
        <p class="text-xs text-ink-muted">
          Tenant entries require an owner or administrator role in the selected organization.
          Platform entries can only be created by Custodium platform operators (staff accounts).
        </p>
      </form>
    </Card>

    <Card v-if="orgId" title="Entries">
      <p v-if="disable.isError.value" role="alert" class="text-sm text-danger mb-3">{{ (disable.error.value as Error).message }}</p>
      <p v-if="entries.isPending.value">Loading…</p>
      <p v-else-if="entries.isError.value" role="alert" class="text-danger">Could not load blacklist entries.</p>
      <EmptyState v-else-if="!(entries.data.value ?? []).length" title="No entries"
        description="No platform or tenant blacklist entries are visible for this organization." />
      <div v-else class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead><tr class="text-left border-b">
            <th scope="col" class="py-2 pr-3">Scope</th><th scope="col" class="py-2 pr-3">Network</th>
            <th scope="col" class="py-2 pr-3">Address</th><th scope="col" class="py-2 pr-3">Reason</th>
            <th scope="col" class="py-2 pr-3">Status</th><th scope="col" class="py-2 pr-3">Expires</th>
            <th scope="col" class="py-2 pr-3">Created</th><th scope="col" class="py-2">Actions</th>
          </tr></thead>
          <tbody>
            <tr v-for="e in entries.data.value" :key="e.id" class="border-b align-top">
              <td class="py-2 pr-3">
                <Badge :tone="e.scope === 'platform' ? 'warning' : 'neutral'">{{ e.scope === 'platform' ? 'Platform' : 'Tenant' }}</Badge>
                <span v-if="e.scope === 'platform'" class="block text-xs text-ink-muted mt-1">Set by Custodium operators</span>
                <span v-else-if="e.project_id" class="block text-xs text-ink-muted mt-1">Project-scoped</span>
              </td>
              <td class="py-2 pr-3">{{ e.network }}</td>
              <td class="py-2 pr-3 font-mono text-xs break-all">{{ e.address }}
                <span v-if="e.normalized_address !== e.address" class="block text-ink-muted">normalized: {{ e.normalized_address }}</span>
              </td>
              <td class="py-2 pr-3">{{ e.reason }}</td>
              <td class="py-2 pr-3">
                <Badge v-if="!e.active" tone="neutral">Disabled</Badge>
                <Badge v-else-if="e.effective" tone="danger">In effect</Badge>
                <Badge v-else tone="warning">Expired</Badge>
              </td>
              <td class="py-2 pr-3 font-mono text-xs">{{ e.expires_at ?? '—' }}</td>
              <td class="py-2 pr-3 font-mono text-xs">{{ e.created_at ?? '—' }}</td>
              <td class="py-2">
                <Button v-if="e.active" type="button" variant="danger" :disabled="disable.isPending.value"
                  @click="disableEntry(e)">Disable</Button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </Card>

    <Card title="Check an address">
      <form class="space-y-4" @submit.prevent="submitCheck">
        <div class="grid gap-4 md:grid-cols-2">
          <Input id="check-address" v-model="checkAddress" label="Address" required />
          <div class="space-y-1">
            <label for="check-network" class="block text-sm font-medium">Network</label>
            <select id="check-network" v-model="checkNetwork" required class="w-full rounded border border-gray-300 dark:border-gray-600 bg-surface px-3 py-2 text-sm">
              <option value="" disabled>Select a network</option>
              <option v-for="n in networks.data.value ?? []" :key="n.id" :value="n.slug">{{ n.name }}{{ n.is_testnet ? ' (testnet)' : '' }}</option>
            </select>
          </div>
        </div>
        <Button type="submit" :disabled="check.isPending.value">Check address</Button>
        <p v-if="check.isError.value" role="alert" class="text-sm text-danger">{{ (check.error.value as Error).message }}</p>
        <div v-if="check.data.value" role="status" class="flex flex-wrap items-center gap-2">
          <Badge :tone="check.data.value.blacklisted ? 'danger' : 'success'">
            {{ check.data.value.blacklisted ? 'Blacklisted' : 'Not listed' }}
          </Badge>
          <span class="text-sm text-ink-muted">
            on {{ check.data.value.network }}<span v-if="check.data.value.matched_scopes.length">
              — matched scope(s): {{ check.data.value.matched_scopes.join(', ') }}</span>
          </span>
        </div>
        <p class="text-xs text-ink-muted">
          Checks the manual list only (platform entries plus, when an organization is selected, that
          organization's tenant entries). A “not listed” result says nothing beyond this list.
        </p>
      </form>
    </Card>
  </div>
</template>
