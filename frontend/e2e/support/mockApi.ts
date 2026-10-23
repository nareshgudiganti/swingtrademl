// A fake backend for the browser tests. Every request the app makes to /api/v1/... is answered here from the
// JSON files in ../fixtures (paper mode, made-up plain values), so the tests never need a server, a database or
// a Kite login, and can never reach production.
//
// Anything not listed answers 404 {"detail": "..."}, the same way the real API says "nothing here"; screens
// already show their own empty / error state for that. Writes (POST/PUT/PATCH/DELETE) are refused with 403,
// except signing in, so a test can never "place" anything even by accident.

import type { Page, Route } from '@playwright/test'

import adminPlans from '../fixtures/admin-plans.json' with { type: 'json' }
import alertSettings from '../fixtures/alert-settings.json' with { type: 'json' }
import authOptions from '../fixtures/auth-options.json' with { type: 'json' }
import brainAlerts from '../fixtures/brain-alerts.json' with { type: 'json' }
import brainChanges from '../fixtures/brain-changes.json' with { type: 'json' }
import brainHealth from '../fixtures/brain-health.json' with { type: 'json' }
import brainLatestRun from '../fixtures/brain-latest-run.json' with { type: 'json' }
import brainLearning from '../fixtures/brain-learning.json' with { type: 'json' }
import beginnerStockInfy from '../fixtures/beginner-stock-infy.json' with { type: 'json' }
import brainStage from '../fixtures/brain-stage.json' with { type: 'json' }
import marketSession from '../fixtures/market-session.json' with { type: 'json' }
import meMember from '../fixtures/me-member.json' with { type: 'json' }
import meOwner from '../fixtures/me-owner.json' with { type: 'json' }
import meTester from '../fixtures/me-tester.json' with { type: 'json' }
import planMember from '../fixtures/plan-member.json' with { type: 'json' }
import planOwner from '../fixtures/plan-owner.json' with { type: 'json' }
import planTester from '../fixtures/plan-tester.json' with { type: 'json' }
import portfolioSummary from '../fixtures/portfolio-summary.json' with { type: 'json' }
import positions from '../fixtures/positions.json' with { type: 'json' }
import realAccount from '../fixtures/real-account.json' with { type: 'json' }
import realTax from '../fixtures/real-tax.json' with { type: 'json' }
import riskEvents from '../fixtures/risk-events.json' with { type: 'json' }
import riskLimits from '../fixtures/risk-limits.json' with { type: 'json' }
import scoreBands from '../fixtures/score-bands.json' with { type: 'json' }
import safetyState from '../fixtures/safety-state.json' with { type: 'json' }
import status from '../fixtures/status.json' with { type: 'json' }
import strategies from '../fixtures/strategies.json' with { type: 'json' }
import v1Picks from '../fixtures/v1-picks.json' with { type: 'json' }
import strategySignals from '../fixtures/strategy-signals.json' with { type: 'json' }

// tester: sees the whole app while plans are off, but never the owner's private areas (like the real server).
export type Role = 'owner' | 'member' | 'tester'

export const FAKE_TOKEN = 'e2e-fake-token-not-a-real-jwt'
const TOKEN_STORAGE = 'stml.token' // same key as src/api/client.ts
const TOUR_KEY_PREFIX = 'tm.tour.seen.v1:' // same key as tourKey() in src/trademind/tourRules.ts

/** Trading days before 2026-10-16 (weekends skipped), oldest first, stamped IST midnight like real candles. */
function tradingDays(n: number): Date[] {
  const days: Date[] = []
  const d = new Date(Date.UTC(2026, 9, 16))
  while (days.length < n) {
    const wd = d.getUTCDay()
    if (wd !== 0 && wd !== 6) days.unshift(new Date(d.getTime() - 5.5 * 3600_000))
    d.setUTCDate(d.getUTCDate() - 1)
  }
  return days
}

/** Where each made-up price walk ends, close to the levels in the fixtures. */
const LAST_PRICE: Record<string, number> = { INFY: 1490, TCS: 3912, RELIANCE: 1372, HDFCBANK: 1650, ITC: 420 }

