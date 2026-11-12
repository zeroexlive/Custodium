<script setup lang="ts">
import type { BalanceItem } from '@/api/types'

defineProps<{ items: BalanceItem[] }>()
</script>
<template>
  <div class="overflow-x-auto">
    <table class="w-full text-sm">
      <thead><tr class="text-left border-b">
        <th scope="col" class="py-2 pr-3">Asset</th><th scope="col" class="py-2 pr-3">Network</th>
        <th scope="col" class="py-2 pr-3">Available</th><th scope="col" class="py-2 pr-3">Reserved</th>
        <th scope="col" class="py-2 pr-3">Pending</th><th scope="col" class="py-2">Ledger accounts (base units)</th>
      </tr></thead>
      <tbody>
        <tr v-for="item in items" :key="item.asset_id" class="border-b align-top">
          <td class="py-2 pr-3"><span class="font-medium">{{ item.symbol }}</span>
            <span class="block text-xs text-ink-muted">{{ item.decimals }} decimals</span></td>
          <td class="py-2 pr-3">{{ item.network }}</td>
          <td class="py-2 pr-3 font-mono">{{ item.available }}</td>
          <td class="py-2 pr-3 font-mono">{{ item.reserved }}</td>
          <td class="py-2 pr-3 font-mono">{{ item.pending }}</td>
          <td class="py-2 font-mono text-xs">
            <div v-for="(value, kind) in item.accounts" :key="kind">{{ kind }}: {{ value }}</div>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
