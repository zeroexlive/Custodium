<script setup lang="ts">
/**
 * Inline SVG icon set (24x24, stroke-based, drawn for Custodium).
 * One component, `name` prop — no icon dependency, no external assets.
 */
const props = withDefaults(defineProps<{ name: string; size?: number }>(), { size: 20 })

const PATHS: Record<string, string> = {
  grid: '<rect x="3.5" y="3.5" width="7" height="7" rx="1.8"/><rect x="13.5" y="3.5" width="7" height="7" rx="1.8"/><rect x="3.5" y="13.5" width="7" height="7" rx="1.8"/><rect x="13.5" y="13.5" width="7" height="7" rx="1.8"/>',
  building: '<rect x="5" y="3.5" width="14" height="17" rx="1.5"/><path d="M9 8h2M13 8h2M9 12h2M13 12h2M9 16h2M13 16h2"/>',
  folder: '<path d="M3.5 6.5A1.5 1.5 0 0 1 5 5h4l2 2.5h8A1.5 1.5 0 0 1 20.5 9v8A1.5 1.5 0 0 1 19 18.5H5A1.5 1.5 0 0 1 3.5 17Z"/>',
  key: '<circle cx="8" cy="14.5" r="4.5"/><path d="M11.2 11.3 20 2.5M17 5.5l3 3M14 8.5l2.5 2.5"/>',
  shield: '<path d="M12 3 5 5.8v5.4c0 4.6 3 7.7 7 9.3 4-1.6 7-4.7 7-9.3V5.8Z"/><path d="m9.2 11.6 2 2 3.6-3.8"/>',
  wallet: '<rect x="3" y="6" width="18" height="13" rx="2.5"/><path d="M3 10.5h18M16.5 15h.8"/>',
  pin: '<path d="M12 21s-6.5-5.6-6.5-10.4A6.5 6.5 0 0 1 12 4a6.5 6.5 0 0 1 6.5 6.6C18.5 15.4 12 21 12 21Z"/><circle cx="12" cy="10.5" r="2.3"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.3-4.3"/>',
  coins: '<circle cx="9" cy="9" r="5.5"/><path d="M14.5 5.6a5.5 5.5 0 1 1-4 9.9"/>',
  refresh: '<path d="M20 12a8 8 0 1 1-2.3-5.6M20 3.5V8h-4.5"/>',
  signal: '<circle cx="12" cy="12" r="1.6"/><path d="M8.8 15.2a4.5 4.5 0 0 1 0-6.4M15.2 8.8a4.5 4.5 0 0 1 0 6.4M6 18a8.5 8.5 0 0 1 0-12M18 6a8.5 8.5 0 0 1 0 12"/>',
  sliders: '<path d="M4 7.5h9M17.5 7.5H20M4 16.5h3.5M12 16.5h8"/><circle cx="15" cy="7.5" r="2.2"/><circle cx="9.5" cy="16.5" r="2.2"/>',
  book: '<path d="M5 4.5A1.5 1.5 0 0 1 6.5 3H19v15H6.5A1.5 1.5 0 0 0 5 19.5Z"/><path d="M5 19.5V4.5M19 18H8"/>',
  fuel: '<path d="M5 20.5v-15A1.5 1.5 0 0 1 6.5 4h5A1.5 1.5 0 0 1 13 5.5v15M3.5 20.5h11"/><path d="M13 9.5 16.5 6a2.4 2.4 0 0 1 3.4 2.1v6.1a2 2 0 0 0 4 .3"/><rect x="7.5" y="7" width="3" height="3" rx="0.6"/>',
  clipboard: '<rect x="5.5" y="5" width="13" height="16" rx="1.8"/><path d="M9 5a3 3 0 0 1 6 0M9 12h6M9 16h4"/>',
  ban: '<circle cx="12" cy="12" r="8.5"/><path d="M6 6l12 12"/>',
  'arrow-up-circle': '<circle cx="12" cy="12" r="8.5"/><path d="M12 16V8M8.5 11.5 12 8l3.5 3.5"/>',
  webhook: '<path d="M9.5 5.5a3 3 0 1 1 3 3"/><path d="M12 8.5c2.8 1.6 4.5 3.8 4.5 6.5a4.5 4.5 0 1 1-9 0c0-1 .3-2 .8-2.9"/><circle cx="18" cy="5.5" r="2"/>',
  users: '<circle cx="9" cy="8.5" r="3.5"/><path d="M3.5 19.5c.6-3 2.8-4.5 5.5-4.5s4.9 1.5 5.5 4.5M16 5.4a3.5 3.5 0 0 1 0 6.2M17.8 15.3c1.6.7 2.5 2 2.8 4.2"/>',
  card: '<rect x="3" y="5.5" width="18" height="13" rx="2.2"/><path d="M3 10h18M6.5 15h4"/>',
  file: '<path d="M6 3.5h8L19 8.5v12H6Z"/><path d="M13.5 3.5v5.5H19M9 13h6M9 16.5h6"/>',
  clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2.8v2.4M12 18.8v2.4M2.8 12h2.4M18.8 12h2.4M5 5l1.7 1.7M17.3 17.3 19 19M19 5l-1.7 1.7M6.7 17.3 5 19"/>',
  moon: '<path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5Z"/>',
  logout: '<path d="M14 4h4a1.5 1.5 0 0 1 1.5 1.5v13A1.5 1.5 0 0 1 18 20h-4M10 16.5 5.5 12 10 7.5M5.5 12H15"/>',
  chart: '<path d="M4 4v16h16"/><path d="M8.5 16v-5M12.5 16V8M16.5 16v-8"/>',
}
</script>
<template>
  <svg
    :width="props.size" :height="props.size" viewBox="0 0 24 24" fill="none"
    stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"
    aria-hidden="true" focusable="false" v-html="PATHS[props.name] ?? ''"
  />
</template>
