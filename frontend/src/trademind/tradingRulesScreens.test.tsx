// #416 acceptance: the Today, Portfolio and Groww Tracker screens show the numbers the backend served, and a
// changed backend value changes the text on the screen. Rendered through the real app routes (new look).
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToString } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import type { TradingRulesDto, WatchTracker, WatchTrackerItem } from '../api/types'
import { LOOK_KEY } from './look'
import { setTradingRules } from './tradingRules'
import TradeMindApp from './TradeMindApp'

const store = new Map<string, string>()
beforeAll(() => {
  vi.stubGlobal('localStorage', {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
    clear: () => store.clear(),
  })
  vi.stubGlobal('window', {
    localStorage: globalThis.localStorage,
    location: { search: '' },
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => true,
  })
})
beforeEach(() => store.clear())

const SERVED: TradingRulesDto = {
  research: {
    version: 'hz-rules-v1',
    sha256: 'x',
    horizons: [{ horizon: 5, target_pct: 0.02, stop_pct: 0.04, half_out_pct: null, max_sessions: 5, research_only: false }],
  },
  risk_limits: { max_drawdown_pct: 0.15 },
  brain_plan: { target_pct: 0.08, stop_pct: 0.04, half_out_pct: 0.05, max_sessions: 15 },
  trial: { start: '2026-10-14', min_sessions: 15, sessions_so_far: 0 },
  calendar: { holidays: [] },
}
// Values nobody would hard-code: 9% target, 3% stop, half at 6%, 12 sessions.
const CHANGED: TradingRulesDto = { ...SERVED, brain_plan: { target_pct: 0.09, stop_pct: 0.03, half_out_pct: 0.06, max_sessions: 12 } }

afterEach(() => setTradingRules(SERVED))

const item = (symbol: string): WatchTrackerItem => ({
  symbol, name: `${symbol} Ltd`, added_at: '2026-10-28T05:00:00Z', note: null, buy_price: 4210, bought_on: '2026-10-28', quantity: 10, invested: 42100,
  profit_amount: 3020, entry_price: 4210, entry_source: 'your_price', last_price: 4512, return_pct: 7.2, today_pct: 0.7, days_done: 9,
  score_today: 92, score_prev: 90, score_delta: 2, score_first: 84,
  scores: [84, 92].map((score, i) => ({ date: `2026-10-${28 + i}`, score })),
  closes: [4210, 4512].map((close, i) => ({ date: `2026-10-${28 + i}`, close })), state: 'target',
})
// The tracker's own window comes from the tracker response, not from the plan.
const tracker = (days: number): WatchTracker => ({ as_of: '2026-11-07', horizon_days: days, items: [item('KEI')] })

function render(path: string, owner: boolean, days = 15): string {
  store.set(LOOK_KEY, 'new')
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  client.setQueryData(['plan'], { can_see_real_account: false, unrestricted: owner, can_manage_plans: owner, features: ['trademind'] })
  client.setQueryData(['myWatchlistTracker'], tracker(days))
  return renderToString(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <TradeMindApp ownerConsole={owner} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}
const text = (html: string) =>
  html.replace(/<!-- -->/g, '').replace(/<[^>]+>/g, ' ').replace(/&#x27;|&apos;/g, "'").replace(/&amp;/g, '&').replace(/\s+/g, ' ')

describe('#416 screens show the served rule numbers', () => {
  it('Groww Tracker: the served plan, then a changed plan', () => {
    const a = text(render('/trademind/groww-tracker', false))
    expect(a).toContain("The app's 15-day plan")
    expect(a).toContain('+8% target, −4% stop, sell half at +5%, and be out within 15 trading days')
    expect(a).toContain('₹4,042 (−4%) / ₹4,547 (+8%)')
    setTradingRules(CHANGED)
    const b = text(render('/trademind/groww-tracker', false, 12))
    expect(b).toContain("The app's 12-day plan")
    expect(b).toContain('+9% target, −3% stop, sell half at +6%, and be out within 12 trading days')
    expect(b).toContain('₹4,084 (−3%) / ₹4,589 (+9%)')
    expect(b).not.toContain('+8% target')
  })

  it('Today: the window named in the page text follows the served plan', () => {
    const a = text(render('/trademind', false))
    expect(a).toContain('15-day')
    setTradingRules(CHANGED)
    const b = text(render('/trademind', false))
    expect(b).toContain('12-day')
    expect(b).not.toContain('15-day')
  })

  it('Portfolio: the rules every trade follows come from the served plan and drawdown limit', () => {
    const a = text(render('/trademind/portfolio', false))
    expect(a).toContain('Sell half at +5%, the rest at the +8% target')
    expect(a).toContain('Sell within 15 trading days')
    expect(a).toContain('Stop all new buys if the account falls 15% from its peak')
    setTradingRules({ ...CHANGED, risk_limits: { max_drawdown_pct: 0.2 } })
    const b = text(render('/trademind/portfolio', false))
    expect(b).toContain('Sell half at +6%, the rest at the +9% target')
    expect(b).toContain('Sell within 12 trading days')
    expect(b).toContain('Stop all new buys if the account falls 20% from its peak')
    expect(b).not.toContain('+8% target')
  })
})
