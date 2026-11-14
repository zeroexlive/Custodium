<script setup lang="ts">
import { ref } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { api } from '@/api/client'
import type { CustomerCreated } from '@/api/types'
import { useAuthStore } from '@/stores/auth'
import Card from '@/components/ui/Card.vue'
import Button from '@/components/ui/Button.vue'
import Badge from '@/components/ui/Badge.vue'
import Input from '@/components/ui/Input.vue'
import EmptyState from '@/components/ui/EmptyState.vue'

const auth = useAuthStore()
const queryClient = useQueryClient()
const customers = useQuery({
  queryKey: ['admin-customers'],
  queryFn: api.listCustomers,
  enabled: auth.isPlatformAdmin,
})

const email = ref('')
const displayName = ref('')
const created = ref<CustomerCreated | null>(null)
const createError = ref('')
const create = useMutation({
  mutationFn: () => api.createCustomer({ email: email.value.trim(), display_name: displayName.value.trim() || undefined }),
  onSuccess: (data) => {
    created.value = data
    createError.value = ''
    email.value = ''
    displayName.value = ''
    void queryClient.invalidateQueries({ queryKey: ['admin-customers'] })
  },
  onError: (e) => { createError.value = e instanceof Error ? e.message : 'Request failed' },
})
</script>
<template>
  <div class="space-y-6">
    <h1 class="text-2xl font-semibold">Customers</h1>

    <Card v-if="!auth.isPlatformAdmin" title="Platform administrators only">
      <p class="text-sm text-ink-muted">
        Customer accounts are created by the platform owner and global
        administrators only. Your account does not have that permission —
        the server refuses these requests as well.
      </p>
    </Card>

    <template v-else>
      <Card title="Create a customer account">
        <p class="text-sm text-ink-muted">
          There is no public registration. Creating an account generates a
          temporary password and emails it to the customer; the same password
          is shown to you exactly once below so you can deliver it through
          another channel if the email does not arrive. The customer signs
          in with it and can then set their own password via the
          password-reset flow and enable two-factor authentication.
        </p>
        <form class="mt-4 grid gap-4 md:grid-cols-3" @submit.prevent="create.mutate()">
          <Input id="customer-email" v-model="email" label="Customer email" type="email" required />
          <Input id="customer-name" v-model="displayName" label="Display name (optional)" />
          <div class="flex items-end">
            <Button type="submit" :disabled="create.isPending.value">Create account</Button>
          </div>
        </form>
        <p v-if="createError" role="alert" class="mt-2 text-sm text-danger">{{ createError }}</p>
        <div v-if="created" class="mt-4 rounded-lg border border-line bg-surface-muted p-4 text-sm">
          <p class="font-medium">Account created for {{ created.email }}</p>
          <p class="mt-2">
            Temporary password (shown once):
            <span class="font-mono font-semibold break-all">{{ created.temporary_password }}</span>
          </p>
          <p class="mt-1 text-ink-muted">
            {{ created.credentials_email_sent
              ? 'The credentials were also emailed to the customer.'
              : 'The credentials email could not be sent — deliver the password above to the customer yourself.' }}
          </p>
        </div>
      </Card>

      <Card title="All accounts">
        <p v-if="customers.isPending.value">Loading…</p>
        <p v-else-if="customers.isError.value" role="alert" class="text-danger">Could not load accounts.</p>
        <EmptyState v-else-if="!(customers.data.value ?? []).length" title="No accounts yet"
          description="Accounts created by platform administrators will appear here." />
        <div v-else class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead><tr class="text-left border-b">
              <th scope="col" class="py-2 pr-3">Email</th><th scope="col" class="py-2 pr-3">Name</th>
              <th scope="col" class="py-2 pr-3">Role</th><th scope="col" class="py-2 pr-3">Status</th>
              <th scope="col" class="py-2">Joined</th>
            </tr></thead>
            <tbody>
              <tr v-for="c in customers.data.value" :key="c.id" class="border-b align-top">
                <td class="py-2 pr-3">{{ c.email }}</td>
                <td class="py-2 pr-3">{{ c.display_name || '—' }}</td>
                <td class="py-2 pr-3">
                  <Badge v-if="c.is_superuser" tone="success">Platform owner</Badge>
                  <Badge v-else-if="c.is_staff" tone="success">Global admin</Badge>
                  <span v-else>Customer</span>
                </td>
                <td class="py-2 pr-3">
                  <Badge :tone="c.is_active ? 'success' : 'neutral'">{{ c.is_active ? 'active' : 'disabled' }}</Badge>
                </td>
                <td class="py-2 font-mono text-xs">{{ c.date_joined ?? '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </Card>
    </template>
  </div>
</template>
