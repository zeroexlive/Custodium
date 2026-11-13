<script setup lang="ts">
import { computed } from 'vue'
import { fractionsOfMax } from './chartMath'

export interface HBarRow { label: string; value: number; display: string }

const props = withDefaults(
  defineProps<{ rows: HBarRow[]; color?: string }>(),
  { color: '#2563eb' },
)
const fractions = computed(() => fractionsOfMax(props.rows.map((r) => r.value)))
</script>
<template>
  <ul class="space-y-3">
    <li v-for="(row, i) in rows" :key="row.label">
      <div class="flex items-baseline justify-between gap-3 text-sm">
        <span class="font-medium">{{ row.label }}</span>
        <span class="font-mono text-xs text-ink-muted">{{ row.display }}</span>
      </div>
      <div class="mt-1 h-2.5 overflow-hidden rounded-full bg-black/8 dark:bg-white/10">
        <div
          class="h-full rounded-full transition-all"
          :style="{ width: `${Math.max((fractions[i] ?? 0) * 100, row.value > 0 ? 2 : 0)}%`, background: color }"
        />
      </div>
    </li>
  </ul>
</template>
