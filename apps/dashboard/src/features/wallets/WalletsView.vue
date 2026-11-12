<script setup lang="ts">
import EmptyState from '@/components/ui/EmptyState.vue'
</script>
<template>
  <div class="space-y-6">
    <h1 class="text-2xl font-semibold">Wallets</h1>
    <EmptyState title="Wallets — Phase 2 / Phase 3" description="Status: Planned. Wallet records arrive in Phase 2 and genuine MPC-backed wallet creation only after the Rust threshold-signing service in Phase 3. No wallets are shown here and production signing is disabled — there is no fake or mock MPC in this dashboard." />
  </div>
</template>
