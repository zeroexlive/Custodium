<script setup lang="ts">
import { computed, ref } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { api } from '@/api/client'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import Badge from '@/components/ui/Badge.vue'

const client = useQueryClient()
const orgId = ref('')
const orgs = useQuery({ queryKey: ['organizations'], queryFn: api.listOrganizations })
const plans = useQuery({ queryKey: ['plans'], queryFn: api.listPlans })
const usage = useQuery({
  queryKey: computed(() => ['usage', orgId.value]),
  queryFn: () => api.getUsage(orgId.value),
  enabled: computed(() => orgId.value !== ''),
})
const invoices = useQuery({
  queryKey: computed(() => ['invoices', orgId.value]),
  queryFn: () => api.listInvoices(orgId.value),
  enabled: computed(() => orgId.value !== ''),
})
const chosenPlan = ref('')
const subscribe = useMutation({
  mutationFn: () => api.setSubscription(orgId.value, chosenPlan.value),
  onSuccess: () => {
    void client.invalidateQueries({ queryKey: ['usage', orgId.value] })
    void client.invalidateQueries({ queryKey: ['invoices', orgId.value] })
  },
})
const markPaid = useMutation({
  mutationFn: (id: string) => api.markInvoicePaid(id),
  onSuccess: () => void client.invalidateQueries({ queryKey: ['invoices', orgId.value] }),
})
const dollars = (cents: number): string => `$${(cents / 100).toFixed(2)}`
</script>

<template>
  <div class="space-y-6">
    <div>
      <h1 class="text-2xl font-semibold">Billing</h1>
      <p class="text-sm text-ink-muted">
        Fiat billing for the SaaS plan — separate from the custody ledger, which remains the crypto
        system of record. Invoices are generated from the plan price plus metered withdrawal overage;
        payment is collected off-platform and marked paid here.
      </p>
    </div>

    <Card>
      <label class="text-sm font-medium">Organization</label>
      <select v-model="orgId" class="mt-1 block w-full rounded-lg border px-3 py-2">
        <option value="">Select an organization…</option>
        <option v-for="o in orgs.data.value ?? []" :key="o.id" :value="o.id">{{ o.name }}</option>
      </select>
    </Card>

    <template v-if="orgId && usage.data.value">
      <div class="grid gap-4 md:grid-cols-3">
        <Card>
          <p class="text-sm text-slate-500">Current plan</p>
          <p class="mt-1 text-2xl font-semibold capitalize">{{ usage.data.value.plan }}</p>
          <p class="text-sm text-slate-500">{{ usage.data.value.period_start }} → {{ usage.data.value.period_end }}</p>
        </Card>
        <Card>
          <p class="text-sm text-slate-500">Wallets</p>
          <p class="mt-1 text-2xl font-semibold">{{ usage.data.value.wallets.used }} / {{ usage.data.value.wallets.limit }}</p>
        </Card>
        <Card>
          <p class="text-sm text-slate-500">Withdrawals this period</p>
          <p class="mt-1 text-2xl font-semibold">
            {{ usage.data.value.withdrawals_this_period.used }}
            <span class="text-base text-slate-500">/ {{ usage.data.value.withdrawals_this_period.included }} included</span>
          </p>
        </Card>
      </div>

      <Card>
        <h2 class="font-medium">Change plan</h2>
        <div class="mt-3 flex flex-wrap items-end gap-3">
          <select v-model="chosenPlan" class="rounded-lg border px-3 py-2">
            <option value="">Choose a plan…</option>
            <option v-for="plan in plans.data.value ?? []" :key="plan.slug" :value="plan.slug">
              {{ plan.name }} — {{ dollars(plan.monthly_price_cents) }}/mo
            </option>
          </select>
          <Button :disabled="!chosenPlan || subscribe.isPending.value" @click="subscribe.mutate()">Subscribe</Button>
        </div>
      </Card>

      <Card>
        <h2 class="font-medium">Invoices</h2>
        <table class="mt-3 w-full text-sm">
          <thead><tr class="text-left text-slate-500"><th class="py-1">Period</th><th>Total</th><th>Status</th><th></th></tr></thead>
          <tbody>
            <tr v-for="invoice in invoices.data.value ?? []" :key="invoice.id" class="border-t">
              <td class="py-2">{{ invoice.period_start }} → {{ invoice.period_end }}</td>
              <td>{{ dollars(invoice.total_cents) }} {{ invoice.currency }}</td>
              <td><Badge :tone="invoice.status === 'paid' ? 'success' : 'warning'">{{ invoice.status }}</Badge></td>
              <td><Button v-if="invoice.status === 'issued'" @click="markPaid.mutate(invoice.id)">Mark paid</Button></td>
            </tr>
          </tbody>
        </table>
        <p v-if="(invoices.data.value ?? []).length === 0" class="mt-2 text-sm text-ink-muted">No invoices yet.</p>
      </Card>
    </template>
  </div>
</template>
