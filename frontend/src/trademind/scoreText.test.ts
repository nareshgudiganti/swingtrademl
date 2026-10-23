import { describe, expect, it } from 'vitest'

import {
  SCORE_HINT,
  actionLabelText,
  rankText,
  scoreBandText,
  scoreLabel,
  scoreLabelLong,
  scorePoints,
  scoreRank,
  withoutScorePercent,
} from './scoreText'

const day = [0.44, 0.71, 0.58, null]

describe('scorePoints', () => {
  it('turns 0-1 into a whole number out of 100', () => {
    expect(scorePoints(0.716)).toBe(72)
    expect(scorePoints(0)).toBe(0)
    expect(scorePoints(1.2)).toBe(100)
  })
  it('is null when there is no score', () => {
    expect(scorePoints(null)).toBeNull()
    expect(scorePoints(undefined)).toBeNull()
    expect(scorePoints(Number.NaN)).toBeNull()
  })
})

describe('scoreRank', () => {
  it('ranks highest first among the day scores, skipping missing ones', () => {
    expect(scoreRank(0.71, day)).toEqual({ rank: 1, of: 3 })
    expect(scoreRank(0.58, day)).toEqual({ rank: 2, of: 3 })
    expect(scoreRank(0.44, day)).toEqual({ rank: 3, of: 3 })
  })
  it('gives equal scores the same place', () => {
    expect(scoreRank(0.5, [0.6, 0.5, 0.5, 0.4])).toEqual({ rank: 2, of: 4 })
    expect(scoreRank(0.4, [0.6, 0.5, 0.5, 0.4])).toEqual({ rank: 4, of: 4 })
  })
  it('is null when the score is not one of the day scores, or missing', () => {
    expect(scoreRank(0.9, day)).toBeNull()
    expect(scoreRank(null, day)).toBeNull()
    expect(scoreRank(0.5, [])).toBeNull()
  })
})

describe('labels', () => {
  it('shows a rank when the day is known', () => {
    expect(rankText({ rank: 3, of: 12 })).toBe('Rank 3 of 12 today')
    expect(scoreLabel(0.58, day)).toBe('Rank 2 of 3 today')
    expect(scoreLabelLong(0.58, day)).toBe('Rank 2 of 3 today by model score')
  })
  it('falls back to a plain number that says it is not a chance', () => {
    expect(scoreLabel(0.72)).toBe('Model score 72')
    expect(scoreLabel(0.9, day)).toBe('Model score 90')
    expect(scoreLabelLong(0.72)).toBe('Model score 72 (a ranking number, not a chance of profit)')
    expect(scoreLabel(null)).toBe('—')
    expect(scoreLabelLong(null)).toBe('No model score')
  })
  it('never uses a % sign or calls the score a probability', () => {
    const texts = [
      scoreLabel(0.72),
      scoreLabel(0.72, [0.72, 0.5]),
      scoreLabelLong(0.72),
      scoreLabelLong(0.72, [0.72, 0.5]),
      ...['0%-30%', '70%-80%', '80%-100%', '60-70%', '80%+'].map(scoreBandText),
    ]
    for (const t of texts) {
      expect(t).not.toMatch(/%/)
      expect(t).not.toMatch(/probab|likel|odds|\bchance of (?!profit)/i)
    }
    expect(SCORE_HINT).toBe("A ranking among today's ideas, not a chance of making money.")
  })
})

describe('scoreBandText', () => {
  it('drops the % sign from API band names', () => {
    expect(scoreBandText('70%-80%')).toBe('70-80')
    expect(scoreBandText('60-70%')).toBe('60-70')
    expect(scoreBandText('80%+')).toBe('80+')
    expect(scoreBandText('60-70')).toBe('60-70')
  })
})

describe('withoutScorePercent', () => {
  it('takes the % off raw model scores in stored brain lines', () => {
    expect(withoutScorePercent('The active model (ml_main) scores this stock 72%; its buy level is 60%.')).toBe(
      'The active model (ml_main) scores this stock 72; its buy level is 60.',
    )
    expect(withoutScorePercent('Model score 41% is below the buy level 55%.')).toBe('Model score 41 is below the buy level 55.')
    expect(withoutScorePercent('A stronger idea is waiting (INFY, scored 81%) and slots are full.')).toBe(
      'A stronger idea is waiting (INFY, scored 81) and slots are full.',
    )
    expect(withoutScorePercent('Raise the buy level to 70%')).toBe('Raise the buy level to 70')
    expect(withoutScorePercent('Of 120 ideas the model scored 70% to 80% on unseen days')).toBe(
      'Of 120 ideas the model scored 70 to 80 on unseen days',
    )
  })

  it('leaves price moves, hit rates and calibrated chances alone', () => {
    for (const s of ['Up 3.2% today', '+8% before -4%', 'Calibrated chance of +8% before -4%: 31%.', 'won 40% of the time']) {
      expect(withoutScorePercent(s)).toBe(s)
    }
  })
})

describe('actionLabelText', () => {
  it('shows a holding read with the score as a plain number', () => {
    expect(actionLabelText('Still bullish (72% today) — model would buy this fresh right now')).toBe(
      'Still bullish (model score 72 today) — model would buy this fresh right now',
    )
    expect(actionLabelText('Confidence easing (80% → 70%) today — below the buy bar but not weak yet')).toBe(
      'Model score easing (80 → 70) today — below the buy bar but not weak yet',
    )
    expect(actionLabelText('Losing conviction (?% today) — alert already sent')).toBe(
      'Losing conviction (model score ? today) — alert already sent',
    )
    expect(actionLabelText('Up 3.2% — the plan is to sell half at +5%')).toBe('Up 3.2% — the plan is to sell half at +5%')
  })
})
