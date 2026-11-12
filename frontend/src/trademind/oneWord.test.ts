import { describe, expect, it } from 'vitest'

import type { BrainDecision, BrainRun } from '../api/types'
import { brainSteps } from './brainSteps'

// A stock the brain likes, held back only by the practice account's room: stored word WATCH, stock verdict TRADE.
const ROOM_ONLY = {
  symbol: 'GRANULES',
  kind: 'idea',
  word: 'WATCH',
  confidence: 0.69,
  reasons: [],
  stock_verdict: 'TRADE',
  stock_verdict_restored: true,
} as unknown as BrainDecision
const RUN = { banner: { mode: 'DEFENSIVE' }, quality: { overall: null, stale: [] }, situations: [], decisions: [ROOM_ONLY] } as unknown as BrainRun

describe('one word per stock', () => {
  it('step "Decide" agrees with the BUY banner when only the account room held the stock back', () => {
    const decide = brainSteps(ROOM_ONLY, RUN, false).at(-2)!
    expect(decide.tag).toBe('TRADE')
    expect(decide.line).not.toMatch(/Not a BUY/)
  })

  it('the owner view of the steps keeps the portfolio word', () => {
    const decide = brainSteps(ROOM_ONLY, RUN, true).filter((s) => s.state === 'word')[0]!
    expect(decide.tag).toBe('WATCH')
  })
})
