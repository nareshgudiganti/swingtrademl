// #326: explicit 5D / 10D / 15D forecast flags. The score is only ever the 5-day reading; research-only or
// unserved windows are marked unavailable; the plan's day count is worded as a hold, never as a forecast.
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { renderToString } from 'react-dom/server'
import { afterEach, describe, expect, it } from 'vitest'
import type { TradingRulesDto } from '../api/types'
import { HorizonFlags, holdText, horizonFlags } from './horizonFlags'
import { setTradingRules } from './tradingRules'

const here = path.dirname(fileURLToPath(import.meta.url))
const read = (p: string) => fs.readFileSync(path.join(here, p), 'utf8')

const base: TradingRulesDto = {
  research: {
    version: 'hz-rules-v1',
    sha256: 'test',
    horizons: [
      { horizon: 5, target_pct: 0.02, stop_pct: 0.04, half_out_pct: null, max_sessions: 5, research_only: false },
      { horizon: 10, target_pct: 0.06, stop_pct: 0.035, half_out_pct: null, max_sessions: 10, research_only: true },
      { horizon: 15, target_pct: 0.08, stop_pct: 0.04, half_out_pct: 0.05, max_sessions: 15, research_only: true },
    ],
  },
  brain_plan: { target_pct: 0.08, stop_pct: 0.04, half_out_pct: 0.05, max_sessions: 15 },
  risk_limits: { max_drawdown_pct: 0.15 },
  trial: { start: '2026-10-14', min_sessions: 15, sessions_so_far: 0 },
  calendar: { holidays: ['2026-10-20', '2026-11-10', '2026-11-24'] },
}

afterEach(() => setTradingRules(base))

describe('horizon flags (#326)', () => {
  it('only the 5-day window is used for the score; 10 and 15 days are not available', () => {
    const f = horizonFlags()
    expect(f.map((x) => [x.horizon, x.state])).toEqual([
      [5, 'score'],
      [10, 'unavailable'],
      [15, 'unavailable'],
    ])
    expect(f[0]!.label).toBe('5D forecast: used for the score')
    expect(f[1]!.label).toBe('10D forecast: not available')
    expect(f[2]!.detail).toMatch(/Research only/)
  })

  it('a viewer who is not served the research windows still sees them marked unavailable', () => {
    setTradingRules({ ...base, research: { ...base.research, horizons: [base.research.horizons[0]!] } })
    const f = horizonFlags()
    expect(f[1]).toMatchObject({ state: 'unavailable', detail: 'Not available.' })
    expect(f[2]).toMatchObject({ state: 'unavailable', detail: 'Not available.' })
  })

  it('the 15-day label never stands in for the score, and the hold comes from the served plan', () => {
    const html = renderToString(<HorizonFlags />)
    expect(html).not.toMatch(/15D forecast: used/)
    expect(html).toContain('Up to 15-day hold')
    setTradingRules({ ...base, brain_plan: { ...base.brain_plan, max_sessions: 12 } })
    expect(holdText()).toBe('Up to 12-day hold')
    expect(holdText(9)).toBe('Up to 9-day hold')
  })

  it('Today, Stock Detail and Idea reports all show the same flags; no bare "15D" badge or "N days" title is left', () => {
    for (const f of ['today/SwingPicks.tsx', 'pages/StockDetail.tsx', 'pages/IdeaReports.tsx']) {
      expect(read(f), f).toContain('<HorizonFlags compact />')
    }
    const today = read('today/SwingPicks.tsx')
    expect(today).not.toContain('{d.horizon_days}D</span>')
    expect(today).not.toContain('Trade setup (${d.horizon_days} days)')
    expect(read('pages/IdeaReports.tsx')).not.toContain('`${h} days`')
  })
})
