<script setup lang="ts">
import { computed } from 'vue'
import { fractionsOfMax } from './chartMath'

export interface BarDatum { label: string; value: number }

const props = withDefaults(
  defineProps<{ data: BarDatum[]; color?: string; ariaLabel: string }>(),
  { color: '#2563eb' },
)

const W = 560
const H = 190
const TOP = 22
const BOTTOM = 24
const fractions = computed(() => fractionsOfMax(props.data.map((d) => d.value)))
const slot = computed(() => W / Math.max(1, props.data.length))
const barWidth = computed(() => Math.min(30, slot.value * 0.52))
function x(i: number): number { return i * slot.value + (slot.value - barWidth.value) / 2 }
function frac(i: number): number { return fractions.value[i] ?? 0 }
function barHeight(i: number): number { return frac(i) * (H - TOP - BOTTOM) }
</script>
<template>
  <svg :viewBox="`0 0 ${W} ${H}`" class="w-full" role="img" :aria-label="ariaLabel">
    <line :x1="0" :y1="H - BOTTOM" :x2="W" :y2="H - BOTTOM" stroke="currentColor" stroke-opacity="0.15" />
    <g v-for="(d, i) in data" :key="d.label">
      <title>{{ d.label }}: {{ d.value }}</title>
      <text
        :x="x(i) + barWidth / 2" :y="H - BOTTOM - barHeight(i) - 6"
        text-anchor="middle" font-size="11" font-weight="600" fill="currentColor"
      >{{ d.value }}</text>
      <rect
        :x="x(i)" :y="H - BOTTOM - barHeight(i)" :width="barWidth" :height="Math.max(2, barHeight(i))"
        rx="4" :fill="color" :fill-opacity="frac(i) > 0 ? 1 : 0.18"
      />
      <text
        :x="x(i) + barWidth / 2" :y="H - 8"
        text-anchor="middle" font-size="9.5" fill="currentColor" fill-opacity="0.55"
      >{{ d.label }}</text>
    </g>
  </svg>
</template>
