// fx8 (Beginner Wave 2): the bx blocks appear where they were wired (BottomBar is not wired yet), only for the accounts the server answers,
// and the brain trial stays a count. Pages are rendered with their data already in the query cache (no network).
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToString } from 'react-dom/server'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeAll, describe, expect, it, vi } from 'vitest'

import type { BrainDecision, BrainRun } from '../../api/types'
import TradeMindApp from '../TradeMindApp'
import Portfolio from '../pages/Portfolio'
import Records from '../pages/Records'
import StockDetail from '../pages/StockDetail'
import MoneyAtStake from './MoneyAtStake'
import { StockSearchView } from './StockSearch'
import type { EventItem, EvidenceSummary, StockBriefData } from './types'

beforeAll(() => {
  const store = new Map<string, string>()
  vi.stubGlobal('localStorage', {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
    clear: () => store.clear(),
  })
})

const idea: BrainDecision = {
  id: 7, run_id: 'r1', symbol: 'INFY', kind: 'idea', word: 'TRADE', reasons: ['Strong trend'], entry_low: 100,
  entry_high: 102, target: 110, stop: 97, qty: 10, horizon_days: 15, confidence: 0.81, honest_score: null,
  evidence_text: null, downgraded_from: null, downgrade_reason: null, overruled_word: null, overrule_reason: null,
  overruled_by: null, overruled_at: null,
} as BrainDecision

const run = {
  run_id: 'r1', kind: 'nightly', as_of: '2026-10-21', live: true, ms: 1, error: null, counts: {}, status: 'done',
  started_at: '2026-10-21T10:20:00Z', banner: { mode: 'NORMAL', headline: null }, book: 'bot', modules: {},
  quality: { overall: null, stale: [] }, sectors: [], situations: [], portfolio: {}, decisions: [idea],
} as unknown as BrainRun

const ok = (answer: string) => ({ answer, available: true, why: null })

const brief: StockBriefData = {
  symbol: 'INFY',
  as_of: '2026-10-21T10:20:00+00:00',
  q1_company: { ...ok('Infosys · IT sector · Large size'), name: 'Infosys' },
  q2_brain: { ...ok('TRADE: Strong trend'), word: 'TRADE', decision: idea },
  q3_plan: {
    ...ok('Buy between 100 and 102'),
    buy_zone: [100, 102],
    sell_half_price: 106.05,
    sell_half_pct: 0.05,
    target: 110,
    stop: 97,
    last_exit_day: '2026-11-11',
  },
  q4_money: {
    ...ok('About ₹1,010 in'),
    invested: 1010,
    loss_if_stop: 47.5,
    gain_if_target: 81.25,
    gain_if_half_out: 62.4,
    charges_round_trip: 18.3,
  },
  q5_events: {
    ...ok('Results on Mon 26 Oct (3 trading days away)'),
    events: [
      { symbol: 'INFY', kind: 'results', date: '2026-10-26', trading_days_away: 3, detail: '', plain: 'Results on Mon 26 Oct (3 trading days away)' },
    ],
  },
  q6_evidence: { ...ok('Not proven'), claim: 'model_ranking_predictive', claim_label: 'x' },
}

const evidence: EvidenceSummary = {
  paper_label: 'Practice money (paper)',
  bot: {
    since: '2026-09-28', profit_booked: -1234.5, profit_open: 200, costs_paid: 90, worst_fall_from_peak_pct: 3.2,
    finished_trades: 4, win_rate_pct: 50, nifty_same_period_pct: 1.1, every_stock_same_period_pct: 0.4,
    enough_trades: false, note: 'Too few finished trades to judge yet.',
  },
  brain_trial: { since: '2026-10-14', finished: 6, needed: 30, sealed: true, sealed_note: 'Sealed until the trial review: counts only.' },
}

const heldEvents: EventItem[] = [
  { symbol: 'TCS', kind: 'results', date: '2026-10-27', trading_days_away: 4, detail: '', plain: 'Results on Tue 27 Oct (4 trading days away)' },
]

type Who = 'owner' | 'tester' | 'member'
const PLAN: Record<Who, object> = {
  owner: { can_manage_plans: true, unrestricted: true, can_see_real_account: true, features: [] },
  tester: { can_manage_plans: false, unrestricted: true, can_see_real_account: false, features: [] },
  member: { can_manage_plans: false, unrestricted: false, can_see_real_account: false, features: ['trademind'] },
}

function client(who: Who) {
  const c = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  c.setQueryData(['plan'], PLAN[who])
  c.setQueryData(['brainLatest', 'nightly'], run)
  c.setQueryData(['beginner', 'stock', 'INFY'], brief)
  c.setQueryData(['beginner', 'evidence'], evidence)
  c.setQueryData(['beginner', 'events', 'held', null], heldEvents)
  return c
}