/** A gentle made-up price walk ending at LAST_PRICE, the same every run so counts never wobble. */
function candles(symbol: string, n: number) {
  const days = tradingDays(Math.min(Math.max(n, 1), 260))
  const closes: number[] = []
  let price = 1
  for (let i = 0; i < days.length; i++) {
    price *= 1 + Math.sin(i / 3) * 0.008 + 0.001
    closes.push(price)
  }
  const scale = (LAST_PRICE[symbol] ?? 1000) / closes[closes.length - 1]!
  const round = (x: number) => Math.round(x * 100) / 100
  return days.map((day, i) => {
    const close = round(closes[i]! * scale)
    const open = round((closes[i - 1] ?? closes[i]!) * scale)
    return {
      ts: day.toISOString(),
      open,
      high: round(Math.max(open, close) * 1.006),
      low: round(Math.min(open, close) * 0.994),
      close,
      volume: 100_000 + i * 1_000,
    }
  })
}

function equityCurve(n: number) {
  return tradingDays(Math.min(n, 15)).map((day, i) => ({
    date: new Date(day.getTime() + 5.5 * 3600_000).toISOString().slice(0, 10),
    total_value: 979_792 + i * 15,
    cash: 979_792 - (i > 8 ? 21_130 : 0),
    holdings_value: i > 8 ? 21_130 + i * 15 : 0,
    day_pnl: 15,
    drawdown_pct: 0,
    open_positions: i > 8 ? 2 : 0,
  }))
}

function scoreTrail(symbol: string) {
  return {
    symbol,
    score_trail: [
      { date: '2026-10-15', score: 0.62, band: 'strong', model_version: '12' },
      { date: '2026-10-16', score: 0.64, band: 'strong', model_version: '12' },
    ],
    score_band: 'strong',
    last_score: 0.64,
  }
}

/** The Testing book: its own practice money, nothing bought yet. */
const testerSummary = {
  ...portfolioSummary,
  measured_since: '2026-10-15',
  starting_capital: 100_000,
  total_value: 100_000,
  cash: 100_000,
  holdings_value: 0,
  unrealized_pnl: 0,
  total_pnl: 0,
  total_return_pct: 0,
  open_positions: 0,
  day_pnl: 0,
  max_drawdown_pct: 0,
  current_drawdown_pct: 0,
  top_movers: [],
}

type Answer = { status?: number; body: unknown }

/** The password the fake sign-in turns down, to test the "wrong password" message. */
export const WRONG_PASSWORD = 'wrong-password'

