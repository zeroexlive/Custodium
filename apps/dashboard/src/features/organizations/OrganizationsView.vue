<script setup lang="ts">
import { ref } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { api } from '@/api/client'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'
import Card from '@/components/ui/Card.vue'
import EmptyState from '@/components/ui/EmptyState.vue'

const name = ref('')
const client = useQueryClient()
const query = useQuery({ queryKey: ['organizations'], queryFn: api.listOrganizations })
const mutation = useMutation({
  mutationFn: () => api.createOrganization({ name: name.value }),
  onSuccess: async () => { name.value = ''; await client.invalidateQueries({ queryKey: ['organizations'] }) },
})
function submit(): void { if (name.value.trim()) mutation.mutate() }
</script>
<template>
  <div class="space-y-6">
    <h1 class="text-2xl font-semibold">Organizations</h1>
    <Card title="Create organization">
      <form class="flex gap-3 items-end" @submit.prevent="submit">
        <Input id="org-name" v-model="name" label="Name" required />
        <Button type="submit" :disabled="mutation.isPending.value">Create</Button>
      </form>
      <p v-if="mutation.isError.value" role="alert" class="text-sm text-danger mt-2">{{ (mutation.error.value as Error).message }}</p>
    </Card>
    <Card title="Your organizations">
      <p v-if="query.isPending.value">Loading…</p>
      <p v-else-if="query.isError.value" role="alert" class="text-danger">Could not load organizations.</p>
      <EmptyState v-else-if="!query.data.value?.length" title="No organizations yet" description="Create your first organization above." />
      <ul v-else class="divide-y">
        <li v-for="org in query.data.value" :key="org.id" class="py-2 flex justify-between">
          <span>{{ org.name }}</span><span class="text-sm text-ink-muted">{{ org.role ?? '' }}</span>
        </li>
      </ul>
    </Card>
  </div>
</template>
