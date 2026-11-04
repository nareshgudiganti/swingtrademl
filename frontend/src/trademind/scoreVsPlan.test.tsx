import { renderToString } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import type { BrainDecision } from '../api/types'
import { BANNED_CLAIMS } from './beginner/cardText'
import { ModelEvidence } from './CaseAnalysis'
import { SCORE_VS_PLAN, SCORE_VS_PLAN_SHORT } from './scoreVsPlan'

describe('score versus plan wording', () => {
  it('names both horizons and says they have not been tested together', () => {
    expect(SCORE_VS_PLAN).toContain('5-day')
    expect(SCORE_VS_PLAN).toContain('15 trading days')
    expect(SCORE_VS_PLAN).toContain('has not been tested')
  })

  it('never calls the score a calibrated chance, and uses no banned claim', () => {
    for (const t of [SCORE_VS_PLAN, SCORE_VS_PLAN_SHORT]) {
      expect(t).not.toMatch(BANNED_CLAIMS)
      expect(t).not.toMatch(/calibrated|chance of|likelihood|% (chance|probability)/i)
    }
  })

  it('shows on the stock page under the model record', () => {
    const d = { kind: 'idea', honest_score: { status: 'no_score' } } as unknown as BrainDecision
    expect(renderToString(<ModelEvidence decision={d} />)).toContain('score-vs-plan')
  })
})
