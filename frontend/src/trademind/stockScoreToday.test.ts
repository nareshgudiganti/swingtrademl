import { describe, expect, it } from 'vitest'

import { stopOf } from './brainSteps'
import { scoreToday, shownWord } from './stockParts'
import type { BrainDecision, BrainRun } from '../api/types'

describe('the brain score for today', () => {
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

describe('the word the stock page shows', () => {
  it('is the stock verdict when only the account room held it back, else the stored word', () => {
    const base = { kind: 'idea', word: 'WATCH', reasons: [] } as unknown as BrainDecision
    expect(shownWord({ ...base, stock_verdict: 'TRADE', stock_verdict_restored: true } as BrainDecision)).toBe('TRADE')
    expect(shownWord({ ...base, stock_verdict: 'WATCH', stock_verdict_restored: false } as BrainDecision)).toBe('WATCH')
  })
})
