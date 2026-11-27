// #486 (from the #240 and #238 verifications): honest labels on the stock page and the positions, no NaN on the chart,
// (the one-decision-word part landed in #499). These failed on `5de3b9c` and pass with the fix.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToString } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import type { BrainDecision, DetailedPosition } from '../api/types'
import { levelFor } from './pages/positionLevels'
import { levelOf, returnText } from './pages/PositionParts'
import { StockHeader } from './stockParts'
import { Candles } from './ui'


// ------------------------------------------------------------------------------------------ the candle chart
describe('the candle chart never prints NaN', () => {
  it('draws nothing at all when it is given no candles', () => {
    expect(renderToString(<Candles bars={[]} height={300} />)).not.toMatch(/NaN|Infinity/)
  })

  it('draws no invalid volume bar on a day with zero volume', () => {
    const html = renderToString(<Candles bars={[{ t: '1 Dec', o: 100, h: 101, l: 99, c: 100, vol: 0 }]} height={300} />)
    expect(html).not.toMatch(/NaN|Infinity/)
  })

  it('still draws volume when there is some', () => {
    const html = renderToString(<Candles bars={[{ t: '1 Dec', o: 100, h: 101, l: 99, c: 100, vol: 500 }]} height={300} />)
    expect(html).toContain('opacity="0.35"')
  })
})

// ------------------------------------------------------------------------------------------ the stock page close
const decision = { symbol: 'V486', kind: 'idea', reasons: [] } as unknown as BrainDecision
const header = (props: { last?: number; prev?: number; change: number | null; closeOn?: string }) =>
  renderToString(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <StockHeader decision={decision} withBuy={false} {...props} />
      </MemoryRouter>
    </QueryClientProvider>,
  )

describe('the stock page close carries its date', () => {
  const closeOn = '2026-11-20T18:30:00Z' // the bar of Saturday... stamped for the India day 21 Nov

  it('says which day the stored close is from', () => {
    const html = header({ last: 123.57, prev: 128.15, change: -4.58, closeOn })
    expect(html).toContain('Last close on 21 Nov')
  })

  it('labels a single candle too: the number is never bare', () => {
    const html = header({ last: 123.57, change: null, closeOn })
    expect(html).toContain('123.57')
    expect(html).toContain('Last close on 21 Nov')
  })

  it('still labels it as a close when the date is not known', () => {
    expect(header({ last: 123.57, change: null }).toLowerCase()).toContain('last close')
  })

  it('draws nothing while the price is loading', () => {
    const html = header({ change: null })
    expect(html).not.toContain('₹')
    expect(html).not.toContain('last close')
  })
})

// ------------------------------------------------------------------------------------------ an unpriced position
const position = (over: Partial<DetailedPosition>): DetailedPosition =>
  ({
    id: 1,
    symbol: 'V486',
    entry_price: 100,
    current_price: 100,
    unrealized_pnl_pct: 0,
    suggestion: undefined,
    ...over,
  }) as unknown as DetailedPosition

describe('a position nobody has priced is not shown as flat', () => {
  it('says "Price unavailable" instead of 0.0%, with the last price time when known (#281 D2)', () => {
    expect(returnText(position({ has_price: false, price_status: 'none', unrealized_pnl_pct: null }))).toBe('Price unavailable')
    expect(
      returnText(position({ has_price: false, price_status: 'none', price_as_of: '2026-11-25T10:00:00Z' })),
    ).toBe('Price unavailable · last price 25 Nov 15:30 IST')
  })

  it('has a level that says so, and is not "Hold: nothing to do"', () => {
    const level = levelOf(position({ has_price: false, price_status: 'none' }))
    expect(level.state).toBe('no_price')
    expect(level.title).toBe('Price unavailable')
    expect(level.act).toBe(true) // flagged under "Act today" (#486 review)
    expect(level.advice).not.toMatch(/Keep holding/)
  })

  it('leaves a priced position exactly as it was', () => {
    const priced = position({ has_price: true, price_status: 'ok', current_price: 103, unrealized_pnl_pct: 0.03 })
    expect(returnText(priced)).toBe('+3.0%')
    expect(levelOf(priced)).toEqual(levelFor(3, false))
  })

  it('treats an answer from an older server (no flag) as priced', () => {
    expect(returnText(position({ unrealized_pnl_pct: -0.021 }))).toBe('−2.1%')
  })
})

describe('a position with no price yet is flagged for action, never listed as fine', () => {
  const unpriced = { id: 1, symbol: 'NP486', has_price: false, unrealized_pnl_pct: 0, unrealized_pnl: 0, suggestion: 'HOLD' } as unknown as DetailedPosition

  it('is an "act today" level with the check-it-by-hand advice', () => {
    expect(levelOf(unpriced)).toMatchObject({ state: 'no_price', act: true })
    expect(levelOf(unpriced).advice).toContain('Check it by hand')
  })
})
