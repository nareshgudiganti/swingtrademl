// New look, wave 3: Market, Evidence, History and the Admin home. They say only what the API says, keep the brain's
// trial sealed (counts only), never show a score as a chance, and keep Admin owner-only.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToString } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import type { BrainDecision, BrainRun, DetailedPosition, Trade } from '../api/types'
import { LOOK_KEY } from './look'
import { activeNav, navPages, visibleNav } from './newMenu'
import TradeMindApp from './TradeMindApp'
import {
  adminStatusRows,
  cancelledRow,
  endedText,
  evidenceCounts,
  inPeriod,
  inTab,
  jobsWord,
  learnedLine,
  meansForYou,
  openRow,
  scorecardLockText,
  sectorBar,
  sectorRows,
  tradeRow,
  trialProgress,
  trialSessionsSoFar,
} from './wave3Rules'

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
beforeEach(() => {
  store.clear()
  store.set(LOOK_KEY, 'new')
})

let nextId = 1
const dec = (symbol: string, word: string, confidence: number, over: Partial<BrainDecision> = {}): BrainDecision =>
  ({
    id: nextId++, run_id: 'r1', symbol, kind: 'idea', word, reasons: [`${symbol} reason`], entry_low: 100,
    entry_high: 102, target: 108, stop: 96, qty: 0, horizon_days: 15, confidence, honest_score: null,
    evidence_text: null, downgraded_from: null, downgrade_reason: null, overruled_word: null, overrule_reason: null,
    overruled_by: null, overruled_at: null, ...over,
  }) as BrainDecision

const RUN = {
  run_id: 'r1', kind: 'nightly', as_of: '2026-10-23', live: true, ms: 1, error: null, counts: {}, status: 'done',
  started_at: '2026-10-23T13:20:00Z', banner: { mode: 'DEFENSIVE', headline: 'Weak market today.' }, book: 'bot',
  modules: {}, quality: { overall: null, stale: [] }, situations: [], portfolio: {},
  sectors: [
    { sector: 'it', name: 'IT', rank: 3, of_total: 3, strength_20d: -0.008, rotation: 'weakening' },
    { sector: 'energy', name: 'Energy', rank: 1, of_total: 3, strength_20d: 0.044, rotation: 'leading' },
    { sector: 'metal', name: 'Metals', rank: 2, of_total: 3, strength_20d: null, rotation: 'unknown' },
  ],
  decisions: [
    dec('GOOD', 'TRADE', 0.9, { reasons: ['Strong trend'] }),
    dec('ROOM', 'WAIT', 0.7, { reasons: ['risk check said no: no room in the account'] }),
    dec('LOW', 'WAIT', 0.3, { reasons: ['Model score 30% is below the buy level 60%.'] }),
    dec('HELD', 'HOLD', 0.5, { kind: 'holding', reasons: ['On plan.'] }),
  ],
} as unknown as BrainRun

const trade = (over: Partial<Trade> = {}): Trade =>
  ({
    id: nextId++, symbol: 'INFY', mode: 'paper', quantity: 10, entry_price: 1410, exit_price: 1522.8,
    entry_at: '2026-10-05T04:00:00Z', exit_at: '2026-10-15T09:00:00Z', holding_days: 8, gross_pnl: 1128, charges: 20,
    net_pnl: 1108, return_pct: 0.0786, exit_reason: 'TARGET_HIT', exit_reason_label: 'Target reached', is_win: true,
    stop_loss: 1353, take_profit: 1523, entry_confidence: 0.7, last_confidence: 0.7, strategy_name: 'ml_swing_main',
    cap_tier: 'large', price_5d_after_exit: null, return_5d_after_exit: null, price_15d_after_exit: null,
    return_15d_after_exit: null, ...over,
  }) as Trade

const position = (over: Partial<DetailedPosition> = {}): DetailedPosition =>
  ({ id: nextId++, symbol: 'RELIANCE', entry_price: 2398, entry_at: '2026-10-22T04:00:00Z', strategy_name: 'ml_swing_main', day_number: 3, trade_limit_days: 15, ...over }) as DetailedPosition

