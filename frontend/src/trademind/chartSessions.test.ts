// #240: missing-day markers appear only for expected trading sessions; weekends and holidays are never marked.
import { describe, expect, it } from 'vitest'

import type { Candle } from '../api/types'
import { barsFrom } from './live-stock'
import { candlePoints, expectedSessionsBetween } from './chartSessions'

// Nov 2026: Sat 21 and Sun 22 are a weekend, Tue 24 is a holiday on the server list, Sat 28 and Sun 29 are a weekend.
const HOLIDAYS = ['2026-11-24']
// A daily candle is stamped India midnight, which is 18:30 UTC the day before.
const candle = (istDate: string, close: number): Candle => {
  const d = new Date(`${istDate}T00:00:00Z`)
  d.setUTCMinutes(d.getUTCMinutes() - 330)
  return { ts: d.toISOString(), open: close, high: close, low: close, close, volume: 1 } as Candle
}

describe('missing sessions on line and area charts', () => {
  it('an expected trading session with no candle is marked', () => {
    // Thu 19 Nov has a candle, Fri 20 Nov is missing, Mon 23 Nov has a candle.
    const pts = candlePoints([candle('2026-11-19', 100), candle('2026-11-23', 101)], HOLIDAYS)
    expect(pts.map((p) => [p.t, p.v, p.missing === true])).toEqual([
      ['11-19', 100, false],
      ['11-20', null, true],
      ['11-23', 101, false],
    ])
  })

  it('weekends are not marked', () => {
    const pts = candlePoints([candle('2026-11-20', 100), candle('2026-11-23', 101)], HOLIDAYS) // Fri then Mon
    expect(pts.some((p) => p.missing)).toBe(false)
  })

  it('a listed holiday is not marked', () => {
    const pts = candlePoints([candle('2026-11-23', 100), candle('2026-11-25', 101)], HOLIDAYS) // Tue 24 is a holiday
    expect(pts.some((p) => p.missing)).toBe(false)
    // The same gap with no holiday listed is an expected session: the list, not a hardcoded date, decides.
    expect(candlePoints([candle('2026-11-23', 100), candle('2026-11-25', 101)], []).filter((p) => p.missing)).toHaveLength(1)
  })

  it('with no holiday list loaded nothing is marked (nothing is guessed), and the prices still draw', () => {
    const pts = candlePoints([candle('2026-11-19', 100), candle('2026-11-23', 101)], null)
    expect(pts).toHaveLength(2)
    expect(pts.every((p) => p.v != null)).toBe(true)
  })

  it('labels bars with the India trading day (a 30 Nov bar is never 29 Nov)', () => {
    const pts = candlePoints([candle('2026-11-27', 1), candle('2026-11-30', 2)], HOLIDAYS)
    expect(pts.map((p) => p.t)).toEqual(['11-27', '11-30'])
  })

  it('expectedSessionsBetween skips weekends and holidays and excludes both ends', () => {
    expect(expectedSessionsBetween('2026-11-20', '2026-11-27', HOLIDAYS)).toEqual(['2026-11-23', '2026-11-25', '2026-11-26'])
  })
})

describe('the candle chart labels are India dates in any browser zone', () => {
  it.each(['UTC', 'America/Los_Angeles', 'Asia/Kolkata', 'Pacific/Kiritimati'])('zone %s', (tz) => {
    const previous = process.env.TZ
    process.env.TZ = tz
    try {
      expect(barsFrom([candle('2026-11-30', 1)])[0]!.t).toBe('30 Nov')
    } finally {
      if (previous === undefined) delete process.env.TZ
      else process.env.TZ = previous
    }
  })
})
