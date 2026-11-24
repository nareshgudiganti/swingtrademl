// #470: a daily candle is stamped at India midnight (18:30 UTC the day before), so its trading day is the IST date.
// Chart labels were cut from the UTC string (a day early) or read in the browser's own time zone (wrong outside India).
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

import { barsFrom } from './live-stock'
import { formatIstDate, istDay, istMonthDay } from './istDay'

const src = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const read = (rel: string) => fs.readFileSync(path.join(src, rel), 'utf8').replace(/\r\n/g, '\n')

// The bar for Monday 30 Nov 2026, as the API serves it.
const MON = '2026-11-29T18:30:00Z'

function inZone<T>(tz: string, fn: () => T): T {
  const previous = process.env.TZ
  process.env.TZ = tz
  try {
    return fn()
  } finally {
    if (previous === undefined) delete process.env.TZ
    else process.env.TZ = previous
  }
}

describe('the India trading day of a candle', () => {
  it('is the IST date, not the UTC date', () => {
    expect(istDay(MON)).toBe('2026-11-30')
    expect(istDay('2026-11-30T18:30:00Z')).toBe('2026-12-01')
    expect(istDay('2026-11-30T18:29:59Z')).toBe('2026-11-30') // just before India midnight
    expect(istMonthDay(MON)).toBe('11-30')
  })

  it('is plain arithmetic on the instant: the same answer whatever time zone the browser is set to', () => {
    for (const tz of ['UTC', 'Asia/Kolkata', 'America/Los_Angeles', 'Pacific/Auckland']) {
      expect(inZone(tz, () => istDay(MON)), tz).toBe('2026-11-30')
    }
  })

  it('reads a space-separated stamp with no zone as UTC, the same as the T form', () => {
    expect(istDay('2026-11-29 18:30:00')).toBe('2026-11-30')
    expect(istDay('2026-11-29 18:30:00.250')).toBe('2026-11-30')
    expect(istDay('2026-11-29 18:30:00+00:00')).toBe('2026-11-30')
  })

  it('also reads the API forms with an offset or fractional seconds', () => {
    expect(istDay('2026-11-29T18:30:00.000Z')).toBe('2026-11-30')
    expect(istDay('2026-11-30T00:00:00+05:30')).toBe('2026-11-30')
  })
})

describe('the stock page candle labels', () => {
  it('say 30 Nov for the 30 Nov bar in every browser zone', () => {
    for (const tz of ['UTC', 'Asia/Kolkata', 'America/Los_Angeles']) {
      const label = inZone(tz, () => barsFrom([{ ts: MON, open: 1, high: 1, low: 1, close: 1, volume: 1 }])[0]!.t)
      expect(label, tz).toBe('30 Nov')
    }
  })
})

describe('the Swing Picks and Opportunities chart labels', () => {
  it('are taken from the India date, never cut from the first ten characters of the UTC timestamp', () => {
    for (const file of ['trademind/today/SwingPicks.tsx', 'trademind/pages/Opportunities.tsx']) {
      const text = read(file)
      expect(text, file).not.toMatch(/\.ts\.slice\(\s*5\s*,\s*10\s*\)/)
      expect(text, file).toContain('istMonthDay(c.ts)')
    }
  })
})

describe('the classic chart and the coverage table', () => {
  it('print the India day as dd Mon yyyy in every browser zone', () => {
    for (const tz of ['UTC', 'Asia/Kolkata', 'America/Los_Angeles', 'Pacific/Auckland']) {
      expect(inZone(tz, () => formatIstDate(MON)), tz).toBe('30 Nov 2026')
      expect(inZone(tz, () => formatIstDate('2026-11-30')), tz).toBe('30 Nov 2026') // a bare India date stays put
    }
  })

  it('PricePerformance and the Setup coverage table use it, not the browser-zone formatDate', () => {
    const chart = read('components/PricePerformance.tsx')
    expect(chart).toContain('formatIstDate(candle.ts)')
    expect(chart).toContain('formatIstDate(value.startDate)')
    expect(chart).not.toMatch(/formatDate\(/)
    const setup = read('trademind/pages/Setup.tsx')
    expect(setup).toContain('formatIstDate(c.from)')
    expect(setup).toContain('formatIstDate(c.to)')
  })
})
