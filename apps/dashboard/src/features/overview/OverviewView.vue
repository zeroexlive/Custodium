<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useQuery } from '@tanstack/vue-query'
import { api } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import Card from '@/components/ui/Card.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import Icon from '@/components/ui/Icon.vue'
import BarChart from '@/components/charts/BarChart.vue'
import DonutChart from '@/components/charts/DonutChart.vue'
import HBars from '@/components/charts/HBars.vue'
import { bucketByDay, proportionNumber } from '@/components/charts/chartMath'

const auth = useAuthStore()
const orgs = useQuery({ queryKey: ['organizations'], queryFn: api.listOrganizations, retry: false })
const projects = useQuery({ queryKey: ['projects'], queryFn: api.listProjects, retry: false })
const keys = useQuery({ queryKey: ['api-keys'], queryFn: () => api.listApiKeys(), retry: false })
const audit = useQuery({ queryKey: ['audit-logs'], queryFn: api.listAuditLogs, retry: false })

const projectId = ref('')
watch(projects.data, (list) => {
  const first = list?.[0]
  if (!projectId.value && first) projectId.value = first.id
})
const selectedProject = computed(() => (projects.data.value ?? []).find((p) => p.id === projectId.value))

const wallets = useQuery({
  queryKey: computed(() => ['wallets', projectId.value]),
  queryFn: () => api.listWallets({ project_id: projectId.value }),
  enabled: computed(() => projectId.value !== ''), retry: false,
})
const balances = useQuery({
  queryKey: computed(() => ['project-balances', projectId.value]),
  queryFn: () => api.getProjectBalances(projectId.value),
  enabled: computed(() => projectId.value !== ''), retry: false,
})
const withdrawals = useQuery({
  queryKey: computed(() => ['withdrawals', projectId.value]),
  queryFn: () => api.listWithdrawals(projectId.value),
  enabled: computed(() => projectId.value !== ''), retry: false,
})
const sweeps = useQuery({
  queryKey: computed(() => ['sweeps', projectId.value]),
  queryFn: () => api.listSweeps(projectId.value),
  enabled: computed(() => projectId.value !== ''), retry: false,
})
const firstOrg = computed(() => (orgs.data.value ?? [])[0])
const usage = useQuery({
  queryKey: computed(() => ['usage', firstOrg.value?.id ?? '']),
  queryFn: () => api.getUsage(firstOrg.value!.id),
  enabled: computed(() => firstOrg.value !== undefined), retry: false,
})

const balanceRows = computed(() =>
  [...(balances.data.value?.items ?? [])]
    .sort((a, b) => proportionNumber(b.available) - proportionNumber(a.available))
    .slice(0, 8)
    .map((item) => ({
      label: `${item.symbol} · ${item.network}`,
      value: proportionNumber(item.available),
      display: `${item.available} ${item.symbol}`,
    })),
)
const hasBalances = computed(() => balanceRows.value.some((r) => r.value > 0))

const STATUS_COLORS: Record<string, string> = {
  completed: '#059669', failed: '#dc2626', rejected: '#d97706',
  pending_policy: '#2563eb', approved: '#0891b2', signing: '#7c3aed',
  broadcast: '#7c3aed', confirming: '#d97706',
}
const PALETTE = ['#2563eb', '#7c3aed', '#059669', '#d97706', '#0891b2', '#dc2626', '#64748b']
const withdrawalDonut = computed(() => {
  const counts = new Map<string, number>()
  for (const w of withdrawals.data.value ?? []) {
    const status = w.status.toLowerCase().replace(/_/g, ' ')
    counts.set(status, (counts.get(status) ?? 0) + 1)
  }
  return [...counts.entries()].map(([label, value], i) => ({
    label, value, color: STATUS_COLORS[label.replace(/ /g, '_')] ?? PALETTE[i % PALETTE.length] ?? '#64748b',
  }))
})

const pendingApprovals = computed(() => {
  const wd = (withdrawals.data.value ?? []).filter((w) => w.status.toLowerCase() === 'pending_policy').length
  const sw = (sweeps.data.value ?? []).filter((s) => s.status.toLowerCase() === 'awaiting_approval').length
  return wd + sw
})

const activity = computed(() =>
  bucketByDay((audit.data.value ?? []).map((e) => e.created_at), 14)
    .map((b) => ({ label: b.label, value: b.count })),
)
const recentEvents = computed(() => (audit.data.value ?? []).slice(0, 6))

const usageBars = computed(() => {
  const u = usage.data.value
  if (!u) return []
  const rows = [
    { label: 'Wallets', used: u.wallets.used, max: u.wallets.limit },
    { label: 'API keys', used: u.api_keys.used, max: u.api_keys.limit },
    { label: 'Withdrawals this period', used: u.withdrawals_this_period.used, max: u.withdrawals_this_period.included },
  ]
  return rows.map((r) => ({
    label: r.label,
    value: r.max > 0 ? (r.used / r.max) * 100 : 0,
    display: `${r.used} / ${r.max}`,
  }))
})

