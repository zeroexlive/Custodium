<script setup lang="ts">
import EmptyState from '@/components/ui/EmptyState.vue'
</script>
<template>
  <div class="space-y-6">
    <h1 class="text-2xl font-semibold">Webhooks</h1>
    <EmptyState title="Webhooks — Phase 9 / 11" description="Status: Planned. HMAC-signed deliveries with replay protection, retries, dead-letter handling and delivery logs will be managed here once the webhook backend lands. No endpoints or fake deliveries are shown." />
  </div>
</template>
