<script setup lang="ts">
import { ref } from 'vue'
import { api, ApiError } from '@/api/client'
import type { TransactionLookup } from '@/api/types'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'
import Card from '@/components/ui/Card.vue'
import Badge from '@/components/ui/Badge.vue'

const network = ref('ethereum'); const hash = ref('')
const result = ref<TransactionLookup | null>(null)
const error = ref<string | null>(null); const loading = ref(false)
const networks = ['ethereum', 'ethereum-sepolia', 'bsc', 'bsc-testnet', 'tron', 'tron-nile', 'solana', 'solana-devnet', 'ton', 'ton-testnet']

async function submit(): Promise<void> {
  error.value = null; result.value = null; loading.value = true
  try { result.value = await api.lookupTransaction(network.value, hash.value.trim()) }
  catch (e) { error.value = e instanceof ApiError ? e.message : 'Lookup failed.' }
  finally { loading.value = false }
}
</script>
<template>
  <div class="space-y-6">
    <h1 class="text-2xl font-semibold">Transaction Hash Explorer</h1>
    <p class="text-ink-muted">Wired to <code class="font-mono text-sm">GET /api/v1/transactions/lookup</code>. Full detail is shown only for your own transactions; other transactions return the public on-chain minimum.</p>
    <Card title="Look up a transaction">
      <form class="space-y-4" @submit.prevent="submit">
        <div class="space-y-1">
          <label for="tx-network" class="block text-sm font-medium">Network</label>
          <select id="tx-network" v-model="network" class="w-full rounded border border-gray-300 dark:border-gray-600 bg-surface px-3 py-2 text-sm">
            <option v-for="n in networks" :key="n" :value="n">{{ n }}</option>
          </select>
        </div>
        <Input id="tx-hash" v-model="hash" label="Transaction hash / signature" required placeholder="0x…" />
        <Button type="submit" :disabled="loading">Look up</Button>
      </form>
      <p v-if="error" role="alert" class="text-sm text-danger mt-3">{{ error }}</p>
    </Card>
    <Card v-if="result" title="Result">
      <dl class="space-y-2 text-sm">
        <div class="flex gap-2"><dt class="font-medium">Status</dt><dd><Badge>{{ result.status }}</Badge></dd></div>
        <div class="flex gap-2"><dt class="font-medium">Indexed</dt><dd>{{ result.indexed ? 'Yes' : 'No — local index does not yet cover this transaction' }}</dd></div>
        <div class="flex gap-2"><dt class="font-medium">Belongs to your tenant</dt><dd>{{ result.belongs_to_tenant ? 'Yes' : 'No' }}</dd></div>
        <div class="flex gap-2"><dt class="font-medium">Confirmations</dt><dd>{{ result.confirmations ?? '—' }}</dd></div>
      </dl>
      <h3 class="font-medium mt-4">Matched addresses</h3>
      <p v-if="!result.matched_addresses.length" class="text-sm text-ink-muted">None of your addresses participated in this transaction.</p>
      <ul v-else class="text-sm divide-y">
        <li v-for="a in result.matched_addresses" :key="a.address_id" class="py-1">{{ a.role }} — wallet {{ a.wallet_id }}<span v-if="a.external_customer_id"> — customer UID {{ a.external_customer_id }}</span></li>
      </ul>
      <template v-if="result.tenant_record?.type === 'withdrawal'">
        <h3 class="font-medium mt-4">Withdrawal requested by</h3>
        <p class="text-sm">
          Customer UID <span class="font-mono">{{ result.tenant_record.external_customer_id || '—' }}</span>
          <span v-if="result.tenant_record.external_reference"> · their reference: {{ result.tenant_record.external_reference }}</span>
          <span v-if="result.tenant_record.withdrawal_request_id"> · request {{ result.tenant_record.withdrawal_request_id }}</span>
        </p>
      </template>
      <h3 class="font-medium mt-4">Transfers</h3>
      <p v-if="!result.transfers.length" class="text-sm text-ink-muted">No relevant transfers parsed.</p>
      <ul v-else class="text-sm divide-y">
        <li v-for="t in result.transfers" :key="t.transfer_id" class="py-1 font-mono">{{ t.direction }} {{ t.amount_base_units }} base units (decimals {{ t.decimals }})</li>
      </ul>
    </Card>
  </div>
</template>
