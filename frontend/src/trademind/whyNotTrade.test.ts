import { describe, expect, it } from 'vitest'

import { classifyReason, whyKey, whyNotTrade, type DecisionLike } from './whyNotTrade'

const d = (over: Partial<DecisionLike>): DecisionLike => ({
  word: 'WAIT',
  reasons: [],
  downgraded_from: null,
  downgrade_reason: null,
  overruled_word: null,
  overrule_reason: null,
  ...over,
})

describe('classifyReason: every stored rule line gets a plain sentence', () => {
  // The exact lines the backend writes (m08 rules / engine draft / constitution).
  const cases: [string, string][] = [
    ['Model score 41% is below the buy level 55%.', 'below_buy_level'],
    ['Calibrated chance 30% is below the 35% needed to pay after costs.', 'below_buy_level'],
    ['No opinion about this stock today (no model score or reasoning module answer).', 'no_clear_signal'],
    ['The signals do not favour buying this stock today.', 'no_clear_signal'],
    ['No price data for this stock yet.', 'no_price'],
    ['Good idea, but the risk check said no: Max open positions reached (5).', 'risk_no_room'],
    ['The risk check has not approved this trade.', 'risk_not_approved'],
    ['The risk gate did not approve this trade.', 'risk_not_approved'],
    ["On the exchange's watch list (ASM), so the brain stays away.", 'exchange_watch_list'],
    ['Results on 08 Oct — the brain avoids new trades around this.', 'results_or_event'],
    ['The signals are weak or disagree (confidence 0.42).', 'weak_signals'],
    ['Similar cases lost money on average (expected -0.12 R per trade after costs).', 'similar_cases_lost'],
    ['The market is careful and this stock is falling, so the brain waits for it to turn up.', 'careful_market_downtrend'],
    ['Its sector ranks 9 of 15 — outside the top 5 for new ideas.', 'weak_sector'],
    ['No classic setup (pullback or breakout on volume) today.', 'no_setup'],
    ['Data is not reliable today (stale candles).', 'data_not_reliable'],
    ['Data quality was not checked (the data gateway is not installed).', 'data_not_reliable'],
    ['Owner paused new buys: holiday.', 'buys_paused'],
    ["The trade plan's prices are not usable (stop, buy range and target must be real prices in order).", 'bad_plan'],
  ]
  it.each(cases)('%s', (line, kind) => {
    expect(classifyReason(line)?.kind).toBe(kind)
  })

  it('does not match a line no rule wrote', () => {
    expect(classifyReason('Strong upward move with rising volume.')).toBeNull()
    expect(classifyReason('Plan: buy around ₹100 to ₹102, target ₹108 (+8%).')).toBeNull()
  })

  it('never shows a raw model score: the "below the buy level" detail is hidden', () => {
    const item = classifyReason('Model score 41% is below the buy level 55%.')!
    expect(item.detail).toBeNull()
    expect(item.text).not.toMatch(/\d/)
  })

  it('never shows the account detail for a risk no (amounts, limits, minimum size)', () => {
    expect(classifyReason('Good idea, but the risk check said no: Sector cap reached.')?.detail).toBeNull()
  })
})

describe('whyNotTrade', () => {
  it('is empty for a TRADE and for holding words', () => {
    expect(whyNotTrade(d({ word: 'TRADE', reasons: ['Strong move.'] }))).toEqual([])
    expect(whyNotTrade(d({ word: 'HOLD', reasons: ['Fine.'] }))).toEqual([])
  })

  it('lists each stored blocking reason once, newest downgrade first, and skips the reasons it was liked for', () => {
    const items = whyNotTrade(
      d({
        word: 'AVOID',
        reasons: [
          'Results on 08 Oct — the brain avoids new trades around this.',
          'Good idea, but the risk check said no: Max open positions reached.',
          'Strong upward move with rising volume.',
          'Plan: buy around ₹100 to ₹102.',
        ],
        downgraded_from: 'TRADE',
        downgrade_reason: 'Results on 08 Oct — the brain avoids new trades around this.',
      }),
    )
    expect(items.map((i) => i.kind)).toEqual(['results_or_event', 'risk_no_room'])
  })

  it('shows an unknown downgrade reason as stored, never a guess', () => {
    const items = whyNotTrade(
      d({ word: 'WATCH', reasons: ['The market mode says no new trades today.'], downgraded_from: 'TRADE', downgrade_reason: 'The market mode says no new trades today.' }),
    )
    expect(items).toEqual([{ kind: 'other', text: 'The market mode says no new trades today.', detail: null }])
  })

  it('a WAIT straight from the draft keeps its first stored reason', () => {
    expect(whyNotTrade(d({ word: 'WAIT', reasons: ['No clear direction.'] }))).toEqual([
      { kind: 'other', text: 'No clear direction.', detail: null },
    ])
  })

  it('says nothing when nothing is stored', () => {
    expect(whyNotTrade(d({ word: 'WAIT', reasons: [] }))).toEqual([])
  })

  it("puts the owner's overrule first, with the reason given", () => {
    const items = whyNotTrade(
      d({ word: 'TRADE', overruled_word: 'WAIT', overrule_reason: 'Too risky for me', reasons: ['Strong move.'] }),
    )
    expect(items).toHaveLength(1)
    expect(items[0]!.kind).toBe('owner_overrule')
    expect(items[0]!.text).toContain('WAIT')
    expect(items[0]!.detail).toContain('Too risky for me')
  })
})

describe('whyKey', () => {
  it('ignores numbers that move day to day, so only a real change of reason counts', () => {
    const a = whyNotTrade(d({ reasons: ['Model score 41% is below the buy level 55%.'] }))
    const b = whyNotTrade(d({ reasons: ['Model score 47% is below the buy level 55%.'] }))
    expect(whyKey(a)).toBe(whyKey(b))
    const c = whyNotTrade(d({ word: 'WATCH', reasons: ['Its sector ranks 9 of 15 — outside the top 5 for new ideas.'], downgraded_from: 'TRADE', downgrade_reason: 'Its sector ranks 9 of 15 — outside the top 5 for new ideas.' }))
    expect(whyKey(a)).not.toBe(whyKey(c))
  })
})