const text = (html: string) =>
  html.replace(/<!-- -->/g, '').replace(/<[^>]+>/g, ' ').replace(/&#x27;|&apos;/g, "'").replace(/\s+/g, ' ')

function page(who: Who, el: React.ReactElement, path = '/trademind/x', route = '/trademind/x') {
  return renderToString(
    <QueryClientProvider client={client(who)}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path={route} element={el} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const stockPage = (who: Who) => page(who, <StockDetail />, '/trademind/stock/INFY', '/trademind/stock/:symbol')

describe('stock page: six plain questions, ₹ at stake and what is coming up (bx1, bx3, bx8)', () => {
  it('shows the brief with money and events to the owner', () => {
    const html = stockPage('owner')
    const t = text(html)
    expect(html).toContain('data-testid="stock-brief"')
    expect(t).toContain('What is this company?')
    expect(t).toContain('How much money is at stake?')
    expect(t).toContain('If the stop is hit you lose about ₹47.50')
    expect(t).toContain('If half is sold at +5% and the rest at the target')
    expect(t).toContain('Results on Mon 26 Oct (3 trading days away)')
    expect(t).toContain('Last day to be out: 11 Nov 2026')
  })
  it('shows it to a tester (the server answers testers) but not to a member (it would refuse)', () => {
    expect(stockPage('tester')).toContain('data-testid="stock-brief"')
    expect(stockPage('member')).not.toContain('data-testid="stock-brief"')
  })
  it('never prints the model score as a percentage inside the brief', () => {
    const html = stockPage('owner')
    const block = html.slice(html.indexOf('data-testid="stock-brief"'))
    expect(text(block)).not.toMatch(/\b81\s*%/)
  })
})

describe('Records: is it working so far (bx4)', () => {
  it('shows the paper results and only a count for the brain trial to the owner', () => {
    const html = page('owner', <Records />)
    const t = text(html)
    expect(html).toContain('data-testid="evidence-panel"')
    expect(t).toContain('Practice money (paper)')
    expect(t).toContain('Profit booked: −₹1,234.50')
    const brain = t.slice(t.indexOf('Brain trial'))
    expect(brain).toContain('6 of 30 finished')
    expect(brain).toContain('Sealed until the trial review')
    expect(brain).not.toMatch(/%|win rate|profit/i)
  })
  it('is not shown to anyone but the owner (the bot book is the owner’s; the server refuses it)', () => {
    expect(page('tester', <Records />)).not.toContain('data-testid="evidence-panel"')
    expect(page('member', <Records />)).not.toContain('data-testid="evidence-panel"')
  })
})

describe('Paper Overview: what is coming up for held stocks (bx8)', () => {
  it('lists held-stock events for the owner only', () => {
    expect(text(page('owner', <Portfolio />))).toContain('TCS: Results on Tue 27 Oct (4 trading days away)')
    for (const who of ['tester', 'member'] as const) {
      const t = text(page(who, <Portfolio />))
      expect(t).not.toContain('Coming up for the stocks the bot holds')
      expect(t).not.toContain('TCS: Results')
    }
  })
})

function shell(who: Who, path: string) {
  return renderToString(
    <QueryClientProvider client={client(who)}>
      <MemoryRouter initialEntries={[path]}>
        <TradeMindApp ownerConsole={who === 'owner'} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('shell: stock search on every page (bx7); phone bottom bar left unwired', () => {
  const PATHS = ['/trademind', '/trademind/records', '/trademind/portfolio', '/trademind/stock/INFY', '/trademind/learn']
  it.each(PATHS)('owner and tester get the search box at %s', (path) => {
    for (const who of ['owner', 'tester'] as const) {
      expect(shell(who, path)).toContain('aria-label="Search a stock"')
    }
  })
  it('a member gets no search box (the server refuses them the stock list)', () => {
    expect(shell('member', '/trademind')).not.toContain('aria-label="Search a stock"')
  })
  it('the bottom bar is not mounted until the owner decides the phone layout; the top row stays', () => {
    for (const who of ['owner', 'tester', 'member'] as const) {
      const html = shell(who, '/trademind/portfolio')
      expect(html).not.toContain('bx-bottombar')
      expect(html).toContain('data-testid="nav-today"')
    }
  })
})

describe('small display fixes carried from the Wave 1 review', () => {
  it('MoneyAtStake takes the half-out level from the plan, and signs a negative amount before the ₹', () => {
    const money = { available: true, why: null, invested: 1000, loss_if_stop: 40, gain_if_target: 80, gain_if_half_out: -12, charges_round_trip: 5 }
    const withPct = text(renderToString(<MoneyAtStake value={money} halfPct={0.06} />))
    expect(withPct).toContain('If half is sold at +6%')
    expect(withPct).toContain('−₹12.00')
    expect(text(renderToString(<MoneyAtStake value={money} />))).toContain('If half is sold at the first target')
  })
  it('a failed search says so instead of "No stock found"', () => {
    const html = renderToString(<StockSearchView query="INF" results={[]} failed onQuery={() => {}} onPick={() => {}} />)
    expect(html).toContain('Search is not available right now')
    expect(html).not.toContain('No stock found')
  })
})
