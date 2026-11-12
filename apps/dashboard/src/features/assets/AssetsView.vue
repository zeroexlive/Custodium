<script setup lang="ts">
import { useQuery } from '@tanstack/vue-query'
import { api } from '@/api/client'
import Card from '@/components/ui/Card.vue'
import Badge from '@/components/ui/Badge.vue'
import EmptyState from '@/components/ui/EmptyState.vue'

const assets = useQuery({ queryKey: ['assets'], queryFn: api.listAssets })
const networks = useQuery({ queryKey: ['networks'], queryFn: api.listNetworks })
</script>
<template>
  <div class="space-y-6">
    <h1 class="text-2xl font-semibold">Assets &amp; Networks</h1>
    <Card title="Networks">
      <p v-if="networks.isPending.value">Loading…</p>
      <p v-else-if="networks.isError.value" role="alert" class="text-danger">Could not load networks.</p>
      <ul v-else class="flex flex-wrap gap-2">
        <li v-for="n in networks.data.value ?? []" :key="n.id"><Badge>{{ n.name }} ({{ n.native_symbol }}){{ n.is_testnet ? ' · testnet' : '' }}</Badge></li>
      </ul>
    </Card>
    <Card title="Assets">
      <p class="text-sm text-ink-muted mb-3">Assets are identified by network + contract/mint address, never by symbol alone. Binance-Peg USDT on BSC is classified separately from issuer-native Tether USD₮.</p>
      <p v-if="assets.isPending.value">Loading…</p>
      <p v-else-if="assets.isError.value" role="alert" class="text-danger">Could not load assets.</p>
      <EmptyState v-else-if="!assets.data.value?.length" title="No assets returned" description="Asset registry data (Phase 2) will appear here once the API returns it." />
      <div v-else class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead><tr class="text-left border-b">
            <th scope="col" class="py-2 pr-3">Network</th><th scope="col" class="py-2 pr-3">Symbol</th>
            <th scope="col" class="py-2 pr-3">Name</th><th scope="col" class="py-2 pr-3">Decimals</th>
            <th scope="col" class="py-2 pr-3">Contract / mint</th><th scope="col" class="py-2 pr-3">Issuer classification</th>
            <th scope="col" class="py-2">Verification</th>
          </tr></thead>
          <tbody>
            <tr v-for="a in assets.data.value" :key="a.id" class="border-b">
              <td class="py-2 pr-3">{{ a.network }}</td><td class="py-2 pr-3 font-medium">{{ a.symbol }}</td>
              <td class="py-2 pr-3">{{ a.name }}</td><td class="py-2 pr-3">{{ a.decimals }}</td>
              <td class="py-2 pr-3 font-mono text-xs break-all">{{ a.contract_or_mint_address ?? 'native' }}</td>
              <td class="py-2 pr-3">{{ a.issuer_classification }}</td>
              <td class="py-2"><Badge :tone="a.verification_status === 'verified' ? 'success' : 'warning'">{{ a.verification_status }}</Badge></td>
            </tr>
          </tbody>
        </table>
      </div>
    </Card>
  </div>
</template>
