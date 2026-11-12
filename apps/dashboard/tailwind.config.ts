import type { Config } from 'tailwindcss'

/**
 * Design tokens — single source for colour / type in the dashboard.
 * Inspiration (not a copy): soft lavender canvas, floating white shell,
 * dark-pill active nav, white KPI cards, blue chart accents. See DESIGN.md.
 */
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{vue,ts}'],
  theme: {
    extend: {
      colors: {
        brand: {
          50: '#eef6ff', 100: '#d9eaff', 200: '#bcdbff', 300: '#8ec4ff',
          400: '#59a2ff', 500: '#3380fc', 600: '#2563eb', 700: '#1d4ed8',
          800: '#183fb4', 900: '#1a3a8c', 950: '#142454',
        },
        canvas: '#c7c9e8',
        surface: {
          DEFAULT: 'rgb(var(--color-surface) / <alpha-value>)',
          muted: 'rgb(var(--color-surface-muted) / <alpha-value>)',
        },
        ink: {
          DEFAULT: 'rgb(var(--color-ink) / <alpha-value>)',
          muted: 'rgb(var(--color-ink-muted) / <alpha-value>)',
        },
        danger: '#dc2626',
        success: '#15803d',
        warning: '#b45309',
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-system', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
      borderRadius: { card: '1rem', shell: '1.75rem' },
      boxShadow: {
        card: '0 1px 2px rgb(15 23 42 / 0.04), 0 8px 24px -12px rgb(15 23 42 / 0.12)',
        shell: '0 24px 60px -24px rgb(30 27 75 / 0.35)',
        pop: '0 12px 32px -8px rgb(15 23 42 / 0.18)',
      },
    },
  },
  plugins: [],
} satisfies Config
