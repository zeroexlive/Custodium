<script setup lang="ts">
import EmptyState from '@/components/ui/EmptyState.vue'
</script>
<template>
  <div class="space-y-6">
    <h1 class="text-2xl font-semibold">Manual Address Blacklist</h1>
    <EmptyState title="Manual blacklist — Phase 9 / 10" description="Status: Planned. This is a locally managed manual blacklist only (platform-wide and tenant-specific entries, checked during withdrawal validation and again before signing). Custodium does not integrate third-party AML/KYT or risk-scoring services, and this list is not a complete AML compliance system. No entries are displayed yet." />
  </div>
</template>
