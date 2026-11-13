<script setup lang="ts">
import { useQuery } from '@tanstack/vue-query'
import { api } from '@/api/client'
import Card from '@/components/ui/Card.vue'
import EmptyState from '@/components/ui/EmptyState.vue'

const logs = useQuery({ queryKey: ['audit-logs'], queryFn: api.listAuditLogs, retry: false })
</script>
<template>
  <div class="space-y-6">
    <div>
      <h1 class="text-2xl font-semibold">Audit Logs</h1>
      <p class="text-sm text-ink-muted">
        Security and operations events recorded by the backend for your
        organizations — the most recent 100. The full log exports as CSV
        from the API (<code>GET /audit-logs/export</code>).
      </p>
    </div>
    <Card>
      <p v-if="logs.isPending.value" class="text-ink-muted">Loading…</p>
      <p v-else-if="logs.isError.value" role="alert" class="text-danger">Could not load audit events from the API.</p>
      <EmptyState
        v-else-if="(logs.data.value ?? []).length === 0"
        title="No audit events yet"
        description="Events appear here as you and your team use the platform."
      />
      <table v-else class="w-full text-left text-sm">
        <thead>
          <tr class="text-ink-muted">
            <th class="py-2 pr-4">Event</th>
            <th class="py-2 pr-4">Project</th>
            <th class="py-2">Recorded</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="e in logs.data.value ?? []" :key="e.id" class="border-t border-line">
            <td class="py-2 pr-4 font-mono text-xs">{{ e.event_type }}</td>
            <td class="py-2 pr-4 font-mono text-xs">{{ e.project_id ? e.project_id.slice(0, 8) + '…' : '—' }}</td>
            <td class="py-2 whitespace-nowrap">{{ new Date(e.created_at).toLocaleString() }}</td>
          </tr>
        </tbody>
      </table>
    </Card>
  </div>
</template>