function render(path: string, owner: boolean, seed: (c: QueryClient) => void = () => {}): string {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  client.setQueryData(['plan'], { can_see_real_account: owner, unrestricted: owner, can_manage_plans: owner, features: [] })
  client.setQueryData(['brainLatest', 'nightly'], RUN)
  seed(client)
  return renderToString(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <TradeMindApp ownerConsole={owner} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const noChance = (html: string) => expect(html).not.toMatch(/\d+\s*%\s*chance/i)

// ------------------------------------------------------------------ market --

describe('Market (new look)', () => {
  it('answers with the mode, highlights its rung, and leaves out what no data states', () => {
    const html = render('/trademind/market', false, (c) =>
      c.setQueryData(['riskLimits'], { deployable_fraction: 0.1 }),
    )
    expect(html).toContain('data-page="market-new"')
    expect(html).toContain('Careful · now')
    expect(html).toContain('Half')
    expect(html).toContain('At most 10% of the account can be invested right now')
    expect(html).not.toContain('back to Normal') // no stored condition: never guessed
    expect(html.indexOf('Energy')).toBeLessThan(html.indexOf('>IT<'))
    noChance(html)
  })

  it('the classic Market stays the default look', () => {
    store.set(LOOK_KEY, 'classic')
    expect(render('/trademind/market', false)).not.toContain('data-page="market-new"')
  })

  it('rules: checklist from the mode, sectors strongest first, bars from the centre', () => {
    expect(meansForYou('DEFENSIVE', null).join(' ')).toMatch(/half the normal size/)
    expect(meansForYou('DEFENSIVE', null).join(' ')).not.toMatch(/invested/)
    expect(meansForYou('NO_NEW_TRADES', 12.4)[0]).toMatch(/No new buys/)
    expect(meansForYou('NO_NEW_TRADES', 12.4).join(' ')).toContain('At most 12%')
    expect(sectorRows(RUN.sectors).map((s) => s.name)).toEqual(['Energy', 'IT', 'Metals'])
    expect(sectorBar(4.4, 4.4)).toEqual({ left: 50, width: 50 })
    expect(sectorBar(-2.2, 4.4)).toEqual({ left: 25, width: 25 })
  })
})

// ---------------------------------------------------------------- evidence --

describe('Evidence (new look)', () => {
  it('counts trading days from 14 Oct, skipping weekends and 20 Oct', () => {
    expect(trialSessionsSoFar('2026-10-13')).toBe(0)
    expect(trialSessionsSoFar('2026-10-14')).toBe(1)
    expect(trialSessionsSoFar('2026-10-23')).toBe(7) // 14,15,16,19,21,22,23
    expect(trialProgress('2026-10-25').line).toBe('Trading day 7 of 15')
    expect(trialSessionsSoFar('2026-11-04')).toBe(15)
    expect(trialProgress('2026-11-20')).toMatchObject({ day: 15, finished: true })
    expect(scorecardLockText('2026-10-25')).toContain('7 Nov 2026')
  })

  it('counts from the run only: checked, liked by the model, stopped for room', () => {
    expect(evidenceCounts(RUN)).toEqual({ checked: 3, passedModel: 2, stoppedByRoom: 1 })
  })

  it('shows counts and the sealed card, never the trial\'s profit or win rate; non-owner sees no live stage count', () => {
    const html = render('/trademind/learn', false, (c) => {
      c.setQueryData(['status'], { trading_mode: 'paper', live_trading_enabled: false })
      c.setQueryData(['brainLearning'], { n_scored: 0, by_band: [], by_word: [], by_week: [], failures: [], drift: [], drift_lines: [], drift_note: null, note: null, since: null })
      c.setQueryData(['brainProposals'], [])
    })
    expect(html).toContain('data-page="evidence-new"')
    expect(html).toContain('Results are sealed until 7 Nov 2026')
    expect(html).toContain('no profit and no win rate')
    expect(html).toContain('Stocks checked tonight')
    expect(html).toContain('Locked')
    expect(html).toContain('data-testid="road-to-real"')
    expect(html).not.toContain('data-testid="finished-count"')
    expect(html).not.toContain('Observatory (owner only)')
    expect(html).not.toMatch(/win rate[^<]*\d+\s*%/i)
    noChance(html)
  })

  it('the owner sees the live stage and "N of 30 finished"', () => {
    const html = render('/trademind/learn', true, (c) =>
      c.setQueryData(['brainStage'], { stage: 'shadow', plain: '', finished: 4, needed: 30, ready: false, history: [], trial: { word: 'sealed', sessions: 7 } }),
    )
    expect(html).toContain('4 of 30 ideas finished')
    expect(html).toContain('7 nightly brain runs recorded')
    expect(html).toMatch(/aria-current="step"[^>]*>1 · Practice|class="on"[^>]*>1 · Practice/)
  })
})

// ----------------------------------------------------------------- history --

describe('History (new look)', () => {
  it('rows from stored data only: how it ended, result only when finished, brain trial sealed', () => {
    const t = tradeRow(trade(), false)
    expect(t).toMatchObject({ kind: 'paper', ended: 'Target hit · sold 15 Oct', sealed: false })
    expect(t.resultPct).toBeCloseTo(7.86)
    const b = tradeRow(trade({ strategy_name: 'brain', entry_at: '2026-10-16T04:00:00Z' }), false)
    expect(b).toMatchObject({ sealed: true, resultPct: null })
    const o = openRow(position(), false, true)
    expect(o).toMatchObject({ ended: 'Still open · day 3 of 15', resultPct: null, kind: 'paper' })
    expect(tradeRow(trade({ mode: 'live', exit_reason: 'MANUAL' }), true)).toMatchObject({ kind: 'own', ended: expect.stringMatching(/^Sold by you/) })
    expect(endedText('STOP_LOSS_HIT', null, false).text).toBe('Stop hit')
    expect(endedText('TIME_STOP', null, false).text).toMatch(/Time exit/)
    const c = cancelledRow({ id: 1, symbol: 'SBIN', decision_day: '2026-10-08', price: 800, reason: 'TRADE idea', status: 'expired', status_plain: 'Ran out of time' })
    expect(inTab(c, 'cancelled') && !inTab(c, 'bot')).toBe(true)
    expect(inPeriod(t, 'month', '2026-10-25')).toBe(true)
    expect(inPeriod(t, 'month', '2026-11-02')).toBe(false)
  })

  it('renders the table, labels Paper, and Step 8 says sealed proposals wait', () => {
    const html = render('/trademind/records', false, (c) => {
      c.setQueryData(['trades', 1000], [trade()])
      c.setQueryData(['positions'], [position()])
      c.setQueryData(['brainLearning'], { n_scored: 12, sealed: true, n_scored_sealed: 3, by_band: [], by_word: [], by_week: [], failures: [], drift: [], drift_lines: [], drift_note: null, note: null, since: null })
      c.setQueryData(['brainProposals'], [{ id: 1, status: 'open', sealed: true, title: 's', evidence: 's', change: {}, kind: 'k', created_at: '', decided_by: null, decided_at: null, decided_note: null }])
    })
    expect(html).toContain('data-page="history-new"')
    expect(html).toContain('Paper buy')
    expect(html).toContain('Target hit')
    expect(html).toContain('Still open')
    expect(html).toContain('Step 8 · What the brain learned')
    expect(html).toContain('sealed until the trial ends')
    expect(html).toContain('Nothing changes by itself')
    // non-owner: no own-trades or cancelled tabs
    expect(html).not.toContain('history-tab-own')
    expect(html).not.toContain('history-tab-cancelled')
    noChance(html)
  })

  it('the owner with the real account gets My own trades and Cancelled', () => {
    const html = render('/trademind/records', true)
    expect(html).toContain('history-tab-own')
    expect(html).toContain('history-tab-cancelled')
  })

  it('learned line: counts only', () => {
    expect(learnedLine({ n_scored: 1 }, [])).toBe(
      '1 finished idea has been scored against what the brain expected. No suggested changes are waiting. Nothing changes by itself: a change happens only when the owner accepts it.',
    )
    expect(learnedLine(undefined, undefined)).not.toMatch(/%/)
  })
})

// ------------------------------------------------------------------- admin --

describe('Admin home (new look, owner only)', () => {
  it('is the first Admin page for the owner and hidden from everyone else', () => {
    const admin = visibleNav(true).find((n) => n.id === 'admin')!
    expect(navPages(admin, true)[0]!.to).toBe('/trademind/admin')
    expect(visibleNav(false).some((n) => n.id === 'admin')).toBe(false)
    expect(activeNav('/trademind/admin', false).id).toBe('today')
  })

  it('renders the status rows and live switches for the owner', () => {
    const html = render('/trademind/admin', true, (c) => {
      c.setQueryData(['status'], { trading_mode: 'paper', live_trading_enabled: false, broker_authenticated: true, scheduler_running: true, paper_tester_enabled: true })
      c.setQueryData(['safetyState'], { new_entries_enabled: true, exits_enabled: true, halt_reason: null, halted_at: null, halted_by: null })
      c.setQueryData(['riskLimits'], { max_drawdown_pct: 0.15, sector_rule: 'pct_cap', sector_cap_pct: 0.25, deployable_fraction: 0.5 })
      c.setQueryData(['brainStage'], { stage: 'shadow', plain: '', finished: 4, needed: 30, ready: false, history: [] })
      c.setQueryData(['realOrdersStatus'], { enabled: false, max_order_inr: 0, max_day_inr: 0, spent_today_inr: 0, market_open: false, market_text: '', waiting: [] })
    })
    expect(html).toContain('data-page="admin-home"')
    expect(html).toContain('PRACTICE (PAPER)')
    expect(html).toContain('PRACTICE STAGE')
    expect(html).toContain('Stop all new buys if the account falls 15%')
    expect(html).toContain('At most 25% of the account in one sector')
    expect(html).toContain('Buys and sells of my own Zerodha shares')
    expect(html).toContain('href="/trademind/control"')
    expect(html).not.toMatch(/<input[^>]*type="checkbox"/) // no new switches that change behaviour
  })

  it('a non-owner never sees it', () => {
    expect(render('/trademind/admin', false)).not.toContain('data-page="admin-home"')
  })

  it('classic look sends /trademind/admin to Control', () => {
    store.set(LOOK_KEY, 'classic')
    expect(render('/trademind/admin', true)).not.toContain('data-page="admin-home"')
  })

  it('status rows: real orders OFF in paper, unknown when an answer is missing, failed jobs named', () => {
    const rows = adminStatusRows({ status: { trading_mode: 'paper', live_trading_enabled: false, broker_authenticated: false, scheduler_running: true } })
    expect(rows.find((r) => r.id === 'real-orders')).toMatchObject({ value: 'OFF', tone: 'green' })
    expect(rows.find((r) => r.id === 'zerodha')!.value).toBe('NOT LOGGED IN')
    expect(rows.find((r) => r.id === 'prices')!.value).toBe('COULD NOT CHECK')
    expect(adminStatusRows({ status: { trading_mode: 'live', live_trading_enabled: true, broker_authenticated: true, scheduler_running: true } }).find((r) => r.id === 'mode')!.tone).toBe('red')
    const job = (name: string, last_status: 'ok' | 'failed' | null) => ({ id: name, name, about: '', registered: true, schedule: null, next_run: null, last_started_at: null, last_finished_at: null, last_duration_s: null, last_status, last_error_kind: null, running_since: null, last_missed_at: null, last_skipped_at: null })
    expect(jobsWord({ generated_at: '', worker_alive: true, runs_available: true, jobs: [job('Nightly brain', 'failed'), job('Prices', 'ok')] })).toMatchObject({ value: '1 FAILED', tone: 'red' })
    expect(jobsWord({ generated_at: '', worker_alive: false, runs_available: true, jobs: [] }).value).toBe('WORKER STOPPED')
    expect(jobsWord(undefined).value).toBe('COULD NOT CHECK')
  })
})
