import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, describe, expect, it } from 'vitest'

import type { BrainDecision, TradingRulesDto } from '../api/types'
import { IdeaPlanCell } from './IdeasTable'
import { PlanLadder } from './stockParts'
import { halfOutPrice, plan, setTradingRules } from './tradingRules'

const dec = (over: Partial<BrainDecision> = {}) =>
  ({
    id: 1, symbol: 'INFY', kind: 'idea', word: 'TRADE', reasons: [], confidence: 0.7, entry_low: 1480, entry_high: 1495,
    target: 1610, stop: 1430, horizon_days: 15, downgraded_from: null, downgrade_reason: null, overruled_word: null, ...over,
  }) as unknown as BrainDecision

const rulesWith = (half: number, target = 0.08, stop = 0.04, days = 15): TradingRulesDto => ({
  research: { version: 'x', sha256: 'x', horizons: [] },
  risk_limits: { max_drawdown_pct: 0.15 },
  brain_plan: { target_pct: target, stop_pct: stop, half_out_pct: half, max_sessions: days },
  trial: { start: '2026-10-14', min_sessions: 15, sessions_so_far: 0 },
  calendar: { holidays: [] },
})
const BASE = rulesWith(0.05)

afterEach(() => setTradingRules(BASE))

describe('halfOutPrice', () => {
  it('prices the half-way sale from the served half-out percent', () => {
    expect(halfOutPrice(1000)).toBeCloseTo(1050, 6)
    setTradingRules(rulesWith(0.06))
    expect(halfOutPrice(1000)).toBeCloseTo(1060, 6)
    expect(plan().halfPct).toBe(6)
  })
})

describe('PlanLadder "Sell half"', () => {
  it('shows a price that follows the served half-out percent, label and price together', () => {
    setTradingRules(rulesWith(0.06))
    const html = renderToStaticMarkup(<PlanLadder decision={dec()} />)
    expect(html).toContain('+6%')
    expect(html).toContain('1,576.75')
    expect(html).not.toContain('1,561.88')
  })
})

describe('IdeaPlanCell (Discover table)', () => {
  it('shows buy zone, target and stop for a TRADE row, with the rules in the tooltip only', () => {
    const html = renderToStaticMarkup(<IdeaPlanCell d={dec()} />)
    expect(html).toContain('1,480')
    expect(html).toContain('1,495')
    expect(html).toContain('1,610')
    expect(html).toContain('1,430')
    const visible = html.replace(/<[^>]*>/g, '')
    expect(visible).not.toMatch(/%|chance|probab/i)
    expect(html).toMatch(/title="[^"]*\+8%[^"]*−4%[^"]*\+5%[^"]*15 trading days/)
  })

  it('takes the tooltip numbers from the served rules', () => {
    setTradingRules(rulesWith(0.06, 0.09, 0.03, 12))
    const html = renderToStaticMarkup(<IdeaPlanCell d={dec()} />)
    expect(html).toMatch(/title="[^"]*\+9%[^"]*−3%[^"]*\+6%[^"]*12 trading days/)
  })

  it('is a dash for a row that is not a TRADE, and when the stored levels are missing', () => {
    expect(renderToStaticMarkup(<IdeaPlanCell d={dec({ word: 'WATCH', downgraded_from: 'TRADE' })} />)).toContain('—')
    expect(renderToStaticMarkup(<IdeaPlanCell d={dec({ word: 'WATCH', downgraded_from: 'TRADE' })} />)).not.toContain('1,610')
    expect(renderToStaticMarkup(<IdeaPlanCell d={dec({ target: null })} />)).not.toContain('1,480')
  })
})
