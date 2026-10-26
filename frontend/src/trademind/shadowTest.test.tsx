// Shadow Test page: owner-only, read-only. Running ideas are never counted as results; under 30 days it says
// "too early"; a stale price says "price not updated"; no advice words; nothing here can place an order.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToString } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import type { ShadowTestView } from '../api/types'
import { activeNav, visibleNav } from './newMenu'
import { ShadowView } from './pages/ShadowTest'

const view = (over: Partial<ShadowTestView> = {}): ShadowTestView => ({
  as_of: '2026-10-23',
  label: 'Exploring, not part of the sealed 6-month test. Passive tracking only: nothing here places an order.',
  verdict: { state: 'too_early', headline: 'Too early to tell', detail: 'Only 12 top-ranked ideas have finished. The ranking is not proven.', days_done: 9, days_needed: 30 },
  totals: { running: 2, finished: 140, target: 19, stop: 58 },
  groups: [
    { group: 'Top 5', finished: 12, target: 3, stop: 5, average_pct: 0.9 },
    { group: 'Ranks 6-20', finished: 38, target: 6, stop: 15, average_pct: -0.2 },
    { group: 'Rank 21+', finished: 90, target: 10, stop: 38, average_pct: -0.6 },
  ],
  running: [
    { symbol: 'KEI', rank: 1, group: 'Top 5', score: 95, word: 'WATCH', ranked_on: '2026-10-22', paper_bought: true, day: 4, today_pct: 1.8, since_pct: 3.1, position: 0.59, price_not_updated: false },
    { symbol: 'RBLBANK', rank: 8, group: 'Ranks 6-20', score: 89, word: 'WATCH', ranked_on: '2026-10-21', paper_bought: false, day: 5, today_pct: null, since_pct: -2.3, position: 0.14, price_not_updated: true },
  ],
  finished: [
    { symbol: 'GALAXYSURF', rank: 7, group: 'Ranks 6-20', ranked_on: '2026-10-06', ended_on: '2026-10-15', outcome: 'target', result_pct: 8, days: 9, paper_bought: false },
  ],
  how: ['Rank recorded: a stock enters from the brain’s nightly ranking.', 'Count outcome: it is added to the results of its original rank group.'],
  ...over,
})

function render(v: ShadowTestView) {
  return renderToString(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <ShadowView v={v} />
      </MemoryRouter>
    </QueryClientProvider>,
  ).replace(/<!-- -->/g, '')
}

describe('Shadow Test page', () => {
  it('says too early and shows the day count under 30 days', () => {
    const html = render(view())
    expect(html).toContain('Too early to tell')
    expect(html).toContain('9 / 30')
    expect(html).toContain('not a pass guarantee')
    expect(html).toContain('data-state="too_early"')
  })

  it('is labelled exploring and passive, with the last-close note', () => {
    const html = render(view())
    expect(html).toContain('Tracking only')
    expect(html).toContain('not part of the sealed 6-month test')
    expect(html).toContain('updated after market close')
  })

  it('shows the four totals and the rank-group table (finished only)', () => {
    const html = render(view())
    expect(html).toContain('Running')
    expect(html).toContain('19<span class="sp-small" style="font-size:16px"> of 140')
    expect(html).toContain('Does rank make a difference?')
    expect(html).toContain('Top 5')
    expect(html).toContain('+0.9%')
    expect(html).toContain('−0.2%')
    expect(html).toContain('Open ideas do not count as completed outcomes.')
  })

  it('running rows show day N of 15, the moves and the paper-bought flag', () => {
    const html = render(view())
    expect(html).toContain('4 / 15')
    expect(html).toContain('+1.8%')
    expect(html).toContain('+3.1%')
    expect(html).toContain('sh-yes')
  })

  it('a stock whose price is old says so instead of showing an old move as today’s', () => {
    const html = render(view())
    expect(html).toContain('price not updated')
  })

  it('uses no advice words', () => {
    const html = render(view()).toLowerCase()
    for (const w of ['buy now', 'sell', 'cheap', 'guarantee ', '% chance']) expect(html).not.toContain(w)
  })

  it('an empty test still renders without inventing rows', () => {
    const html = render(view({ running: [], finished: [], totals: { running: 0, finished: 0, target: 0, stop: 0 } }))
    expect(html).toContain('data-testid="shadow-empty"')
    expect(html).not.toContain('data-testid="shadow-running"')
  })

  it('the menu entry is owner only', () => {
    expect(visibleNav(true).map((n) => n.id)).toContain('shadow')
    expect(visibleNav(false).map((n) => n.id)).not.toContain('shadow')
    expect(activeNav('/trademind/shadow-test', true).id).toBe('shadow')
  })
})
