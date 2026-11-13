<script setup lang="ts">
import { computed, ref } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { api } from '@/api/client'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import Input from '@/components/ui/Input.vue'

const client = useQueryClient()
const projectId = ref('')
const projects = useQuery({ queryKey: ['projects'], queryFn: api.listProjects })
const networks = useQuery({ queryKey: ['networks'], queryFn: api.listNetworks })
const entries = useQuery({
  queryKey: computed(() => ['address-book', projectId.value]),
  queryFn: () => api.listAddressBook(projectId.value),
  enabled: computed(() => projectId.value !== ''),
})
const policy = useQuery({
  queryKey: computed(() => ['address-book-policy', projectId.value]),
  queryFn: () => api.getAddressBookPolicy(projectId.value),
  enabled: computed(() => projectId.value !== ''),
})

const form = ref({ network: 'ethereum', address: '', label: '' })
const formError = ref('')
const add = useMutation({
  mutationFn: () => api.addAddressBookEntry({ project_id: projectId.value, ...form.value }),
  onSuccess: () => {
    form.value = { network: form.value.network, address: '', label: '' }
    formError.value = ''
    void client.invalidateQueries({ queryKey: ['address-book', projectId.value] })
  },
  onError: (e) => { formError.value = e instanceof Error ? e.message : 'Request failed' },
})
const remove = useMutation({
  mutationFn: (id: string) => api.deleteAddressBookEntry(id),
  onSuccess: () => void client.invalidateQueries({ queryKey: ['address-book', projectId.value] }),
})
const setPolicy = useMutation({
  mutationFn: (required: boolean) => api.setAddressBookPolicy(projectId.value, required),
  onSuccess: () => void client.invalidateQueries({ queryKey: ['address-book-policy', projectId.value] }),
})
</script>

<template>
  <div class="space-y-6">
    <div>
      <h1 class="text-2xl font-semibold">Address book</h1>
      <p class="text-sm text-ink-muted">
        Vetted destination addresses for this project. When the withdrawal allowlist is
        required, withdrawals can only go to addresses listed here — checked next to the
        blacklist on every withdrawal request.
      </p>
    </div>

    <Card>
      <div class="flex flex-wrap items-end gap-3">
        <label class="text-sm">
          <span class="mb-1 block text-ink-muted">Project</span>
          <select v-model="projectId" class="rounded-lg border border-line bg-white px-3 py-2">
            <option value="">Select a project</option>
            <option v-for="p in projects.data.value ?? []" :key="p.id" :value="p.id">{{ p.name }}</option>
          </select>
        </label>
        <label v-if="projectId" class="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            :checked="policy.data.value?.withdrawal_allowlist_required === true"
            :disabled="setPolicy.isPending.value"
            @change="setPolicy.mutate(($event.target as HTMLInputElement).checked)"
          >
          Require address-book allowlist for withdrawals
        </label>
      </div>
    </Card>

    <template v-if="projectId">
      <Card title="Add an address">
        <form class="flex flex-wrap items-end gap-3" @submit.prevent="add.mutate()">
          <label class="text-sm">
            <span class="mb-1 block text-ink-muted">Network</span>
            <select v-model="form.network" class="rounded-lg border border-line bg-white px-3 py-2">
              <option v-for="n in networks.data.value ?? []" :key="n.slug" :value="n.slug">{{ n.slug }}</option>
            </select>
          </label>
          <Input id="ab-address" v-model="form.address" label="Address" required class="min-w-80" />
          <Input id="ab-label" v-model="form.label" label="Label (optional)" />
          <Button type="submit" :disabled="add.isPending.value">Add</Button>
        </form>
        <p v-if="formError" role="alert" class="mt-2 text-sm text-danger">{{ formError }}</p>
      </Card>

      <Card title="Entries">
        <EmptyState
          v-if="(entries.data.value ?? []).length === 0"
          title="No addresses yet"
          description="Add the first vetted destination address for this project."
        />
        <table v-else class="w-full text-left text-sm">
          <thead>
            <tr class="text-ink-muted">
              <th class="py-2 pr-4">Network</th>
              <th class="py-2 pr-4">Address</th>
              <th class="py-2 pr-4">Label</th>
              <th class="py-2" />
            </tr>
          </thead>
          <tbody>
            <tr v-for="entry in entries.data.value ?? []" :key="entry.id" class="border-t border-line">
              <td class="py-2 pr-4">{{ entry.network }}</td>
              <td class="py-2 pr-4 font-mono break-all">{{ entry.address }}</td>
              <td class="py-2 pr-4">{{ entry.label }}</td>
              <td class="py-2 text-right">
                <Button variant="secondary" :disabled="remove.isPending.value" @click="remove.mutate(entry.id)">Remove</Button>
              </td>
            </tr>
          </tbody>
        </table>
      </Card>
    </template>
  </div>
</template>
