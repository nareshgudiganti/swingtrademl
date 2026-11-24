import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, describe, expect, it } from 'vitest'

import type { TradingRulesDto } from '../api/types'
import { setToken } from '../api/client'
import { HORIZONS } from './horizons'
import { levelFor, barPercent } from './pages/positionLevels'
import { safetyRules } from './portfolioRules'
import { scoreVsPlan } from './scoreVsPlan'
import { stopTarget } from './trackerRules'
import { safetySummary } from './today/answerRules'
import { GLOSSARY } from './vocab'
import { fiveDayQuestion, fiveDayQuestionWords, plan, setTradingRules } from './tradingRules'
import TradingRulesGate, { RulesUnavailable, showsNoRuleNumbers } from './TradingRulesGate'
import { trialProgress, trialSessionsSoFar, trialStartText } from './wave3Rules'

// What the server answers today; test-setup.ts loads the same values for every test file.
const TODAY: TradingRulesDto = {
  research: {
    version: 'hz-rules-v1',
    sha256: 'x',
    horizons: [{ horizon: 5, target_pct: 0.02, stop_pct: 0.04, half_out_pct: null, max_sessions: 5, research_only: false }],
  },
  risk_limits: { max_drawdown_pct: 0.15 },
  brain_plan: { target_pct: 0.08, stop_pct: 0.04, half_out_pct: 0.05, max_sessions: 15 },
  trial: { start: '2026-10-14', min_sessions: 15, sessions_so_far: 0 },
  calendar: { holidays: ['2026-10-20', '2026-11-10'] },
}
const CHANGED: TradingRulesDto = {
  ...TODAY,
  brain_plan: { target_pct: 0.09, stop_pct: 0.03, half_out_pct: 0.06, max_sessions: 12 },
}

afterEach(() => {
  setTradingRules(TODAY)
  localStorage.clear()
})

describe('the screens say exactly what they said before, now from the server numbers', () => {
  it('position levels', () => {
    expect(levelFor(-4.5).advice).toBe('It hit your −4% stop. Consider selling now.')
    expect(levelFor(8.1).advice).toBe("It hit the +8% target of the app's 15-day plan. Consider booking profit.")
    expect(levelFor(7.3).advice).toBe('0.7% from your +8% target (15-day plan). Consider booking profit at the target.')
    expect(levelFor(5.2).advice).toBe('At or above +5%. Review selling half of your position.')
    expect(levelFor(-3.5).advice).toBe('0.5% from your −4% stop. Consider selling if it falls further.')
    expect(levelFor(4.2).advice).toBe('0.8% from +5%. Be ready to sell half.')
    expect(barPercent(2)).toBe(50)
  })

  it('stop and target prices are the same numbers as before', () => {
    expect(stopTarget(100)).toEqual({ stop: 96, target: 108 })
  })

  it('the safety rules and the safety line', () => {
    const texts = safetyRules({}).map((r) => r.text)
    expect(texts).toContain('Sell if a stock falls 4% below its buy price')
    expect(texts).toContain('Sell half at +5%, the rest at the +8% target')
    expect(texts).toContain('Sell within 15 trading days')
    expect(safetySummary({ owner: false, ddPct: null, haltPct: null }).text).toBe(
      "Safety net on: every trade in the Brain's 15-day trial has a −4% stop, a +8% target and a 15-trading-day limit.",
    )
  })

  it('the brain step, the glossary and the 15-day window', () => {
    expect(GLOSSARY.stop_loss.text).toContain('4% below the buy price')
    expect(GLOSSARY.target.text).toBe('The price at which the plan takes its profit: 8% above the buy price.')
    expect(GLOSSARY.horizon.text).toContain('at most 15 trading days, about three weeks')
    expect(GLOSSARY.est_chance.text).toContain('went up 8% before falling 4%, within 15 trading days')
    const h = HORIZONS.find((x) => x.id === '15d')!
    expect([h.days, h.title, h.span]).toEqual([15, '15 Days', 'up to 15 trading days'])
  })

  it('the trial counter and its text', () => {
    expect(trialSessionsSoFar('2026-10-23')).toBe(7)
    expect(trialProgress('2026-10-25').line).toBe('Trading day 7 of 15')
    expect(trialStartText()).toBe('14 Oct 2026')
  })
})

