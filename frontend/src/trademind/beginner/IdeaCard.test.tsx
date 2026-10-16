import { renderToString } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import type { BrainDecision } from '../../api/types'
import IdeaCard from './IdeaCard'
import MoneyAtStake from './MoneyAtStake'
import type { MoneyAtStakeData } from './types'

const decision = (over: Partial<BrainDecision> = {}): BrainDecision => ({
  id: 1,
  run_id: 'r1',
  symbol: 'INFY',
  kind: 'idea',
  word: 'TRADE',
  reasons: ['Trend is up', 'Volume is healthy'],
  entry_low: 1500,
  entry_high: 1520,
  target: 1640,
  stop: 1450,
  qty: 10,
  horizon_days: 15,
  confidence: 72,
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

const money: MoneyAtStakeData = {
  available: true,
  why: null,
  invested: 15100,
  loss_if_stop: 612.5,
  gain_if_target: 1050,
  gain_if_half_out: 900,
  charges_round_trip: 40,
}

const html = (d: BrainDecision, m?: MoneyAtStakeData) => renderToString(<IdeaCard decision={d} money={m} />)

describe('IdeaCard', () => {
  it('TRADE with shares shows rupees at stake and the stop loss line', () => {
    const out = html(decision(), money)
    expect(out).toContain('₹ at stake')
    expect(out).toContain('If the stop is hit you lose about ₹612.50')
  })
  it('WATCH with 0 shares shows no rupee line', () => {
    const out = html(decision({ word: 'WATCH', qty: 0 }), money)
    expect(out).not.toContain('₹ at stake')
    expect(out).not.toContain('If the stop is hit')
    expect(out).toContain('No shares allowed')
  })
  it('names the risk rule when the reasons contain one', () => {
    const out = html(decision({ qty: 0, reasons: ['Risk rule: sector limit reached', 'x'] }))
    expect(out).toContain('No shares allowed: Risk rule: sector limit reached')
  })
  it('missing stop shows Not available', () => {
    const out = html(decision({ stop: null }), { available: false, why: 'plan incomplete' })
    expect(out).toContain('Not available')
    expect(out).toContain('plan incomplete')
  })
  it('never says probability or chance of winning on the raw score', () => {
    const out = html(decision())
    expect(out.toLowerCase()).not.toContain('probability')
    expect(out).toContain('72 model score')
    expect(out).toContain('a ranking, not a chance of winning')
    expect(out).not.toMatch(/~\d+%/)
  })
  it('shows a % chance only through honest_score', () => {
    const out = html(
      decision({ honest_score: { status: 'measured', honest_chance: 0.31 } }),
    )
    expect(out).toContain('~31%')
  })
  it('missing confidence shows Not available', () => {
    expect(html(decision({ confidence: null }))).toContain('Score: Not available')
  })
  it('always says Experimental, unproven and the horizon', () => {
    const out = html(decision({ word: 'WAIT', qty: 0 }))
    expect(out).toContain('Experimental, unproven')
    expect(out).toContain('15 trading days')
    expect(out).toContain('Not proven')
  })
  it('renders holding words and events', () => {
    const out = renderToString(
      <IdeaCard
        decision={decision({ kind: 'holding', word: 'HOLD' })}
        events={[
          { symbol: 'INFY', kind: 'results', date: '2026-10-20', trading_days_away: 2, detail: 'q', plain: 'Results in 2 trading days' },
        ]}
      />,
    )
    expect(out).toContain('HOLD')
    expect(out).toContain('Results in 2 trading days')
  })
})

describe('MoneyAtStake', () => {
  it('shows all figures and the after-charges note', () => {
    const out = renderToString(<MoneyAtStake value={money} />)
    expect(out).toContain('₹15,100.00')
    expect(out).toContain('about ₹612.50')
    expect(out).toContain('₹1,050.00')
    expect(out).toContain('₹900.00')
    expect(out).toContain('after charges')
  })
  it('unavailable shows the reason, never a number', () => {
    const out = renderToString(<MoneyAtStake value={{ available: false, why: 'plan incomplete' }} />)
    expect(out).toContain('Not available — plan incomplete')
    expect(out).not.toContain('₹0')
  })
  it('a missing figure is Not available, not 0', () => {
    const out = renderToString(<MoneyAtStake value={{ ...money, loss_if_stop: null }} />)
    expect(out).toContain('Not available')
  })
})
