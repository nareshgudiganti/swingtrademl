import { describe, expect, it } from 'vitest'
import { safeChanges, stepDetail } from './stepDetails'
import type { BrainDecision, BrainRun } from '../api/types'

const run = {
  quality: { overall: { fresh: true, issues: [] }, stale: [] },
  banner: { mode: 'DEFENSIVE', headline: null },
  decisions: [{ kind: 'idea', confidence: 0.92 }, { kind: 'idea', confidence: 0.7 }],
  situations: [
    { scope: 'stock', subject: 'SUZ', label: 'down-trend', confidence: 0.8, is_unknown: false, suggest_defensive: true, evidence: ['SUZ: down-trend.'] },
  ],
} as unknown as BrainRun

const d = {
  symbol: 'SUZ',
  kind: 'idea',
  word: 'WATCH',
  confidence: 0.92,
  reasons: [
    'Good idea, but the risk check said no: After stronger ideas, the half size leaves room for only ₹19,849 — below the ₹39,677 minimum position.',
    'Sector: Energy, ranked 13 of 15, lagging (weaker than NIFTY over 1 and 3 months).',
  ],
  what_would_change: [
    { key: 'a', text: 'The market would need to return to NORMAL: half of this one (₹19,849) is below the ₹39,677 minimum.' },
    { key: 'b', text: 'The stock would need to stop falling.' },
  ],
} as unknown as BrainDecision

describe('stepDetail', () => {
  it('the decision step lists what is for and against, without any account figure', () => {
    const { bullets } = stepDetail(d, run, 7)
    const text = bullets.map((b) => b.text).join(' | ')
    expect(text).toMatch(/WATCH, not BUY/)
    expect(text).toMatch(/market is careful/i)
    expect(text).toMatch(/down-trend/)
    expect(text).toMatch(/Energy, ranked 13 of 15/)
    expect(text).not.toMatch(/₹|minimum|half size|room for only/i)
    expect(bullets.find((b) => /down-trend/.test(b.text))?.tone).toBe('bad')
  })
  it('the market step explains a careful market', () => {
    expect(stepDetail(d, run, 2).bullets.map((b) => b.text).join(' ')).toMatch(/extra proof/)
  })
  it('what would change it drops any line with an amount', () => {
    expect(safeChanges(d)).toEqual(['The stock would need to stop falling.'])
  })
})
