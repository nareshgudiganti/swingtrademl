// oa12: the one recommendation card. Every signal says "Experimental, unproven"; nothing claims the model is
// validated, proven or profitable; a model score is never shown as a % chance unless it is calibrated; every
// missing item says "Not available" and why.
import { renderToString } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import type { BrainDecision, BrainHonestScore } from '../../api/types'
import { BANNED_CLAIMS, MODEL_STATUS, withoutScorePercent } from './cardText'
import IdeaCard from './IdeaCard'

const decision = (over: Partial<BrainDecision> = {}): BrainDecision => ({
  id: 1,
  run_id: 'r1',
  symbol: 'INFY',
  kind: 'idea',
  word: 'TRADE',
  reasons: ['Strong upward move with rising volume.'],
  entry_low: 1480,
  entry_high: 1500,
  target: 1610,
  stop: 1430,
  qty: 6,
  horizon_days: 15,
  confidence: 0.71,
  honest_score: null,
  evidence_text: null,
  downgraded_from: null,
  downgrade_reason: null,
  overruled_word: null,
  overruled_by: null,
  overrule_reason: null,
  overruled_at: null,
  ...over,
})

const text = (html: string) =>
  html.replace(/<!-- -->/g, '').replace(/<[^>]+>/g, ' ').replace(/&#x27;|&apos;/g, "'").replace(/\s+/g, ' ')

const render = (d: BrainDecision, extra: Partial<Parameters<typeof IdeaCard>[0]> = {}) =>
  text(renderToString(<IdeaCard decision={d} {...extra} />))

const WORDS: Partial<BrainDecision>[] = [
  { word: 'TRADE' },
  { word: 'WATCH', qty: 0 },
  { word: 'WAIT', qty: 0 },
  { word: 'AVOID', qty: 0 },
  { kind: 'holding', word: 'HOLD' },
  { kind: 'holding', word: 'MONITOR' },
  { kind: 'holding', word: 'REDUCE' },
  { kind: 'holding', word: 'EXIT' },
  { word: 'TRADE', overruled_word: 'AVOID', overrule_reason: 'Too risky' },
]

const SCORES: (BrainHonestScore | null)[] = [
  null,
  { status: 'not_measured', note: 'Not measured on unseen days yet.' },
  { status: 'no_score' },
  {
    status: 'measured',
    honest_chance: 0.14,
    caveat: 'Past results do not guarantee future results.',
    track_record: {
      enough_evidence: true,
      text: 'Of 1,200 ideas the model scored 70% to 80% on days it had not seen (2023-07-01 to 2025-01-31), 14% (about 1 in 7) reached the target first.',
    },
  },
]

describe('oa12: one recommendation card', () => {
  it('every signal says "Experimental, unproven" and shows the model status', () => {
    for (const w of WORDS) {
      const out = render(decision(w))
      expect(out, JSON.stringify(w)).toContain('Experimental, unproven')
      expect(out).toContain(MODEL_STATUS)
      expect(out).toContain('7 of 21')
      expect(out).toContain('9 of 21')
    }
  })

  it('never says validated, proven, profitable or probability, whatever the word or score', () => {
    expect(MODEL_STATUS).not.toMatch(BANNED_CLAIMS)
    for (const w of WORDS) {
      for (const h of SCORES) {
        for (const compact of [false, true]) {
          const out = render(decision({ ...w, honest_score: h }), { compact })
          expect(out, `${JSON.stringify(w)} ${h?.status}`).not.toMatch(BANNED_CLAIMS)
        }
      }
    }
  })

  it('shows no % next to the model score unless the score is calibrated', () => {
    for (const h of SCORES.slice(0, 3)) {
      const out = render(decision({ confidence: 0.71, honest_score: h }))
      expect(out).not.toMatch(/\d\s*%/)
      expect(out).toContain('Model score 71')
    }
    // Calibrated: the measured chance may carry a %, the model score itself still does not.
    const cal = render(decision({ confidence: 0.71, honest_score: SCORES[3] }))
    expect(cal).toContain('Estimated chance, measured on past days: ~14%')
    expect(cal).not.toMatch(/71\s*%/)
    expect(cal).not.toMatch(/scored 70% to 80%/)
    expect(cal).toContain('scored 70 to 80')
  })

  it('a raw score written as a % in a stored reason loses its % sign', () => {
    const out = render(
      decision({ word: 'TRADE', reasons: ['The model scores this stock 72% against a buy level of 60%; strong trend.'] }),
    )
    expect(out).toContain('The model scores this stock 72 against a buy level of 60; strong trend.')
    expect(out).not.toMatch(/72%|60%/)
    expect(withoutScorePercent('Model score 41% is below the buy level 55%.')).toBe('Model score 41 is below the buy level 55.')
    // A measured hit rate or a calibrated chance is not a raw score and keeps its %.
    expect(withoutScorePercent('Calibrated chance of +8% before -4%: 31%.')).toBe('Calibrated chance of +8% before -4%: 31%.')
  })

  it('shows the score as a rank among the day\'s ideas when the day is known', () => {
    const out = render(decision({ confidence: 0.58 }), { dayScores: [0.71, 0.58, 0.44] })
    expect(out).toContain('Rank 2 of 3 today by model score')
  })

  it('shows entry zone, target, stop, last exit day, risk verdict, shares and rupees for a TRADE', () => {
    const out = render(decision(), {
      plan: { available: true, why: null, sell_half_price: 1564.5, last_exit_day: '2026-11-12' },
      money: { available: true, why: null, invested: 8940, loss_if_stop: 380, gain_if_target: 640, gain_if_half_out: 520 },
    })
    expect(out).toContain('Buy zone: ₹1,480.00 to ₹1,500.00')
    expect(out).toContain('Target: ₹1,610.00')
    expect(out).toContain('Stop: ₹1,430.00')
    expect(out).toContain('Sell half at: ₹1,564.50')
    expect(out).toContain('Last exit day: Thu 12 Nov 2026 (within 15 trading days)')
    expect(out).toContain('Risk verdict: passed — the paper account may buy 6 shares.')
    expect(out).toContain('Shares (paper account): 6')
    expect(out).toContain('If the stop is hit you lose about ₹380.00')
    expect(out).toContain('Why the brain says this')
    expect(out).toContain('Strong upward move with rising volume.')
    expect(out).toContain('15 trading days')
    expect(render(decision({ horizon_days: 5 }))).toContain('5 trading days — no supported strategy for this window')
  })

  it('every missing item says Not available and why', () => {
    const out = render(decision({ entry_low: null, target: null, stop: null, confidence: null, reasons: [] }))
    expect(out).toContain('Buy zone: Not available — the brain stored no buy zone')
    expect(out).toContain('Target: Not available — plan incomplete')
    expect(out).toContain('Stop: Not available — plan incomplete')
    expect(out).toContain('Sell half at: Not available — the plan details were not loaded')
    expect(out).toContain('Last exit day: Not available — the plan details were not loaded')
    expect(out).toContain('Not available — figures not loaded')
    expect(out).toContain('Model score: Not available — the model gave no score for this stock')
    expect(out).toContain('Not available — the brain did not store a reason for this decision.')
    expect(out).toContain('Past results: Not available — there is no measured record for this kind of idea.')

    const fromBrief = render(decision(), {
      plan: { available: false, why: 'The brain has not looked at this stock today' },
      money: { available: false, why: 'The brain has not looked at this stock today' },
    })
    expect(fromBrief).toContain('Last exit day: Not available — The brain has not looked at this stock today')
    expect(fromBrief).toContain('₹ at stake Not available — The brain has not looked at this stock today')

    const notMeasured = render(decision({ honest_score: SCORES[1] }))
    expect(notMeasured).toContain('Past results: Not available — Not measured on unseen days yet.')
  })

  it('a WATCH idea explains why it is not a TRADE and shows no buy plan', () => {
    const out = render(
      decision({ word: 'WATCH', qty: 0, downgraded_from: 'TRADE', downgrade_reason: 'Good idea, but the risk check said no: sector cap' }),
    )
    expect(out).toContain('No buy plan — the brain says WATCH')
    expect(out).toContain('Risk verdict: lowered from TRADE to WATCH — Good idea, but the risk check said no: sector cap')
    expect(out).not.toContain('Buy zone')
    expect(out).not.toContain('₹ at stake')
  })

  it('the compact card keeps the first reason and folds the rest', () => {
    const out = render(decision({ reasons: ['First reason.', 'Second reason.', 'Third reason.'] }), { compact: true })
    expect(out).toContain('First reason.')
    expect(out).toContain('2 more reasons')
  })

  it('links the stock name to its page when given a link', () => {
    const html = renderToString(
      <MemoryRouter>
        <IdeaCard decision={decision()} linkTo="/trademind/stock/INFY" />
      </MemoryRouter>,
    )
    expect(html).toContain('href="/trademind/stock/INFY"')
    expect(html).toContain('data-card="idea"')
  })
})
