<script setup lang="ts">
defineProps<{ title?: string }>()
</script>
<template>
  <section class="rounded-card border border-black/5 bg-surface p-5 text-ink shadow-card md:p-6" :aria-label="title">
    <h2 v-if="title" class="mb-3 text-sm font-medium text-ink-muted">{{ title }}</h2>
    <slot />
  </section>
</template>
