// #486 (from the #240 and #238 verifications): honest labels on the stock page and the positions, no NaN on the chart,
// and one decision word for an idea. These failed on `5de3b9c` and pass with the fix.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { renderToString } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import type { BrainDecision, DetailedPosition } from '../api/types'
import { wordFor } from './live'
import { levelFor } from './pages/positionLevels'
import { levelOf, returnText } from './pages/PositionParts'
import { StockHeader } from './stockParts'
import { Candles } from './ui'

const src = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const read = (rel: string) => fs.readFileSync(path.join(src, rel), 'utf8').replace(/\r\n/g, '\n')

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
  it('says "No price yet" instead of 0.0%', () => {
    expect(returnText(position({ has_price: false, price_status: 'none' }))).toBe('No price yet')
  })

  it('has a level that says so, and is not "Hold: nothing to do"', () => {
    const level = levelOf(position({ has_price: false, price_status: 'none' }))
    expect(level.state).toBe('no_price')
    expect(level.title).toBe('No price yet')
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

// ------------------------------------------------------------------------------------------ one word for an idea
const roomHeldBack = {
  word: 'WATCH',
  stock_verdict: 'TRADE',
  stock_verdict_restored: true,
  overruled_word: null,
} as unknown as BrainDecision

describe('an idea held back only by the account’s room has one word', () => {
  it('the owner sees the stored word, as Today does; everyone else sees the stock-level verdict', () => {
    expect(wordFor(roomHeldBack, true)).toBe('WATCH')
    expect(wordFor(roomHeldBack, false)).toBe('TRADE')
  })

  it('an owner’s overrule wins for everyone', () => {
    const overruled = { ...roomHeldBack, overruled_word: 'AVOID' } as unknown as BrainDecision
    expect(wordFor(overruled, true)).toBe('AVOID')
    expect(wordFor(overruled, false)).toBe('AVOID')
  })

  it('an idea with no room problem reads the same for everyone', () => {
    const plain = { word: 'TRADE', stock_verdict: null, stock_verdict_restored: false } as unknown as BrainDecision
    expect(wordFor(plain, true)).toBe('TRADE')
    expect(wordFor(plain, false)).toBe('TRADE')
  })

  it('Stock Detail, AI Analysis, AI Decision and the ideas table all ask wordFor, never shownWord directly', () => {
    for (const file of [
      'trademind/pages/StockDetail.tsx',
      'trademind/pages/StockAnalysis.tsx',
      'trademind/pages/AIDecision.tsx',
      'trademind/IdeasTable.tsx',
    ]) {
      const text = read(file)
      expect(text, file).toMatch(/useWordFor|wordFor\(/)
      expect(text, file).not.toMatch(/\bshownWord\(/)
    }
  })
})

// ------------------------------------------------------------------------------------------ Discover: one word per row
import { discoverCounts, filterIdeas, whereItStopped } from './discoverRules'

describe('Discover reads the same word as the row, for the owner and for everyone else', () => {
  // Held back only by the practice account's room: stored WATCH, stock-level verdict TRADE.
  const room = {
    id: 1, run_id: 'r', symbol: 'ROOM486', kind: 'idea', word: 'WATCH', reasons: ['risk check said no: no room in the account'],
    stock_verdict: 'TRADE', stock_verdict_restored: true, overruled_word: null, confidence: 0.8,
  } as unknown as BrainDecision
  const ideas = [room]

  it('for the owner the row, the filter, the count and "Where it stopped" all say WATCH', () => {
    expect(wordFor(room, true)).toBe('WATCH')
    expect(discoverCounts(ideas, true)).toMatchObject({ WATCH: 1, TRADE: 0 })
    expect(filterIdeas(ideas, { filter: 'WATCH', owner: true })).toHaveLength(1)
    expect(filterIdeas(ideas, { filter: 'TRADE', owner: true })).toHaveLength(0)
    expect(whereItStopped(room, true).label).not.toBe('Passed')
  })

  it('for everyone else they all say TRADE, as before', () => {
    expect(wordFor(room, false)).toBe('TRADE')
    expect(discoverCounts(ideas)).toMatchObject({ TRADE: 1, WATCH: 0 })
    expect(filterIdeas(ideas, { filter: 'TRADE' })).toHaveLength(1)
    expect(whereItStopped(room).label).toBe('Passed')
  })
})

// ------------------------------------------------------------------------------------------ no price: flagged for action
describe('a position with no price yet is flagged for action, never listed as fine', () => {
  const unpriced = { id: 1, symbol: 'NP486', has_price: false, unrealized_pnl_pct: 0, unrealized_pnl: 0, suggestion: 'HOLD' } as unknown as DetailedPosition

  it('is an "act today" level with the check-it-by-hand advice', () => {
    expect(levelOf(unpriced)).toMatchObject({ state: 'no_price', act: true })
    expect(levelOf(unpriced).advice).toContain('Check it by hand')
  })
})
