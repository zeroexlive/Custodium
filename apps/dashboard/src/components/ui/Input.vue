<script setup lang="ts">
defineProps<{ id: string; label: string; modelValue: string; type?: string; required?: boolean; autocomplete?: string; placeholder?: string }>()
defineEmits<{ 'update:modelValue': [value: string] }>()
</script>
<template>
  <div class="space-y-1">
    <label :for="id" class="block text-sm font-medium">{{ label }}</label>
    <input :id="id" :type="type ?? 'text'" :value="modelValue" :required="required" :autocomplete="autocomplete" :placeholder="placeholder"
      class="w-full rounded border border-gray-300 dark:border-gray-600 bg-surface px-3 py-2 text-sm"
      @input="$emit('update:modelValue', ($event.target as HTMLInputElement).value)" />
  </div>
</template>
