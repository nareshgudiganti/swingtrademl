// #326: a phone has no tooltip, so wherever the app shows an estimated chance it must also show, as visible text,
// which question that chance answers: +8% before -4%, within 15 days, in the trial. With no measured chance there
// is no chance on screen, so none of that text may appear either. Wording only: no number or rule is touched.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToString } from 'react-dom/server'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import type { BrainDecision, BrainRun } from '../api/types'
import IdeaCard from './beginner/IdeaCard'
import { chanceScale } from './honest'
import AIDecision from './pages/AIDecision'
import { SwingPicksList } from './today/SwingPicks'

const measured = { status: 'calibrated', honest_chance: 0.62, track_record: { enough_evidence: false } } as const
const unmeasured = { status: 'not_measured', note: 'This model has no measured results yet.' } as const

const decision = (honest: BrainDecision['honest_score']): BrainDecision => ({
  id: 1,
  run_id: 'r1',
  symbol: 'INFY',
  kind: 'idea',
  word: 'TRADE',
  reasons: ['Trend is up'],
  entry_low: 1500,
  entry_high: 1520,
  target: 1640,
  stop: 1450,
  qty: 10,
  horizon_days: 15,
  confidence: 0.72,
  honest_score: honest,
  evidence_text: null,
  downgraded_from: null,
  downgrade_reason: null,
  overruled_word: null,
  overruled_by: null,
  overrule_reason: null,
  overruled_at: null,
})

const run = (d: BrainDecision) =>
  ({
    run_id: 'r1', kind: 'nightly', as_of: '2026-10-16', live: true, ms: 1, error: null, counts: {}, status: 'done',
    started_at: '2026-10-16T10:20:00Z', banner: { mode: 'NORMAL', headline: null }, book: 'bot', modules: {},
    quality: { overall: null, stale: [] }, sectors: [], situations: [], portfolio: {}, decisions: [d],
  }) as unknown as BrainRun

const plainText = (html: string) =>
  html
    .replace(/<!-- -->/g, '')
    .replace(/<[^>]+>/g, ' ')
    .replace(/&#x27;|&apos;/g, "'")
    .replace(/&amp;/g, '&')
    .replace(/\s+/g, ' ')

// The text a person can read on a phone: the markup with every attribute (title, aria-label) removed.
const visible = (html: string) => plainText(html)

const clientWith = (r?: BrainRun) => {
  const c = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  c.setQueryData(['plan'], { can_manage_plans: false, unrestricted: false, features: ['trademind'], brain_enabled: true })
  if (r) {
    c.setQueryData(['brainLatest', 'nightly'], r)
    c.setQueryData(['brainHealth'], { enabled: true, stage: 'shadow', runs_today: 1 })
  }
  return c
}

// Plain English: what the model aims for, in how many days, and that it is the trial.
const SCALE = /aims for \+8% target before the −4% stop, within 15 trading days \(15-day trial\)/
const NO_SCALE = /aims for|\+8% target before/

describe('the shared scale text', () => {
  it('says in plain English what the chance is for, and only when a chance is measured', () => {
    expect(chanceScale(decision(measured))).toBe('aims for +8% target before the −4% stop, within 15 trading days (15-day trial)')
    expect(chanceScale(decision(unmeasured))).toBe('')
    expect(chanceScale(decision(null))).toBe('')
  })

  it('reads the rule the server sent when there is one, and says "trial" without claiming 15 days', () => {
    const withRule = decision({ ...measured, rule: '+8% target before the -4% stop, within 15 trading days' })
    expect(chanceScale(withRule)).toBe('aims for +8% target before the −4% stop, within 15 trading days (trial)')
    const other = decision({ ...measured, rule: '+5% target before the -3% stop, within 10 trading days' })
    expect(chanceScale(other)).toBe('aims for +5% target before the −3% stop, within 10 trading days (trial)')
    expect(chanceScale(other)).not.toContain('15')
  })
})

describe('IdeaCard shows the scale as visible text', () => {
  const html = (d: BrainDecision) => renderToString(<IdeaCard decision={d} />)
  it('with a measured chance', () => {
    expect(visible(html(decision(measured)))).toMatch(SCALE)
  })
  it('without one: no chance and none of the scale', () => {
    const out = visible(html(decision(unmeasured)))
    expect(out).not.toMatch(NO_SCALE)
    expect(out).not.toContain('~62%')
  })
})

describe('Swing Picks shows the scale as visible text', () => {
  const html = (d: BrainDecision) =>
    renderToString(
      <QueryClientProvider client={clientWith(run(d))}>
        <MemoryRouter>
          <SwingPicksList run={run(d)} win="15d" onWin={() => {}} />
        </MemoryRouter>
      </QueryClientProvider>,
    )
  it('with a measured chance', () => {
    const out = visible(html(decision(measured)))
    expect(out).toContain('~62%')
    expect(out).toMatch(SCALE)
  })
  it('without one: no chance and none of the scale', () => {
    const out = visible(html(decision(unmeasured)))
    expect(out).not.toContain('~62%')
    expect(out).not.toMatch(NO_SCALE)
  })
})

describe('AI decision shows the scale as visible text', () => {
  const html = (d: BrainDecision) =>
    renderToString(
      <QueryClientProvider client={clientWith(run(d))}>
        <MemoryRouter initialEntries={['/trademind/ai/INFY']}>
          <Routes>
            <Route path="/trademind/ai/:symbol" element={<AIDecision />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )
  it('with a measured chance', () => {
    const out = visible(html(decision(measured)))
    expect(out).toContain('~62% chance')
    expect(out).toMatch(SCALE)
  })
  it('without one: no chance and none of the scale', () => {
    const out = visible(html(decision(unmeasured)))
    expect(out).not.toContain('~62%')
    expect(out).not.toMatch(NO_SCALE)
  })
})