function answer(role: Role, method: string, path: string, query: URLSearchParams, body: unknown): Answer | undefined {
  const owner = role === 'owner'
  if (method !== 'GET') {
    if (method === 'POST' && path === '/auth/login') {
      const password = (body as { password?: string } | null)?.password
      if (password === WRONG_PASSWORD) return { status: 401, body: { detail: 'Incorrect username or password' } }
      return { body: { access_token: FAKE_TOKEN } }
    }
    return { status: 403, body: { detail: 'Changes are switched off in browser tests.' } }
  }

  // Signing in and who you are.
  if (path === '/auth/options') return { body: authOptions }
  if (path === '/auth/me') return { body: owner ? meOwner : role === 'tester' ? meTester : meMember }
  if (path === '/me/plan') return { body: owner ? planOwner : role === 'tester' ? planTester : planMember }

  // Account status is owner-only on the real server too.
  if (path === '/status') return owner ? { body: status } : { status: 403, body: { detail: 'Owner only.' } }
  if (path === '/safety/state') return owner ? { body: safetyState } : { status: 403, body: { detail: 'Owner only.' } }
  if (path === '/risk/limits') return { body: riskLimits }
  if (path === '/safety/risk-events') return owner ? { body: riskEvents.slice(0, Number(query.get('limit') ?? 50)) } : { status: 403, body: { detail: 'Owner only.' } }

  // Plans manager (owner only, like the real /admin API).
  const adminPlan: Record<string, unknown> = { '/admin/switch': adminPlans.switch, '/admin/features': adminPlans.features, '/admin/plans': adminPlans.plans, '/admin/users': adminPlans.users }
  if (path in adminPlan) return owner ? { body: adminPlan[path] } : { status: 403, body: { detail: 'Owner only.' } }

  // Brain (practice mode) and the market clock.
  if (path === '/brain/runs/latest') return { body: brainLatestRun }
  if (path === '/brain/health') return { body: brainHealth }
  if (path === '/brain/changes') return { body: brainChanges }
  if (path === '/brain/learning') return { body: brainLearning }
  if (path === '/brain/proposals') return { body: [] }
  if (path === '/brain/observatory/score-bands') return owner ? { body: scoreBands } : { status: 403, body: { detail: 'Owner only.' } }
  if (path === '/brain/episodes') return { body: [] }
  if (path === '/brain/runs') return { body: [] }
  // The stock brief the idea card reads its plan details and rupees at stake from (oa12). INFY is the TRADE.
  if (path === '/beginner/stock/INFY') return { body: beginnerStockInfy }
  if (path === '/brain/stage') return owner ? { body: brainStage } : { status: 403, body: { detail: 'Owner only.' } }
  if (path === '/brain/alerts') return owner ? { body: brainAlerts } : { status: 403, body: { detail: 'Owner only.' } }
  if (path === '/brain/approvals') return owner ? { body: [] } : { status: 403, body: { detail: 'Owner only.' } }
  if (path === '/notifications/telegram/status') return { body: { ok: false, bot: null, error: 'Telegram is not set up on this server.' } }
  if (path === '/notifications/alert-settings') return owner ? { body: alertSettings } : { status: 403, body: { detail: 'Only the owner can do this.' } }
  if (path.startsWith('/brain/track/')) {
    const symbol = decodeURIComponent(path.slice('/brain/track/'.length))
    return { body: { symbol, opened_on: null, points: [], band: [] } }
  }
  if (path === '/market/session') return { body: marketSession }
  if (path === '/strategies') return { body: strategies }
  // A strategy's signals are open to no plan on the real server: the owner and a tester (plans off) only.
  if (path === '/strategies/1/signals') return owner || role === 'tester' ? { body: strategySignals } : { status: 403, body: { detail: 'Not in your plan.' } }

  // Version 1's picks (Records page) and the watchlist, so the model score wording can be checked there (ux10).
  if (path === '/signals/buy-list') return { body: v1Picks.buyList }
  if (path === '/signals/track-record') return { body: v1Picks.trackRecord }
  if (path === '/instruments/watchlist') {
    return {
      body: ['INFY', 'ITC'].map((s, i) => ({
        id: i + 1,
        instrument_token: 1000 + i,
        tradingsymbol: s,
        name: null,
        exchange: 'NSE',
        instrument_type: 'EQ',
        lot_size: 1,
        tick_size: 0.05,
        is_watchlisted: true,
        is_active: true,
      })),
    }
  }

  // Prices and scores.
  if (path.startsWith('/market-data/candles/')) {
    const symbol = decodeURIComponent(path.slice('/market-data/candles/'.length))
    return { body: candles(symbol, Number(query.get('limit') ?? 66)) }
  }
  if (path.startsWith('/ml/score-trail/')) {
    return { body: scoreTrail(decodeURIComponent(path.slice('/ml/score-trail/'.length))) }
  }

  // Portfolio books: bot (paper), tester (paper), real (owner only, empty).
  if (path === '/portfolio/summary') return { body: query.get('book') === 'tester' ? testerSummary : portfolioSummary }
  if (path === '/portfolio/positions/detailed') {
    const book = query.get('book')
    if (book === 'bot' || book === 'all') return { body: positions }
    if (book === 'real' && !owner) return { status: 403, body: { detail: 'Owner only.' } }
    return { body: [] }
  }
  if (path === '/portfolio/health') {
    const book = query.get('book') ?? 'bot'
    if (book === 'real' && !owner) return { status: 403, body: { detail: 'Owner only.' } }
    const labels: Record<string, string> = { bot: 'Bot (Paper)', tester: 'Testing (Paper)', real: 'My Zerodha (Real)' }
    return {
      body: {
        book,
        book_label: labels[book] ?? book,
        is_real_money: book === 'real',
        account_value: 1_000_000,
        account_value_basis: "The bot's account: shares held plus cash left",
        holdings_checked: book === 'bot' ? 1 : 0,
        rules: ['At most 25% of the account in one sector', 'Stop-loss 4% below the price paid'],
        results_checked: true,
        notes: [],
        issues:
          book === 'bot'
            ? [{ kind: 'past_plan', symbols: ['INFY'], title: 'INFY is on day 16 of a 15-day plan.', detail: 'A reminder to review it.' }]
            : [],
        checked_at: '2026-10-20T10:00:00+05:30',
      },
    }
  }
  if (path === '/portfolio/trades') return { body: [] }
  if (path === '/portfolio/equity-curve') return { body: equityCurve(Number(query.get('days') ?? 180)) }
  if (path === '/portfolio/holdings') return owner ? { body: [] } : { status: 403, body: { detail: 'Owner only.' } }
  if (path === '/portfolio/real/account') return owner ? { body: realAccount.account } : undefined
  if (path === '/portfolio/real/orders-status') return owner ? { body: realAccount.ordersStatus } : undefined
  if (path === '/real-report') return owner ? { body: realAccount.report } : undefined
  if (path === '/real-report/tax') return owner ? { body: realTax } : { status: 403, body: { detail: 'This is a private account.' } }

  return undefined
}