const kpis = computed(() => [
  { label: 'Organizations', icon: 'building', value: orgs.data.value?.length, error: orgs.isError.value, to: '/organizations' },
  { label: 'Projects', icon: 'folder', value: projects.data.value?.length, error: projects.isError.value, to: '/projects' },
  { label: 'API keys', icon: 'key', value: keys.data.value?.length, error: keys.isError.value, to: '/api-keys' },
  { label: 'Wallets in project', icon: 'wallet', value: projectId.value ? wallets.data.value?.length : undefined, error: wallets.isError.value, to: '/wallets' },
  { label: 'Awaiting approval', icon: 'clock', value: projectId.value ? pendingApprovals.value : undefined, error: withdrawals.isError.value || sweeps.isError.value, to: '/withdrawals' },
])
</script>
<template>
  <div class="space-y-6">
    <header class="flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 class="text-2xl font-bold tracking-tight md:text-3xl">
          Welcome back<span v-if="auth.user">, {{ auth.user.display_name || auth.user.email.split('@')[0] }}</span>
        </h1>
        <p class="mt-1 max-w-2xl text-sm text-ink-muted">
          Live data from your Custodium API — balances, operations and activity below are
          read from the platform in real time. Nothing on this page is sample data.
        </p>
      </div>
      <span class="rounded-full bg-amber-100 px-3.5 py-1.5 text-xs font-semibold text-amber-900">Pre-production · not production approved</span>
    </header>

    <div class="grid gap-4 md:grid-cols-3 xl:grid-cols-5">
      <Card v-for="kpi in kpis" :key="kpi.label">
        <div class="flex items-center justify-between">
          <p class="text-sm font-medium text-ink-muted">{{ kpi.label }}</p>
          <span class="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-50 text-brand-600"><Icon :name="kpi.icon" :size="17" /></span>
        </div>
        <p v-if="kpi.error" class="mt-2 font-medium text-danger">Could not load</p>
        <p v-else-if="kpi.value === undefined" class="mt-2 text-4xl font-bold tracking-tight text-ink-muted">—</p>
        <p v-else class="mt-2 text-4xl font-bold tracking-tight">{{ kpi.value }}</p>
        <RouterLink :to="kpi.to" class="mt-3 inline-block rounded-full bg-brand-600 px-3.5 py-1.5 text-xs font-semibold text-white hover:bg-brand-700">Manage →</RouterLink>
      </Card>
    </div>

    <Card>
      <div class="flex flex-wrap items-center gap-3">
        <label class="text-sm">
          <span class="mb-1 block text-ink-muted">Project for balances &amp; operations</span>
          <select v-model="projectId" class="rounded-lg border border-line bg-white px-3 py-2">
            <option value="">Select a project</option>
            <option v-for="p in projects.data.value ?? []" :key="p.id" :value="p.id">{{ p.name }} ({{ p.environment }})</option>
          </select>
        </label>
        <p v-if="selectedProject" class="text-sm text-ink-muted">
          Showing {{ selectedProject.name }} — charts update from the project's real ledger and operations.
        </p>
      </div>
    </Card>

    <div class="grid gap-4 xl:grid-cols-2">
      <Card title="Available balances by asset">
        <p v-if="balances.isPending.value && projectId" class="text-ink-muted">Loading…</p>
        <p v-else-if="balances.isError.value" class="font-medium text-danger">Could not load balances from the API.</p>
        <EmptyState
          v-else-if="!projectId || !hasBalances"
          title="No balances yet"
          description="Credited deposits will appear here as available balances per asset, in integer base units."
        />
        <HBars v-else :rows="balanceRows" />
      </Card>

      <Card title="Withdrawals by status">
        <p v-if="withdrawals.isPending.value && projectId" class="text-ink-muted">Loading…</p>
        <p v-else-if="withdrawals.isError.value" class="font-medium text-danger">Could not load withdrawals from the API.</p>
        <EmptyState
          v-else-if="!projectId || withdrawalDonut.length === 0"
          title="No withdrawals yet"
          description="Withdrawal requests for this project will be charted here by status."
        />
        <DonutChart v-else :data="withdrawalDonut" ariaLabel="Withdrawals by status" />
      </Card>

      <Card title="Platform activity — audit events per day">
        <p v-if="audit.isPending.value" class="text-ink-muted">Loading…</p>
        <p v-else-if="audit.isError.value" class="font-medium text-danger">Could not load audit events from the API.</p>
        <EmptyState
          v-else-if="(audit.data.value ?? []).length === 0"
          title="No audit events yet"
          description="Recorded security and operations events will be charted here."
        />
        <template v-else>
          <BarChart :data="activity" ariaLabel="Audit events per day, last 14 days" />
          <p class="mt-1 text-xs text-ink-muted">Last 14 days (UTC), counted from the most recent 100 audit events.</p>
        </template>
      </Card>

      <Card title="Plan usage">
        <p v-if="usage.isPending.value && firstOrg" class="text-ink-muted">Loading…</p>
        <p v-else-if="usage.isError.value" class="font-medium text-danger">Could not load usage from the API.</p>
        <EmptyState
          v-else-if="!usage.data.value"
          title="No usage data"
          description="Plan usage appears once an organization exists."
        />
        <template v-else>
          <p class="mb-3 text-sm text-ink-muted">
            {{ firstOrg?.name }} · {{ usage.data.value.plan }} plan ·
            {{ usage.data.value.period_start }} → {{ usage.data.value.period_end }}
          </p>
          <HBars :rows="usageBars" />
        </template>
      </Card>
    </div>

    <Card title="Recent activity">
      <EmptyState
        v-if="recentEvents.length === 0"
        title="Nothing recorded yet"
        description="The latest audit events across your organizations will appear here."
      />
      <ul v-else class="divide-y divide-line">
        <li v-for="e in recentEvents" :key="e.id" class="flex items-center gap-3 py-2.5 text-sm">
          <span class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-surface-muted text-ink-muted"><Icon name="file" :size="16" /></span>
          <span class="font-mono text-xs">{{ e.event_type }}</span>
          <span class="ml-auto whitespace-nowrap text-ink-muted">{{ new Date(e.created_at).toLocaleString() }}</span>
        </li>
      </ul>
      <RouterLink to="/audit" class="mt-3 inline-block text-sm font-medium text-brand-600 hover:underline">Open audit logs →</RouterLink>
    </Card>
  </div>
</template>
