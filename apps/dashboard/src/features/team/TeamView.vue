<script setup lang="ts">
import { computed, ref } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { api } from '@/api/client'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'
import Card from '@/components/ui/Card.vue'
import EmptyState from '@/components/ui/EmptyState.vue'

const ROLES = ['owner', 'administrator', 'developer', 'finance_operator', 'withdrawal_approver', 'viewer']
const client = useQueryClient()
const orgId = ref('')
const orgs = useQuery({ queryKey: ['organizations'], queryFn: api.listOrganizations })
const members = useQuery({
  queryKey: computed(() => ['members', orgId.value]),
  queryFn: () => api.listMembers(orgId.value),
  enabled: computed(() => orgId.value !== ''),
})
const email = ref('')
const role = ref('viewer')
const formError = ref('')
const add = useMutation({
  mutationFn: () => api.addMember(orgId.value, email.value.trim(), role.value),
  onSuccess: () => {
    formError.value = ''
    email.value = ''
    void client.invalidateQueries({ queryKey: ['members', orgId.value] })
  },
  onError: (e) => { formError.value = e instanceof Error ? e.message : 'Request failed' },
})
const changeRole = useMutation({
  mutationFn: (args: { id: string; role: string }) => api.updateMemberRole(orgId.value, args.id, args.role),
  onSuccess: () => void client.invalidateQueries({ queryKey: ['members', orgId.value] }),
})
const remove = useMutation({
  mutationFn: (id: string) => api.removeMember(orgId.value, id),
  onSuccess: () => void client.invalidateQueries({ queryKey: ['members', orgId.value] }),
})
</script>

<template>
  <div class="space-y-6">
    <div>
      <h1 class="text-2xl font-semibold">Team</h1>
      <p class="text-sm text-ink-muted">
        Organization members and roles. Only owners and administrators can change membership;
        the last owner can never be removed or demoted. Every change is written to the audit log.
      </p>
    </div>

    <Card>
      <label class="text-sm font-medium">Organization</label>
      <select v-model="orgId" class="mt-1 block w-full rounded-lg border px-3 py-2">
        <option value="">Select an organization…</option>
        <option v-for="o in orgs.data.value ?? []" :key="o.id" :value="o.id">{{ o.name }}</option>
      </select>
    </Card>

    <template v-if="orgId">
      <Card>
        <h2 class="font-medium">Add member</h2>
        <p class="mt-1 text-sm text-ink-muted">The person must already have a Custodium account with this email.</p>
        <div class="mt-3 grid gap-3 md:grid-cols-3">
          <Input id="member-email" v-model="email" label="Email" placeholder="teammate@example.com" />
          <div>
            <label class="block text-sm font-medium">Role</label>
            <select v-model="role" class="mt-1 block w-full rounded-lg border px-3 py-2">
              <option v-for="r in ROLES" :key="r" :value="r">{{ r }}</option>
            </select>
          </div>
          <div class="flex items-end"><Button :disabled="add.isPending.value" @click="add.mutate()">Add member</Button></div>
        </div>
        <p v-if="formError" class="mt-2 text-sm text-red-600">{{ formError }}</p>
      </Card>

      <Card>
        <h2 class="font-medium">Members</h2>
        <EmptyState
          v-if="(members.data.value ?? []).length === 0"
          title="No members"
          description="Members of this organization will appear here."
        />
        <table v-else class="mt-3 w-full text-sm">
          <thead><tr class="text-left text-slate-500"><th class="py-1">Email</th><th>Role</th><th>Since</th><th></th></tr></thead>
          <tbody>
            <tr v-for="m in members.data.value ?? []" :key="m.membership_id" class="border-t">
              <td class="py-2">{{ m.email }}</td>
              <td>
                <select
                  :value="m.role" class="rounded-lg border px-2 py-1"
                  @change="changeRole.mutate({ id: m.membership_id, role: ($event.target as HTMLSelectElement).value })"
                >
                  <option v-for="r in ROLES" :key="r" :value="r">{{ r }}</option>
                </select>
              </td>
              <td>{{ new Date(m.created_at).toLocaleDateString() }}</td>
              <td><Button @click="remove.mutate(m.membership_id)">Remove</Button></td>
            </tr>
          </tbody>
        </table>
      </Card>
    </template>
  </div>
</template>
