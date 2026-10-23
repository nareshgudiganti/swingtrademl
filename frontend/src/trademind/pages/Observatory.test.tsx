// ob15: Observatory display fixes from the Phase 1A review, drawn from cached data (no network).
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToString } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import type { ObsOutcomes } from '../../api/types'
import Observatory from './Observatory'
import { ObservatoryBoundary, ObservatoryCrash } from './ObservatoryBoundary'

const text = (html: string) =>
  html.replace(/<!-- -->/g, '').replace(/<[^>]+>/g, ' ').replace(/&#x27;|&apos;/g, "'").replace(/\s+/g, ' ')

const DAY = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata' }).format(new Date())

function render(seed: (c: QueryClient) => void): string {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  seed(client)
  return text(renderToString(<QueryClientProvider client={client}><Observatory /></QueryClientProvider>))
}

const runSummary = {
  id: 'nightly-20261015T102000-abcdef', kind: 'nightly', live: true, status: 'running', book: 'paper',
  as_of: '2026-10-15T10:20:00+00:00', day: '2026-10-15', started_at: '2026-10-15T10:20:00+00:00',
  finished_at: null, ms: 0, error: null,
}

describe('Observatory page (ob15)', () => {
  it('labels run times in India time, converted, not "UTC"', () => {
    const html = render((c) => {
      c.setQueryData(['obs-runs', DAY], {
        pages: [{ date: DAY, nightly: { state: 'in_progress', expectation: '' }, intraday: {}, items: [runSummary], next_cursor: null }],
        pageParams: [undefined],
      })
    })
    expect(html).toContain('nightly · running · 15:50 IST')
    expect(html).not.toMatch(/\bUTC\b/)
  })

  it('an unfinished run shows no 0 s duration and names no false completion', () => {
    const html = render((c) => {
      c.setQueryData(['obs-runs', DAY], {
        pages: [{ date: DAY, nightly: { state: 'in_progress', expectation: '' }, intraday: {}, items: [runSummary], next_cursor: null }],
        pageParams: [undefined],
      })
      c.setQueryData(['obs-run', runSummary.id], {
        run: runSummary, headline: 'running', banner: { mode: null, headline: null }, modules: [],
        counts: { used: 0, failed: 0, not_observed: 0, unknown: 0 }, step_fallbacks: [], outside_steps: [],
        stage_that_day: { stage: null, label: '' }, words: { idea: {}, holding: {}, ideas_total: 0, holdings_total: 0 },
        universe_relation: { state: 'not_observed', ideas: 0, holdings: 0 },
        recording: { card: 'x', phase: '1A', not_recorded: [], versions: '' }, redacted_fields: [],
      })
    })
    expect(html).toContain('Not finished yet')
    expect(html).toContain('not finished yet ·')
    expect(html).not.toMatch(/\b0 s\b/)
  })
})

describe('Results figures (ob15)', () => {
  it('calls the every-stock figure an average of every stock, not a random baseline', async () => {
    const { FIGURE_LABELS } = await import('../observatoryText')
    expect(FIGURE_LABELS.every_stock).not.toMatch(/random/i)
    expect(FIGURE_LABELS.every_stock).toMatch(/average/i)
  })

  it('an unknown excluded count does not print "null"', async () => {
    const { excludedText } = await import('../observatoryText')
    const t = excludedText({ other_stage_days: null, other_book_runs: 2 } as unknown as NonNullable<ObsOutcomes['excluded']>)
    expect(t).not.toMatch(/null/)
    expect(t).toMatch(/2 run\(s\) in another book/)
  })
})

describe('error boundary (ob15)', () => {
  it('turns a drawing error into a plain message', () => {
    expect(ObservatoryBoundary.getDerivedStateFromError(new Error('boom'))).toEqual({ error: new Error('boom') })
    const html = text(renderToString(<ObservatoryCrash error={new Error('boom')} />))
    expect(html).toContain('This page could not be drawn.')
    expect(html).toContain('Page said: boom')
  })
})
