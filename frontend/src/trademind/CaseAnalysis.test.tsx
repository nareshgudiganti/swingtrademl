import { describe, expect, it } from 'vitest'
import { renderToString } from 'react-dom/server'

import type { BrainDecision, BrainRun } from '../api/types'
import { CaseAnalysis, caseFigures } from './CaseAnalysis'

const dec = (over: Partial<BrainDecision> = {}): BrainDecision =>
  ({
    id: 1, run_id: 'r', symbol: 'ABC', kind: 'idea', word: 'TRADE', reasons: [], entry_low: 98, entry_high: 102,
    target: 108, stop: 96, qty: 0, horizon_days: 15, confidence: 0.83, honest_score: null, evidence_text: null,
    downgraded_from: null, downgrade_reason: null, overruled_word: null, overrule_reason: null, overruled_by: null,
    overruled_at: null, what_would_change: [], ...over,
  }) as BrainDecision

const run = (ds: BrainDecision[], mode = 'NORMAL') =>
  ({ run_id: 'r', banner: { mode, headline: '' }, decisions: ds }) as unknown as BrainRun

describe('the AI’s case', () => {
  it('draws the plan from the stored entry, target and stop, and says how far the score is from the buy level', () => {
    const d = dec({ confidence: 0.83, honest_score: { track_record: { enough_evidence: true, n: 20, hit_rate: 0.35 } } as never })
    const f = caseFigures(d, run([d]))
    expect(f.score).toBe(83)
    expect(f.entry).toBe(100)
    expect(f.scenarios.map((s) => [s.label, Math.round(s.pct)])).toEqual([['Target', 8], ['Sell half', 5], ['Stop', -4]])
    expect(f.rewardToRisk).toBe(2)
    expect(f.record).toEqual({ n: 20, hits: 7 })
  })

  it('a BUY shows all four charts with the research note; no chance of profit is claimed', () => {
    const d = dec()
    const html = renderToString(<CaseAnalysis decision={d} run={run([d])} />)
    for (const id of ['case-score', 'case-scenarios', 'case-record', 'case-risks']) expect(html).toContain(`data-testid="${id}"`)
    expect(html).toContain('Why the AI says BUY')
    expect(html).toContain('not investment advice')
    expect(html).not.toMatch(/\d+%\s*chance/i)
    expect(html).toContain('Not enough similar past cases')
  })

  it('a WATCH says what would have to change, in the same four-card layout', () => {
    const d = dec({ word: 'WATCH', what_would_change: [{ key: 'k', text: 'More room would need to open up.' }] })
    const html = renderToString(<CaseAnalysis decision={d} run={run([d], 'DEFENSIVE')} />)
    expect(html).toContain('Why the AI says WATCH, not BUY')
    expect(html).toContain('What would have to change')
    expect(html).toContain('More room would need to open up.')
    expect(html).toContain('If it became a BUY')
  })

  it('shows nothing for a holding', () => {
    const d = dec({ kind: 'holding', word: 'HOLD' })
    expect(renderToString(<CaseAnalysis decision={d} run={run([d])} />)).toBe('')
  })
})
