import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import {
  bucketByDay, donutSegments, fractionsOfMax, proportionNumber, shares,
} from '@/components/charts/chartMath'
import Icon from '@/components/ui/Icon.vue'

describe('chart math', () => {
  it('fractionsOfMax scales to the largest value and survives all-zero input', () => {
    expect(fractionsOfMax([0, 5, 10])).toEqual([0, 0.5, 1])
    expect(fractionsOfMax([0, 0])).toEqual([0, 0])
    expect(fractionsOfMax([])).toEqual([])
  })

  it('shares sum to 1 and survive an all-zero total', () => {
    const parts = shares([1, 1, 2])
    expect(parts).toEqual([0.25, 0.25, 0.5])
    expect(parts.reduce((a, b) => a + b, 0)).toBeCloseTo(1)
    expect(shares([0, 0])).toEqual([0, 0])
  })

  it('donutSegments place each segment after the previous ones', () => {
    const C = 100
    const segments = donutSegments([1, 3], C)
    expect(segments[0]).toEqual({ dash: '25 75', offset: -0 })
    expect(segments[1]).toEqual({ dash: '75 25', offset: -25 })
  })

  it('bucketByDay counts timestamps into the trailing UTC days, oldest first', () => {
    const now = new Date('2026-11-14T12:00:00Z')
    const buckets = bucketByDay(
      ['2026-11-14T01:00:00Z', '2026-11-14T23:00:00Z', '2026-11-12T10:00:00Z', '2026-10-01T10:00:00Z'],
      3, now,
    )
    expect(buckets.map((b) => b.key)).toEqual(['2026-11-12', '2026-11-13', '2026-11-14'])
    expect(buckets.map((b) => b.count)).toEqual([1, 0, 2])
    expect(buckets[0]?.label).toBe('Nov 12')
  })

  it('proportionNumber parses base-unit strings and rejects junk', () => {
    expect(proportionNumber('1500000')).toBe(1500000)
    expect(proportionNumber('not-a-number')).toBe(0)
  })
})

describe('Icon', () => {
  it('renders SVG content for a known icon and nothing for an unknown one', () => {
    const known = mount(Icon, { props: { name: 'shield' } })
    expect(known.find('svg').exists()).toBe(true)
    expect(known.find('svg').html()).toContain('<path')
    const unknown = mount(Icon, { props: { name: 'does-not-exist' } })
    expect(unknown.find('svg').html()).not.toContain('<path')
  })
})
