<script setup lang="ts">
import EmptyState from '@/components/ui/EmptyState.vue'
</script>
<template>
  <div class="space-y-6">
    <h1 class="text-2xl font-semibold">Sweeps</h1>
    <EmptyState title="Sweeps — Phase 10" description="Status: Planned for Phase 10 (sweeping & treasury). When implemented, a sweep request will never contain a destination address — the destination is resolved per-sweep from your registered HTTPS endpoint (see Sweep Endpoint), snapshotted immutably, approved, and signed via MPC. No sweep data is displayed yet." />
  </div>
</template>
