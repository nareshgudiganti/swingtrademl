import { renderToString } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import type { BrainDecision } from '../api/types'
import { BANNED_CLAIMS } from './beginner/cardText'
import { ModelEvidence } from './CaseAnalysis'
import { SCORE_VS_PLAN_SHORT, scoreVsPlan } from './scoreVsPlan'

describe('score versus plan wording', () => {
  it('names both horizons and says they have not been tested together', () => {
    expect(scoreVsPlan()).toContain('5-day')
    expect(scoreVsPlan()).toContain('15 trading days')
    expect(scoreVsPlan()).toContain('has not been tested')
  })

  it('says exactly what it said before the numbers came from the server', () => {
    expect(scoreVsPlan()).toBe(
      'The score is the model’s 5-day reading: how strongly it ranks this stock for a +2% rise within 5 trading days. ' +
        'The trade plan (+8% target, −4% stop, up to 15 trading days) is a separate rule. The score has not been tested ' +
        'against that plan yet, so the plan is not backed by the score’s record.',
    )
  })

  it('never calls the score a calibrated chance, and uses no banned claim', () => {
    for (const t of [scoreVsPlan(), SCORE_VS_PLAN_SHORT]) {
      expect(t).not.toMatch(BANNED_CLAIMS)
      expect(t).not.toMatch(/calibrated|chance of|likelihood|% (chance|probability)/i)
    }
  })

  it('shows on the stock page under the model record', () => {
    const d = { kind: 'idea', honest_score: { status: 'no_score' } } as unknown as BrainDecision
    expect(renderToString(<ModelEvidence decision={d} />)).toContain('score-vs-plan')
  })
})