export type MockApi = {
  /** Paths the app asked for that this fake backend does not know (answered 404). Useful when adding a page. */
  unmocked: string[]
}

/**
 * Serve the fake backend for this page. With `signedIn`, the browser starts with a (fake) saved sign-in, so the
 * app opens straight into TradeMind; without it, the sign-in screen shows first.
 */
export async function mockApi(page: Page, opts: { role?: Role; signedIn?: boolean; tourSeen?: boolean } = {}): Promise<MockApi> {
  const role = opts.role ?? 'owner'
  const state: MockApi = { unmocked: [] }

  // The first-time tour opens by itself for an account that has not seen it, and would cover every journey.
  // Mark it seen for both fake accounts unless a test is about the tour (tour.spec.ts passes tourSeen: false).
  if (opts.tourSeen ?? true) {
    await page.addInitScript((keys) => keys.forEach((k) => localStorage.setItem(k, '1')), [
      TOUR_KEY_PREFIX + meOwner.username,
      TOUR_KEY_PREFIX + meMember.username,
      TOUR_KEY_PREFIX + meTester.username,
    ])
  }

  if (opts.signedIn ?? true) {
    await page.addInitScript(
      ([key, token]) => {
        // Only on the first load: a test that logs out must stay logged out after the reload.
        if (!sessionStorage.getItem('e2e.seeded')) {
          sessionStorage.setItem('e2e.seeded', '1')
          localStorage.setItem(key!, token!)
        }
      },
      [TOKEN_STORAGE, FAKE_TOKEN],
    )
  }

  // A predicate, not a '**/api/**' glob: the glob would also catch the app's own source files (src/api/...).
  await page.route(
    (url) => url.pathname.startsWith('/api/v1/'),
    async (route: Route) => {
      const req = route.request()
      const url = new URL(req.url())
      const path = url.pathname.slice('/api/v1'.length)
      let body: unknown = null
      try {
        body = req.postDataJSON()
      } catch {
        /* no JSON body */
      }
      const found = answer(role, req.method(), path, url.searchParams, body)
      if (!found) state.unmocked.push(`${req.method()} ${path}`)
      const reply = found ?? { status: 404, body: { detail: 'Not found (not in the browser-test fixtures).' } }
      await route.fulfill({ status: reply.status ?? 200, contentType: 'application/json', body: JSON.stringify(reply.body) })
    },
  )
  return state
}
