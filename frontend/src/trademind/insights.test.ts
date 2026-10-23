import { describe, expect, it } from 'vitest'

import type { ObsClaim } from '../api/types'
import { NOT_PROVEN, benchCell, bookCell, improvingAnswer } from './insights'

const claim = (claim: string, word: string): ObsClaim => ({
  claim,
  label: claim,
  word,
  numeric: null,
  independence: null,
  independence_note: '',
  protocol_id: null,
  tested_subject: null,
  numbers: null,
  problems: [],
})

describe('improvingAnswer', () => {
  it('is "Not proven" unless the frozen learning test says Proven', () => {
    expect(improvingAnswer(undefined).word).toBe(NOT_PROVEN)
    expect(improvingAnswer([]).word).toBe(NOT_PROVEN)
    for (const w of ['No frozen protocol yet', 'Insufficient evidence', 'Not proven', 'Passed, not proven: independence not established']) {
      expect(improvingAnswer([claim('learning_changes', w)]).word).toBe(NOT_PROVEN)
    }
  })
  it('a Proven verdict on another claim never makes the brain "improving"', () => {
    expect(improvingAnswer([claim('model_ranking_predictive', 'Proven'), claim('full_brain', 'Proven')]).word).toBe(NOT_PROVEN)
  })
  it('only a frozen Proven on learning says so', () => {
    expect(improvingAnswer([claim('learning_changes', 'Proven')]).word).toBe('Proven by a frozen test')
  })
  it('never uses the word "improving" when not proven', () => {
    const a = improvingAnswer([claim('learning_changes', 'No frozen protocol yet')])
    expect(`${a.word} ${a.why}`.toLowerCase()).not.toContain('improving')
  })
})

describe('cells', () => {
  it('no trades is said plainly, not as zero profit', () => {
    expect(bookCell({ finished: 0, wins: 0, net_pnl: 0, charges: 0, money_used: 0, return_pct: null }).main).toBe('No finished trades')
  })
  it('a book shows its own result only', () => {
    const c = bookCell({ finished: 2, wins: 1, net_pnl: -150, charges: 12, money_used: 20000, return_pct: -0.75 })
    expect(c.main).toBe('−₹150.00')
    expect(c.detail).toContain('2 trades, 1 made money')
    expect(c.detail).toContain('−0.75% on money used')
  })
  it('a missing benchmark says why', () => {
    expect(benchCell({ pct: null, why: 'No NIFTY 50 prices are stored for these days.' })).toContain('Not available — No NIFTY 50')
    expect(benchCell({ pct: 1.234, why: null })).toBe('+1.23%')
  })
})
