// #240 Verify quote freshness and chart states: the browser side. Tests only: nothing here changes a screen, a price or a chart.
// The server side is backend/tests/test_verify_240_quote_states.py; the quote and snapshot rules were verified in #246 (cited).
// Findings note: docs/verification/240-quotes-charts.md.
//
// The gaps found here have been fixed (#240 chart states); each is now an ordinary passing test marked FIXED.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { renderToString } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import type { BrainDecision, MarketSession } from '../api/types'
import PricesBadge from './PricesBadge'
import { pricesAge } from './pricesAge'
import { StockHeader } from './stockParts'
import { fmtPct, fmtPrice } from './trackerRules'
import { Candles } from './ui'
import { barsFrom } from './live-stock'

const src = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const read = (rel: string) => fs.readFileSync(path.join(src, rel), 'utf8').replace(/\r\n/g, '\n')

// What GET /market/session sends the badge (server tests a1-a4 produce these exact shapes). Nov 2026: Tue 24 Nov is a holiday.
const session = (over: Partial<MarketSession>): MarketSession => ({
  state: 'closed',
  plain: 'Market closed · opens Mon 30 Nov, 9:15 am',
  trading_day: true,
  opens_at: null,
  closes_at: null,
  next_open: '2026-11-30T09:15:00+05:30',
  next_close: '2026-11-30T15:30:00+05:30',
  last_closed_trading_day: '2026-11-27',
  today: '2026-11-30',
  recent_closed_trading_days: ['2026-11-27', '2026-11-26', '2026-11-25', '2026-11-23', '2026-11-20'],
  latest_candle_date: '2026-11-27',
  calendar_warning: null,
  ...over,
})

const ageOf = (m: MarketSession) =>
  pricesAge({
    latestCandleDate: m.latest_candle_date ?? null,
    today: m.today ?? '',
    recentClosedTradingDays: m.recent_closed_trading_days ?? [m.last_closed_trading_day],
  })

function badge(m: MarketSession | undefined): string {
  const qc = new QueryClient()
  if (m) qc.setQueryData(['marketSession'], m)
  return renderToString(
    <QueryClientProvider client={qc}>
      <PricesBadge />
    </QueryClientProvider>,
  )
}

// ================================================================ (a) the "Prices from ..." label on every TradeMind page

describe('the prices label (pricesAge.test.ts holds the full day-counting matrix; these use the server shapes)', () => {
  it('Monday morning on Friday’s close is up to date, and a holiday is not counted as a missed day', () => {
    expect(ageOf(session({}))).toMatchObject({ tone: 'fresh', days: 0, label: 'Prices from the Fri 27 Nov close' })
    const afterHoliday = session({
      today: '2026-11-25',
      last_closed_trading_day: '2026-11-23',
      recent_closed_trading_days: ['2026-11-23', '2026-11-20', '2026-11-19'],
      latest_candle_date: '2026-11-23',
    })
    expect(ageOf(afterHoliday)).toMatchObject({ tone: 'fresh', days: 0 }) // Tuesday 24 Nov was a holiday
  })

  it('after the close the previous close is one normal day old; a missing day or more turns it amber', () => {
    const evening = session({
      today: '2026-11-26',
      last_closed_trading_day: '2026-11-26',
      recent_closed_trading_days: ['2026-11-26', '2026-11-25', '2026-11-23'],
      latest_candle_date: '2026-11-25',
    })
    expect(ageOf(evening)).toMatchObject({ tone: 'fresh', days: 1, label: 'Prices are 1 day old' })
    const twelveDays = session({ latest_candle_date: '2026-11-13' })
    const old = ageOf(twelveDays)
    expect(old.tone).toBe('stale')
    expect(old.detail).toMatch(/Out of date/)
  })

  it('no stored price at all says so and is never "fresh"', () => {
    const none = ageOf(session({ latest_candle_date: null }))
    expect(none).toMatchObject({ tone: 'stale', days: null, label: 'No prices yet' })
    expect(none.detail).toContain('nothing on this page is based on real prices')
  })

  it('the badge shows the label and warns in amber when stale; it shows nothing while the session is unknown', () => {
    expect(badge(undefined)).toBe('') // no data yet: no label at all, never an invented one
    const fresh = badge(session({}))
    expect(fresh).toContain('Prices from the Fri 27 Nov close')
    expect(fresh).not.toContain('tm-asof-stale')
    const stale = badge(session({ latest_candle_date: '2026-11-13' }))
    expect(stale).toContain('tm-asof-stale')
    expect(stale).toMatch(/aria-label="[^"]*Out of date/)
  })

  it('every TradeMind shell mounts the badge (so every page carries an age label)', () => {
    expect(read('trademind/TradeMindApp.tsx')).toContain('<PricesBadge />')
    expect(read('trademind/NewLookShell.tsx')).toContain('<PricesBadge />')
  })
})