describe('the numbers follow the server', () => {
  it('a different plan from the server changes every text that states it', () => {
    setTradingRules(CHANGED)
    expect(plan()).toEqual({ targetPct: 9, stopPct: 3, halfPct: 6, days: 12 })
    expect(levelFor(9.5).advice).toBe("It hit the +9% target of the app's 12-day plan. Consider booking profit.")
    expect(safetyRules({}).map((r) => r.text)).toContain('Sell within 12 trading days')
    expect(stopTarget(100)?.stop).toBeCloseTo(97)
    expect(HORIZONS.find((x) => x.id === '15d')!.span).toBe('up to 12 trading days')
  })

  it('the drawdown limit is read from the server and worded as before', () => {
    expect(GLOSSARY.drawdown.text).toContain('If it falls 15% below that high point')
    expect(safetyRules({}).map((r) => r.text)).toContain('Stop all new buys if the account falls 15% from its peak')
    setTradingRules({ ...TODAY, risk_limits: { max_drawdown_pct: 0.2 } })
    expect(GLOSSARY.drawdown.text).toContain('If it falls 20% below that high point')
    expect(safetyRules({}).map((r) => r.text)).toContain('Stop all new buys if the account falls 20% from its peak')
  })

  it('the score-versus-plan sentence and the 5-day numbers come from the horizons', () => {
    setTradingRules({
      ...TODAY,
      research: {
        ...TODAY.research,
        horizons: [{ horizon: 5, target_pct: 0.03, stop_pct: 0.04, half_out_pct: null, max_sessions: 6, research_only: false }],
      },
    })
    expect(scoreVsPlan()).toContain('for a +3% rise within 6 trading days')
  })

  it('a changed holiday list changes the trial count', () => {
    setTradingRules({ ...TODAY, calendar: { holidays: [] } })
    expect(trialSessionsSoFar('2026-10-23')).toBe(8)
  })
})

describe('no numbers, no guess', () => {
  it('with nothing loaded, a number is refused rather than invented', () => {
    setTradingRules(null)
    expect(() => plan()).toThrow('not loaded')
    expect(() => levelFor(1)).toThrow('not loaded')
    expect(() => stopTarget(100)).toThrow('not loaded')
  })
})

describe('the gate', () => {
  const render = (client: QueryClient) =>
    renderToStaticMarkup(
      <QueryClientProvider client={client}>
        <TradingRulesGate>
          <p>the app</p>
        </TradingRulesGate>
      </QueryClientProvider>,
    )

  it('signed out: no request, the app shows', () => {
    expect(render(new QueryClient())).toContain('the app')
  })

  it('signed in, still loading: the app waits', () => {
    setToken('t')
    const html = render(new QueryClient())
    expect(html).not.toContain('the app')
    expect(html).toContain('Loading')
  })

  it('signed in, loaded: the app shows', () => {
    setToken('t')
    const client = new QueryClient()
    client.setQueryData(['tradingRules'], TODAY)
    expect(render(client)).toContain('the app')
  })

  it('failed: says so plainly, offers a retry, and carries no number', () => {
    const html = renderToStaticMarkup(<RulesUnavailable onRetry={() => {}} />)
    expect(html).toContain('unavailable')
    expect(html).toContain('Try again')
    expect(html.replace(/<[^>]*>/g, '')).not.toMatch(/\d/) // the words only, no number
  })

  it('the failure card also offers a sign-out', () => {
    expect(renderToStaticMarkup(<RulesUnavailable onRetry={() => {}} />)).toContain('Sign out')
  })

  it('only the owner pages that show no rule number open when the numbers are missing', () => {
    for (const ok of ['/admin', '/plans', '/trademind/people', '/trademind/plans', '/trademind/people/7']) {
      expect(showsNoRuleNumbers(ok), ok).toBe(true)
    }
    for (const no of ['/', '/trademind', '/trademind/today', '/trademind/portfolio', '/administrator', '/plansx']) {
      expect(showsNoRuleNumbers(no), no).toBe(false)
    }
  })

  it('the gate shows that card, not the app, when the request failed', async () => {
    // (no browser here: read the gate's own source for the branch, the card itself is rendered above)
    const source = (await import('./TradingRulesGate.tsx?raw')).default
    expect(source).toContain('if (rules.isError) {')
    expect(source).toContain('return <RulesUnavailable onRetry={retry} />')
    expect(source.indexOf('rules.isError')).toBeLessThan(source.indexOf('return <Loading />'))
  })

  it('the numbers are stored when the request finishes, never while rendering', async () => {
    const source = (await import('./TradingRulesGate.tsx?raw')).default
    expect(source).not.toContain('setTradingRules(rules.data)')
    expect(source).toContain('setTradingRules(loaded)')
  })

  it('the 5-session sentences read their numbers from the horizon', () => {
    setTradingRules({
      ...TODAY,
      research: {
        ...TODAY.research,
        horizons: [{ horizon: 5, target_pct: 0.03, stop_pct: 0.04, half_out_pct: null, max_sessions: 6, research_only: false }],
      },
    })
    expect(fiveDayQuestion()).toBe('+3% or more after 6 days')
    expect(fiveDayQuestionWords()).toBe('does the price close 3% or more higher within 6 days')
    expect(HORIZONS.find((x) => x.id === '5d')!.research).toContain('(closes +3% or more after 6 days)')
  })
})
