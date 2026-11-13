<script setup lang="ts">
import { computed } from 'vue'
import { donutSegments } from './chartMath'

export interface DonutDatum { label: string; value: number; color: string }

const props = defineProps<{ data: DonutDatum[]; ariaLabel: string }>()

const R = 48
const C = 2 * Math.PI * R
const segments = computed(() => donutSegments(props.data.map((d) => d.value), C))
const total = computed(() => props.data.reduce((a, d) => a + d.value, 0))
</script>
<template>
  <div class="flex flex-wrap items-center gap-5">
    <svg viewBox="0 0 120 120" class="h-36 w-36 shrink-0" role="img" :aria-label="ariaLabel">
      <g transform="rotate(-90 60 60)">
        <circle cx="60" cy="60" :r="R" fill="none" stroke="currentColor" stroke-opacity="0.08" stroke-width="15" />
        <circle
          v-for="(d, i) in data" :key="d.label"
          cx="60" cy="60" :r="R" fill="none" :stroke="d.color" stroke-width="15"
          :stroke-dasharray="segments[i]?.dash ?? ''" :stroke-dashoffset="segments[i]?.offset ?? 0"
        >
          <title>{{ d.label }}: {{ d.value }}</title>
        </circle>
      </g>
      <text x="60" y="58" text-anchor="middle" font-size="19" font-weight="700" fill="currentColor">{{ total }}</text>
      <text x="60" y="74" text-anchor="middle" font-size="8.5" fill="currentColor" fill-opacity="0.55">total</text>
    </svg>
    <ul class="min-w-36 space-y-1.5 text-sm">
      <li v-for="d in data" :key="d.label" class="flex items-center gap-2">
        <span class="h-2.5 w-2.5 rounded-full" :style="{ background: d.color }" aria-hidden="true" />
        <span class="capitalize">{{ d.label }}</span>
        <span class="ml-auto pl-4 font-semibold">{{ d.value }}</span>
      </li>
    </ul>
  </div>
</template>
