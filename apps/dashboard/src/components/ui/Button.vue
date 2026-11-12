<script setup lang="ts">
withDefaults(defineProps<{ type?: 'button' | 'submit'; variant?: 'primary' | 'secondary' | 'danger'; disabled?: boolean; ariaLabel?: string }>(), {
  type: 'button', variant: 'primary', disabled: false, ariaLabel: undefined,
})
</script>
<template>
  <button :type="type" :disabled="disabled" :aria-label="ariaLabel"
    :class="variant === 'primary' ? 'bg-gray-900 text-white hover:bg-gray-700 dark:bg-white dark:text-gray-900 dark:hover:bg-gray-200' : variant === 'danger' ? 'bg-danger text-white hover:opacity-90' : 'bg-surface text-ink border border-gray-300 hover:bg-gray-50 dark:border-gray-600 dark:hover:bg-gray-800'"
    class="inline-flex items-center justify-center rounded-xl px-4 py-2.5 text-sm font-medium shadow-card transition disabled:opacity-50">
    <slot />
  </button>
</template>
