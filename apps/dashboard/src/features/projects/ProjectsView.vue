<script setup lang="ts">
import { ref } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { api } from '@/api/client'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'
import Card from '@/components/ui/Card.vue'
import Badge from '@/components/ui/Badge.vue'
import EmptyState from '@/components/ui/EmptyState.vue'

const name = ref(''); const organizationId = ref(''); const environment = ref<'sandbox' | 'production'>('sandbox')
const client = useQueryClient()
const orgs = useQuery({ queryKey: ['organizations'], queryFn: api.listOrganizations })
const query = useQuery({ queryKey: ['projects'], queryFn: api.listProjects })
const mutation = useMutation({
  mutationFn: () => api.createProject({ organization_id: organizationId.value, name: name.value, environment: environment.value }),
  onSuccess: async () => { name.value = ''; await client.invalidateQueries({ queryKey: ['projects'] }) },
})
function submit(): void { if (name.value.trim() && organizationId.value) mutation.mutate() }
</script>
<template>
  <div class="space-y-6">
    <h1 class="text-2xl font-semibold">Projects</h1>
    <Card title="Create project">
      <form class="space-y-4" @submit.prevent="submit">
        <div class="space-y-1">
          <label for="project-org" class="block text-sm font-medium">Organization</label>
          <select id="project-org" v-model="organizationId" required class="w-full rounded border border-gray-300 dark:border-gray-600 bg-surface px-3 py-2 text-sm">
            <option value="" disabled>Select an organization</option>
            <option v-for="org in orgs.data.value ?? []" :key="org.id" :value="org.id">{{ org.name }}</option>
          </select>
        </div>
        <Input id="project-name" v-model="name" label="Project name" required />
        <div class="space-y-1">
          <label for="project-env" class="block text-sm font-medium">Environment</label>
          <select id="project-env" v-model="environment" class="w-full rounded border border-gray-300 dark:border-gray-600 bg-surface px-3 py-2 text-sm">
            <option value="sandbox">Sandbox</option><option value="production">Production</option>
          </select>
        </div>
        <Button type="submit" :disabled="mutation.isPending.value">Create project</Button>
        <p v-if="mutation.isError.value" role="alert" class="text-sm text-danger">{{ (mutation.error.value as Error).message }}</p>
      </form>
    </Card>
    <Card title="Your projects">
      <p v-if="query.isPending.value">Loading…</p>
      <p v-else-if="query.isError.value" role="alert" class="text-danger">Could not load projects.</p>
      <EmptyState v-else-if="!query.data.value?.length" title="No projects yet" description="Create a project to issue API credentials." />
      <ul v-else class="divide-y">
        <li v-for="p in query.data.value" :key="p.id" class="py-2 flex justify-between items-center">
          <span>{{ p.name }}</span><Badge :tone="p.environment === 'production' ? 'warning' : 'neutral'">{{ p.environment }}</Badge>
        </li>
      </ul>
    </Card>
  </div>
</template>
