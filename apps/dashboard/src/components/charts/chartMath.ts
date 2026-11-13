/** Pure chart math — kept separate from the components so it is unit-testable. */

/** Each value as a fraction of the largest value (for bar lengths). */
export function fractionsOfMax(values: number[]): number[] {
  const max = Math.max(0, ...values)
  return values.map((v) => (max > 0 ? v / max : 0))
}

/** Each value as a share of the total (for donut segments). */
export function shares(values: number[]): number[] {
  const total = values.reduce((a, b) => a + b, 0)
  return values.map((v) => (total > 0 ? v / total : 0))
}

export interface DonutSegment {
  /** stroke-dasharray value: "<filled> <rest>" in circumference units. */
  dash: string
  /** stroke-dashoffset placing the segment after its predecessors. */
  offset: number
}

/** Stroke segments for a donut drawn with circles of the given circumference. */
export function donutSegments(values: number[], circumference: number): DonutSegment[] {
  const parts = shares(values)
  let acc = 0
  return parts.map((fraction) => {
    const filled = fraction * circumference
    const segment = { dash: `${filled} ${circumference - filled}`, offset: -acc * circumference }
    acc += fraction
    return segment
  })
}

export interface DayBucket { key: string; label: string; count: number }

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/**
 * Count ISO timestamps into per-day buckets for the last `days` days
 * (UTC days, matching the API's UTC timestamps), oldest first.
 */
export function bucketByDay(timestamps: string[], days: number, now: Date = new Date()): DayBucket[] {
  const buckets: DayBucket[] = []
  const byKey = new Map<string, DayBucket>()
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() - i))
    const key = d.toISOString().slice(0, 10)
    const bucket = { key, label: `${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}`, count: 0 }
    buckets.push(bucket)
    byKey.set(key, bucket)
  }
  for (const ts of timestamps) {
    const bucket = byKey.get(ts.slice(0, 10))
    if (bucket) bucket.count += 1
  }
  return buckets
}

/** Base-unit integer strings can exceed float precision; Number() is
 *  used only for chart proportions and counts, never for display. */
export function proportionNumber(value: string): number {
  const n = Number(value)
  return Number.isFinite(n) ? n : 0
}
