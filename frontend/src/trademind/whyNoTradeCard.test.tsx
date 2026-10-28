import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import type { BrainDecision, BrainRun } from '../api/types'
import { brainSteps } from './brainSteps'
import { PlanLadder, WhyNoTrade } from './stockParts'
import { nextReview, SCORE_IS_NOT_PERMISSION, whyNotTrade } from './whyNotTrade'

const EVENT_LINE = 'Results on 02 Nov: the brain avoids new trades 5 trading days before results'

const dec = (word: string, reasons: string[], over: Partial<BrainDecision> = {}) =>
  ({
    id: 1, symbol: 'CARBORUNIV', kind: 'idea', word, reasons, confidence: 0.86, entry_low: 1074, entry_high: 1096,
    target: 1171.8, stop: 1041.6, horizon_days: 15, downgraded_from: word === 'TRADE' ? null : 'TRADE',
    downgrade_reason: reasons[0] ?? null, overruled_word: null, ...over,
  }) as unknown as BrainDecision

const RUN = {
  banner: { mode: 'NORMAL' }, quality: { overall: { fresh: true, issues: [] }, stale: [] }, situations: [], decisions: [],
} as unknown as BrainRun

describe('nextReview', () => {
  it('names the results date from the stored reason', () => {
    const items = whyNotTrade(dec('AVOID', [EVENT_LINE]))
    expect(nextReview(items)).toBe('After the results on 02 Nov. The brain looks again once they are out.')
  })

  it('says nothing when no date is stored, instead of guessing one', () => {
    const items = whyNotTrade(dec('AVOID', ['Results or an event is close, so the brain avoids new trades around this.']))
    expect(nextReview(items)).toBeNull()
    expect(nextReview(whyNotTrade(dec('WATCH', ['Good idea, but the risk check said no: no room'])))).toBeNull()
  })
})

describe('WhyNoTrade', () => {
  it('explains a blocked rank-1 stock in one place', () => {
    const html = renderToStaticMarkup(<WhyNoTrade decision={dec('AVOID', [EVENT_LINE])} />)
    expect(html).toContain('Why no trade?')
    expect(html).toContain('Company results or a similar event is coming up')
    expect(html).toContain(SCORE_IS_NOT_PERMISSION)
    expect(html).toContain('Next review:')
    expect(html).toContain('02 Nov')
  })

  it('is not shown for a TRADE', () => {
    expect(renderToStaticMarkup(<WhyNoTrade decision={dec('TRADE', [])} />)).toBe('')
  })
})

describe('the plan for a stock that is not a TRADE', () => {
  it('is labelled illustrative and marked so it can be dimmed', () => {
    const html = renderToStaticMarkup(<PlanLadder decision={dec('AVOID', [EVENT_LINE])} />)
    expect(html).toContain('Illustrative only: no buy is recommended today')
    expect(html).toContain('data-illustrative="true"')
  })

  it('is a normal plan for a TRADE', () => {
    const html = renderToStaticMarkup(<PlanLadder decision={dec('TRADE', [])} />)
    expect(html).not.toContain('data-illustrative')
    expect(html).toContain('The plan for this trade.')
  })
})

describe('step 6 never claims the limits passed when testing mode skipped them', () => {
  it('says the limits were switched off', () => {
    const d = dec('TRADE', ['Account limits were switched off for testing, so none were applied.'])
    const step = brainSteps(d, RUN)[5]!
    expect(step.tag).toBe('LIMITS OFF')
    expect(step.line).toMatch(/switched off for testing/)
    expect(step.line).not.toMatch(/passed/i)
  })

  it('still says passed when the limits really ran', () => {
    expect(brainSteps(dec('TRADE', []), RUN)[5]).toMatchObject({ tag: 'PASSED' })
  })
})