// ======================================================================== (b) the stock page price: stale, missing, loading

const decision = { symbol: 'V240', kind: 'idea', reasons: [] } as unknown as BrainDecision

function header(over: { last?: number; prev?: number; change: number | null; snapshot?: undefined; lastDate?: string }) {
  return renderToString(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <StockHeader decision={decision} last={over.last} prev={over.prev} change={over.change} snapshot={over.snapshot} lastDate={over.lastDate} withBuy={false} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('the stock header price (priceSnapshot.test.tsx covers live, delayed, stale, mismatch and holiday states)', () => {
  it('while the price is loading, no price number is drawn at all', () => {
    const html = header({ change: null })
    expect(html).not.toContain('₹')
    expect(html).not.toContain('NaN')
  })

  it('FIXED b1: with no snapshot the stored close is shown with its own date', () => {
    const html = header({ last: 123.57, prev: 128.15, change: -4.58, lastDate: '2026-11-30' })
    expect(html).toContain('Closing price on 30 Nov 2026')
  })

  it('FIXED b2: a bare stored close with no change to show is still labelled as a close', () => {
    // Only one candle on file: no change to show, the close still says it is a close and which day.
    const html = header({ last: 123.57, change: null, lastDate: '2026-11-30' })
    expect(html).toContain('Closing price on 30 Nov 2026')
    expect(header({ last: 123.57, change: null })).toContain('Last closing price') // no date on file: still a close
  })
})

// ================================================================================================ (c) charts

const bar = (i: number, price = 100 + i) => ({ t: `${i + 1} Dec`, o: price, h: price + 2, l: price - 2, c: price + 1, vol: 1000 + i })

describe('the candle chart draws only the candles it is given', () => {
  it('one body per candle, labelled with the candle’s own date, nothing interpolated', () => {
    const html = renderToString(<Candles bars={[bar(0), bar(1), bar(4)]} height={300} />) // 2 and 3 Dec missing
    expect((html.match(/<line x1="[^"]*" x2="[^"]*" y1="[^"]*" y2="[^"]*" stroke="#(2ee68a|ff4d6a)" stroke-width="1"/g) ?? []).length).toBe(3)
    expect(html).toContain('1 Dec')
    expect(html).toContain('2 Dec')
    expect(html).not.toContain('NaN')
  })

  it('a single candle with a flat price draws no invalid numbers', () => {
    const html = renderToString(<Candles bars={[{ t: '1 Dec', o: 100, h: 100, l: 100, c: 100, vol: 500 }]} height={300} />)
    expect(html).not.toMatch(/NaN|Infinity/)
  })

  it('FIXED c1b: a candle with zero volume is drawn as a valid candle with no volume bar', () => {
    const html = renderToString(<Candles bars={[{ t: '1 Dec', o: 100, h: 101, l: 99, c: 100, vol: 0 }]} height={300} />)
    expect(html).not.toMatch(/NaN|Infinity/)
    expect(html).toContain('stroke-width="1"') // the candle itself is drawn
    expect(html).not.toContain('opacity="0.35"') // no volume bar
  })

  it('a quiet day beside a busy day keeps the busy day volume bar and skips the quiet one', () => {
    const html = renderToString(<Candles bars={[{ t: '1 Dec', o: 100, h: 101, l: 99, c: 100, vol: 0 }, bar(1)]} height={300} />)
    expect(html).not.toMatch(/NaN|Infinity/)
    expect((html.match(/opacity="0.35"/g) ?? []).length).toBe(1)
  })

  it('FIXED c1: the chart given no candles shows a plain empty state and draws nothing invalid', () => {
    const html = renderToString(<Candles bars={[]} height={300} />)
    expect(html).not.toMatch(/NaN|Infinity/)
    expect(html).toContain('No price history to draw yet.')
    expect(html).not.toContain('<svg')
  })

  it('the two callers show a loading or an empty state instead of the chart', () => {
    const detail = read('trademind/pages/StockDetail.tsx')
    expect(detail).toContain('candlesQ.data === undefined ? (') // loading: a notice, not the chart
    expect(detail.indexOf('candlesQ.data === undefined ? (')).toBeLessThan(detail.indexOf('<Candles bars'))
    expect(detail).toContain('No stored price history for this stock yet.') // empty
    expect(read('trademind/pages/StockAnalysis.tsx')).toContain('{bars.length > 0 && (')
  })

  it('missing numbers print a dash, never zero', () => {
    expect(fmtPrice(null)).toBe('—')
    expect(fmtPrice(undefined)).toBe('—')
    expect(fmtPct(null)).toBe('—')
    expect(fmtPct(undefined)).toBe('—')
    expect(fmtPct(0)).toBe('0.0%') // a real zero is still a zero
  })
})

// ================================================================================= (d) dates on charts are India dates

describe('chart dates are India trading days', () => {
  it('FIXED (#470) c2: candle labels are right whatever the browser time zone is', () => {
    // live-stock.ts:12-14 reads the date with local getDate(): it says so ("Assumes the viewer is in IST").
    const previous = process.env.TZ
    process.env.TZ = 'UTC'
    try {
      const bars = barsFrom([{ ts: '2026-11-29T18:30:00Z', open: 1, high: 1, low: 1, close: 1, volume: 1 }])
      expect(bars[0]!.t).toBe('30 Nov') // the bar of Monday 30 Nov (stamped 00:00 IST)
    } finally {
      if (previous === undefined) delete process.env.TZ
      else process.env.TZ = previous
    }
  })

  it('FIXED (#470) c3: no chart label is cut from the first ten characters of a candle timestamp', () => {
    // The API sends 2026-11-29T18:30:00Z for the 30 Nov bar (backend test b1); slice(5, 10) gives "11-29", a day early.
    for (const file of ['trademind/today/SwingPicks.tsx', 'trademind/pages/Opportunities.tsx']) {
      expect(read(file), file).not.toMatch(/c\.ts\.slice\(5, 10\)/)
    }
  })

  it('the day counting in the label never reads a timestamp: it works on India dates the server already converted', () => {
    const source = read('trademind/pricesAge.ts')
    expect(source).not.toMatch(/new Date\(.*latestCandle/) // the candle date is used as a plain YYYY-MM-DD string
    expect(read('trademind/PricesBadge.tsx')).toContain('latest_candle_date')
  })
})

describe('the line and area charts are drawn only when there is data to draw (read from the source: recharts cannot render without a browser)', () => {
  it('each caller waits for the data, and says so plainly when there is too little', () => {
    const swing = read('trademind/today/SwingPicks.tsx')
    expect(swing).toContain('{spark.length > 1 && <GlowArea')
    expect(swing).toContain('{points.length > 1 && <GlowArea')
    expect(read('trademind/pages/Opportunities.tsx')).toContain('{points.length > 0 && <GlowArea')
    const portfolio = read('trademind/pages/PortfolioNew.tsx')
    expect(portfolio).toContain('equity.data === undefined ? (') // loading or refused: a notice, not a chart
    expect(portfolio).toContain('points.length >= 2 ? (')
    expect(portfolio).toContain('Not enough days of history yet to draw a chart.')
    expect(read('trademind/pages/Risk.tsx')).toContain('points.length > 1 ? (')
    expect(read('trademind/pages/GrowwTracker.tsx')).toContain('Not enough days yet. The chart appears after the first close.')
  })
})
