<script setup lang="ts">
defineProps<{ title: string; description: string }>()
</script>
<template>
  <div class="border border-dashed border-gray-300 dark:border-gray-600 rounded-card p-6 text-center" role="status">
    <h3 class="font-medium">{{ title }}</h3>
    <p class="text-sm text-ink-muted mt-1">{{ description }}</p>
    <slot />
  </div>
</template>
