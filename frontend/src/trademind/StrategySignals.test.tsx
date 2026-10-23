// oa5: the version 1 per-strategy signals, read only, in Discover. Each signal says "Experimental, unproven", the
// model score never has a % sign, and nothing on it buys or sells.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToString } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import type { Strategy, StrategySignal } from '../api/types'
import { BANNED_CLAIMS } from './beginner/cardText'
import { StrategySignals, signalOutcome } from './StrategySignals'

const strategy = (id: number, name: string, type = 'ml_swing', active = true) =>
  ({ id, name, strategy_type: type, is_active: active, symbols: [], params: {} }) as unknown as Strategy

const signal = (id: number, symbol: string, over: Partial<StrategySignal> = {}): StrategySignal =>
  ({
    id, strategy_id: 1, instrument_id: id, tradingsymbol: symbol, name: symbol, signal_type: 'BUY', mode: 'paper',
    price: 1500, confidence: 0.72, suggested_quantity: 2, stop_loss: 1440, take_profit: 1620, reason: null,
    features: { probability: 0.72 }, was_executed: false, rejection_reason: null, advisory_only: false,
    generated_at: '2026-10-22T10:00:00Z', ...over,
  }) as StrategySignal

function render(open = false): string {
  const c = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  c.setQueryData(['strategies'], [
    strategy(7, 'TradeMind brain', 'brain'),
    strategy(1, 'ML swing (large)'),
    strategy(2, 'ML swing (mid)', 'ml_swing', false),
  ])
  c.setQueryData(['strategySignals', 1, 'discover'], [
    signal(1, 'INFY'),
    signal(2, 'TCS', { signal_type: 'HOLD', confidence: 0.41, rejection_reason: 'Already holding this stock' }),
  ])
  return renderToString(
    <QueryClientProvider client={c}>
      <MemoryRouter>
        <StrategySignals initiallyOpen={open} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const text = (html: string) =>
  html.replace(/<!-- -->/g, '').replace(/<[^>]+>/g, ' ').replace(/&#x27;|&apos;/g, "'").replace(/\s+/g, ' ')

describe('Version 1 strategy signals in Discover', () => {
  it('is closed until opened, and loads nothing before that', () => {
    const html = render()
    expect(html).toContain('data-feature="classic-strategy-signals"')
    expect(html).not.toContain('data-testid="strategy-signals"')
  })

  it('lists the first active strategy that is not the brain, and offers the others', () => {
    const html = render(true)
    expect(html).toContain('data-signal="INFY"')
    expect(html).toContain('data-signal="TCS"')
    expect(text(html)).toContain('ML swing (mid) (switched off)')
    expect(html).not.toMatch(/<option[^>]*>TradeMind brain/)
  })

  it('every signal says "Experimental, unproven"; the score has no % and nothing claims proof', () => {
    const html = render(true)
    const rows = html.split('data-signal="').slice(1).map((r) => r.slice(0, r.indexOf('</tr>')))
    expect(rows.length).toBe(2)
    for (const r of rows) {
      expect(text(r)).toContain('Experimental, unproven')
      expect(text(r)).not.toMatch(/\d\s*%/)
    }
    expect(text(html)).toContain('Model score 72')
    expect(text(html)).not.toMatch(BANNED_CLAIMS)
  })

  it("says it is read only and not the brain's ideas, and has no button that trades", () => {
    const html = render(true)
    expect(text(html)).toContain('Read only: nothing here buys or sells.')
    expect(text(html)).toContain("These are not the brain's ideas.")
    expect(html).not.toMatch(/<button/)
  })

  it('says what happened to each signal in plain words', () => {
    expect(signalOutcome(signal(1, 'A', { was_executed: true }))).toBe('Acted on (paper)')
    expect(signalOutcome(signal(1, 'A', { rejection_reason: 'Model scored 41% below the bar' }))).toBe(
      'Not acted on: Model scored 41 below the bar',
    )
    expect(signalOutcome(signal(1, 'A', { advisory_only: true }))).toBe('Advice only')
  })
})
