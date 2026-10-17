// Swing Picks uses the shared horizon selector (Phase 3a): five horizons, 15 days chosen by default and labelled
// "Experimental, unproven", the 15-day picks listed, and nothing of the picks list or figures changed.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToString } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import type { BrainDecision, BrainRun } from '../../api/types'
import type { HorizonId } from '../horizons'
import Dashboard from './Dashboard'

const idea = (symbol: string, word: string, confidence: number): BrainDecision =>
  ({
    id: symbol.length, run_id: 'r1', symbol, kind: 'idea', word, reasons: ['a reason'], entry_low: 100, entry_high: 102,
    target: 108, stop: 96, qty: 10, horizon_days: 15, confidence, honest_score: null, evidence_text: null,
    downgraded_from: null, downgrade_reason: null, overruled_word: null, overrule_reason: null, overruled_by: null,
    overruled_at: null,
  }) as BrainDecision

const run = {
  run_id: 'r1', kind: 'nightly', as_of: '2026-10-16', live: true, ms: 1, error: null, counts: {}, status: 'done',
  started_at: '2026-10-16T10:20:00Z', banner: { mode: 'NORMAL', headline: null }, book: 'bot', modules: {},
  quality: { overall: null, stale: [] }, sectors: [], situations: [], portfolio: {},
  decisions: [idea('AAAPICK', 'TRADE', 0.9), idea('BBBPICK', 'WATCH', 0.7), idea('CCCSKIP', 'AVOID', 0.2)],
} as unknown as BrainRun

function render(initialHorizon?: HorizonId): string {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  client.setQueryData(['brainLatest', 'nightly'], run)
  return renderToString(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/trademind/dashboard']}>
        <Dashboard initialHorizon={initialHorizon} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const text = (html: string) =>
  html.replace(/<!-- -->/g, '').replace(/<[^>]+>/g, ' ').replace(/&#x27;|&apos;/g, "'").replace(/\s+/g, ' ')

describe('Swing Picks with the shared horizon selector', () => {
  const html = render()

  it('offers the five horizons twice (hero tabs and list tabs), 15 days selected in both', () => {
    expect(html.match(/data-horizon="/g)?.length).toBe(10)
    expect(html.match(/aria-selected="true"[^>]*data-horizon="15d"/g)?.length).toBe(2)
  })

  it('labels 15 days "Experimental, unproven" and never "Validated"', () => {
    expect(text(html)).toContain('Experimental, unproven')
    expect(text(html)).not.toMatch(/\bValidated\b/)
  })

  it('lists the 15-day TRADE and WATCH picks, and not AVOID', () => {
    expect(html).toContain('AAAPICK')
    expect(html).toContain('BBBPICK')
    expect(html).not.toContain('CCCSKIP')
    expect(text(html)).toContain('15 Days (2)')
  })

  it('counts picks only for the supported horizon', () => {
    expect(text(html)).toMatch(/1D: — 5D: — 15D: 2 30D: — 3M: —/)
  })

  it('labels the summary figures as 15-day figures, so they never pass for another window', () => {
    expect(text(html)).toContain("Average of today's 15-day picks")
    expect(text(html)).toContain('15-day window')
  })

  it('says picks exist for the 15-day window only, and keeps its span', () => {
    expect(text(html)).toContain('Picks are shown for the 15-day window only')
    expect(text(html)).toContain('up to 15 trading days')
  })

  it('gives the two horizon lists different names', () => {
    expect(html).toContain('aria-label="Trading horizon"')
    expect(html).toContain('aria-label="Trading horizon (list)"')
  })
})

describe('Swing Picks on a horizon with no supported strategy', () => {
  for (const h of ['1d', '5d', '30d', '90d'] as const) {
    it(`${h}: shows the explanation and no picks, table, filters or pick detail`, () => {
      const page = render(h)
      expect(page).toMatch(new RegExp(`aria-selected="true"[^>]*data-horizon="${h}"`))
      expect(text(page)).toContain('No supported trading strategy for')
      expect(page).not.toContain('<table')
      expect(page).not.toContain('AAAPICK')
      expect(page).not.toContain('Search stock')
      expect(page).not.toContain('Trade setup')
    })
  }

  it('5d separates the research predictions from a trading plan', () => {
    expect(text(render('5d'))).toContain('not a trading plan')
  })
})
