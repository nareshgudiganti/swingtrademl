// Stock Compare: the plain-words rules and the screen. Display only: price changes from stored closes, a dash
// where we do not have that far back, and no advice words.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToString } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import type { CompareStock, CompareView } from '../api/types'
import { MAX_COMPARE, fmtPct, leaderLine, noNumbersText, parseSelection, toneOf } from './compareRules'
import Compare from './pages/Compare'

const PERIODS = ['1W', '1M', '3M', '6M', '1Y', '2Y', '3Y', '5Y']
const stock = (symbol: string, returns: Record<string, number | null>, over: Partial<CompareStock> = {}): CompareStock => ({
  symbol,
  name: `${symbol} Ltd`,
  state: 'ok',
  as_of: '2026-11-02',
  last_close: 100,
  returns: { ...Object.fromEntries(PERIODS.map((p) => [p, null])), ...returns },
  ...over,
})

describe('compare rules', () => {
  it('reads the selection: upper case, no repeats, at most three', () => {
    expect(parseSelection('suzlon, eternal,SUZLON,bse,tcs')).toEqual(['SUZLON', 'ETERNAL', 'BSE'])
    expect(parseSelection(null)).toEqual([])
    expect(MAX_COMPARE).toBe(3)
  })

  it('writes a percent with a sign, or says there is not enough history', () => {
    expect(fmtPct(8.94)).toBe('+8.94%')
    expect(fmtPct(-5.83)).toBe('-5.83%')
    expect(fmtPct(0)).toBe('0.00%')
    expect(fmtPct(null)).toBe('Not enough history')
  })

  it('tones: up, down, flat, none', () => {
    expect([toneOf(1), toneOf(-1), toneOf(0), toneOf(null)]).toEqual(['up', 'down', 'flat', 'none'])
  })

  it('says who did best and worst, never "fell the most" for a rise', () => {
    const line = leaderLine([stock('SUZLON', { '3M': -26.64 }), stock('ETERNAL', { '3M': 14.32 }), stock('BSE', { '3M': -4.2 })], '3M')
    expect(line).toBe('Over the last 3 months, ETERNAL did best (+14.32%) and SUZLON did worst (-26.64%).')
  })

  it('stays silent with fewer than two stocks that have the period', () => {
    expect(leaderLine([stock('A', { '5Y': 10 }), stock('B', {})], '5Y')).toBeNull()
    expect(leaderLine([stock('A', { '1M': 1 }, { state: 'no_history' }), stock('B', { '1M': 2 })], '1M')).toBeNull()
  })

  it('says the same amount when they tie', () => {
    expect(leaderLine([stock('A', { '1M': 2 }), stock('B', { '1M': 2 })], '1M')).toContain('same amount')
  })

  it('explains a stock with no numbers without guessing', () => {
    expect(noNumbersText(stock('ZZZ', {}, { state: 'unknown' }))).toContain('not a stock we know')
    expect(noNumbersText(stock('ITI', {}, { state: 'no_history' }))).toContain('do not hold price history')
  })
})

function render(path: string, data?: CompareView) {
  const client = new QueryClient()
  if (data) client.setQueryData(['compare', 'SUZLON,ETERNAL'], data)
  return renderToString(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Compare />
      </MemoryRouter>
    </QueryClientProvider>,
  ).replace(/<!-- -->/g, '')
}

describe('Compare screen', () => {
  it('asks for stocks when none are picked', () => {
    const html = render('/trademind/compare')
    expect(html).toContain('data-testid="compare-empty"')
    expect(html).toContain('not advice to buy or sell')
  })

  it('shows a tile per period with the change, a dash where history is short, and links to the stock page', () => {
    const html = render('/trademind/compare?s=suzlon,eternal', {
      periods: PERIODS,
      stocks: [stock('SUZLON', { '1W': -5.83, '1M': -9.46, '3M': -26.64 }), stock('ETERNAL', { '1W': 8.94, '1M': 10.15, '3M': 14.32 })],
    })
    expect(html).toContain('data-testid="tile-SUZLON-1W"')
    expect(html).toContain('-5.83%')
    expect(html).toContain('+14.32%')
    expect(html).toContain('data-tone="down"')
    expect(html).toContain('data-tone="up"')
    expect(html).toContain('data-tone="none"')
    expect(html).toContain('Closing prices up to 2026-11-02')
    expect(html).toContain('/trademind/stock/SUZLON')
    expect(html).toContain('ETERNAL did best')
  })

  it('says plainly when a stock has no stored history, and shows no tiles for it', () => {
    const html = render('/trademind/compare?s=suzlon,eternal', {
      periods: PERIODS,
      stocks: [stock('SUZLON', {}, { state: 'no_history', as_of: null, last_close: null }), stock('ETERNAL', { '3M': 14.32 })],
    })
    expect(html).toContain('data-testid="compare-no-numbers"')
    expect(html).toContain('do not hold price history for SUZLON')
    expect(html).not.toContain('tile-SUZLON')
  })

  it('uses no buy or sell advice words', () => {
    const html = render('/trademind/compare?s=suzlon,eternal', {
      periods: PERIODS,
      stocks: [stock('SUZLON', { '3M': -26.64 }), stock('ETERNAL', { '3M': 14.32 })],
    })
    expect(html.replace('not advice to buy or sell', '')).not.toMatch(/\b(buy|sell|strong buy|should)\b/i)
  })
})
