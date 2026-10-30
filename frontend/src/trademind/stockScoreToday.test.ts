import { describe, expect, it } from 'vitest'

import { stopOf } from './brainSteps'
import { scoreToday, trailWithToday } from './stockParts'
import type { BrainDecision, BrainRun } from '../api/types'

const trail = [
  { date: '2026-10-27', score: 0.7 },
  { date: '2026-10-28', score: 0.72 },
  { date: '2026-10-29', score: 0.72 },
]

describe('the score list ends on the headline score', () => {
  it('replaces a same-day reading with the headline, keeps earlier days', () => {
    const out = trailWithToday(trail, { date: '2026-10-29', score: 0.85 })
    expect(out.map((t) => [t.date, t.score])).toEqual([
      ['2026-10-27', 0.7],
      ['2026-10-28', 0.72],
      ['2026-10-29', 0.85],
    ])
  })

  it('adds today after the last day when the daily list is behind', () => {
    const out = trailWithToday(trail, { date: '2026-10-30', score: 0.85 })
    expect(out).toHaveLength(4)
    expect(out.at(-1)).toEqual({ date: '2026-10-30', score: 0.85 })
  })

  it('leaves the list alone when the brain stored no score', () => {
    expect(trailWithToday(trail, null)).toBe(trail)
  })

  it('dates the run by the Indian calendar day', () => {
    const d = { confidence: 0.85 } as BrainDecision
    // 21:00 UTC on 29 Oct is 02:30 IST on 30 Oct
    expect(scoreToday(d, { started_at: '2026-10-29T21:00:00Z' } as BrainRun)?.date).toBe('2026-10-30')
  })
})

describe('the chain has no account step', () => {
  it('an owner-page idea held back only by the account room has no stop', () => {
    const d = { kind: 'idea', word: 'WATCH', reasons: [], stock_verdict_restored: true } as unknown as BrainDecision
    expect(stopOf(d, false)).toBeNull()
  })
})
