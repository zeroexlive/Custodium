<script setup lang="ts">
withDefaults(defineProps<{ tone?: 'neutral' | 'success' | 'warning' | 'danger' }>(), { tone: 'neutral' })
</script>
<template>
  <span :class="tone === 'success' ? 'bg-green-100 text-green-800' : tone === 'warning' ? 'bg-amber-100 text-amber-800' : tone === 'danger' ? 'bg-red-100 text-red-800' : 'bg-gray-100 text-gray-800'"
    class="inline-flex rounded-full px-2 py-0.5 text-xs font-medium"><slot /></span>
</template>
