<script setup lang="ts">
import { useQuery } from '@tanstack/vue-query'
import { api } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import Card from '@/components/ui/Card.vue'

const auth = useAuthStore()
const orgs = useQuery({ queryKey: ['organizations'], queryFn: api.listOrganizations, retry: false })
const projects = useQuery({ queryKey: ['projects'], queryFn: api.listProjects, retry: false })
const keys = useQuery({ queryKey: ['api-keys'], queryFn: () => api.listApiKeys(), retry: false })
</script>
<template>
  <div class="space-y-6">
    <header class="flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 class="text-2xl font-bold tracking-tight md:text-3xl">
          Welcome back<span v-if="auth.user">, {{ auth.user.display_name || auth.user.email.split('@')[0] }}</span>
        </h1>
        <p class="mt-1 max-w-2xl text-sm text-ink-muted">
          Phase 1 — SaaS foundation: authentication, organizations, projects and API credentials.
          Wallet, deposit and withdrawal data arrives in later phases; nothing here is sample data.
        </p>
      </div>
      <span class="rounded-full bg-gray-900 px-3.5 py-1.5 text-xs font-semibold text-white dark:bg-white dark:text-gray-900">Phase 1 · In progress</span>
    </header>

    <div class="grid gap-4 md:grid-cols-3">
      <Card title="Organizations">
        <p v-if="orgs.isPending.value" class="text-ink-muted">Loading…</p>
        <p v-else-if="orgs.isError.value" class="font-medium text-danger">Could not load organizations from the API.</p>
        <template v-else>
          <p class="text-4xl font-bold tracking-tight">{{ orgs.data.value?.length ?? 0 }}</p>
          <RouterLink to="/organizations" class="mt-4 inline-block rounded-full bg-brand-600 px-3.5 py-1.5 text-xs font-semibold text-white hover:bg-brand-700">Manage →</RouterLink>
        </template>
      </Card>
      <Card title="Projects">
        <p v-if="projects.isPending.value" class="text-ink-muted">Loading…</p>
        <p v-else-if="projects.isError.value" class="font-medium text-danger">Could not load projects from the API.</p>
        <template v-else>
          <p class="text-4xl font-bold tracking-tight">{{ projects.data.value?.length ?? 0 }}</p>
          <RouterLink to="/projects" class="mt-4 inline-block rounded-full bg-brand-600 px-3.5 py-1.5 text-xs font-semibold text-white hover:bg-brand-700">Manage →</RouterLink>
        </template>
      </Card>
      <Card title="API Keys">
        <p v-if="keys.isPending.value" class="text-ink-muted">Loading…</p>
        <p v-else-if="keys.isError.value" class="font-medium text-danger">Could not load API keys from the API.</p>
        <template v-else>
          <p class="text-4xl font-bold tracking-tight">{{ keys.data.value?.length ?? 0 }}</p>
          <RouterLink to="/api-keys" class="mt-4 inline-block rounded-full bg-brand-600 px-3.5 py-1.5 text-xs font-semibold text-white hover:bg-brand-700">Manage →</RouterLink>
        </template>
      </Card>
    </div>

    <Card title="Getting started">
      <ol class="list-decimal space-y-2 pl-5 text-sm">
        <li>Create an organization, then a project (sandbox or production).</li>
        <li>Issue an API key for the project — the secret is shown exactly once.</li>
        <li>Make an HMAC-signed API request to verify your integration.</li>
      </ol>
      <p class="mt-3 text-sm text-ink-muted">
        Balances, cash-flow charts and transaction tables will appear here only when they are backed by
        real indexed chain data (Phase 5+) — this dashboard never displays invented financial figures.
      </p>
    </Card>
  </div>
</template>
