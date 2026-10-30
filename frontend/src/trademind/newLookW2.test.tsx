// New look, wave 2: Discover, Portfolio and My Watchlist. The pure helpers say only what the run and the server
// gave, and the routes pick the new pages in the new look while classic stays as it was.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToString } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import type {
  BrainDecision,
  BrainRun,
  CurrentLimits,
  DetailedPosition,
  MyWatchlist,
  PortfolioSummary,
  SystemStatus,
} from '../api/types'
import { discoverCounts, filterIdeas, sectorsIn, whereItStopped, DISCOVER_FOOT } from './discoverRules'
import { LOOK_KEY } from './look'
import { navPages, visibleNav } from './newMenu'
import { heldRows, moneyFigures, moneyRoom, pointsInRange, safetyRules, sectorBars, wordSummary } from './portfolioRules'
import TradeMindApp from './TradeMindApp'
import { isCloseToTrade, NOT_CHECKED, rowsFor, tabCounts, waitingFor, watchRows } from './watchlistRules'

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

let nextId = 1
const dec = (symbol: string, word: string, confidence: number | null, over: Partial<BrainDecision> = {}): BrainDecision =>
  ({
    id: nextId++, run_id: 'r1', symbol, kind: 'idea', word, reasons: [`${symbol} reason`], entry_low: 100,
    entry_high: 102, target: 108, stop: 96, qty: 0, horizon_days: 15, confidence, honest_score: null,
    evidence_text: null, downgraded_from: null, downgrade_reason: null, overruled_word: null, overrule_reason: null,
    overruled_by: null, overruled_at: null, ...over,
  }) as BrainDecision

const GOOD = dec('GOODCO', 'TRADE', 0.9, { reasons: ['Strong trend'] })
const ROOM = dec('ROOMCO', 'WATCH', 0.8, { reasons: ['risk check said no: no room in the account'] })
const LOW = dec('LOWCO', 'WAIT', 0.3, {
  reasons: ['Model score 30% is below the buy level 60%.'],
  what_would_change: [{ key: 'score', text: 'The model score would need to reach the buy level.' }],
})
const BARE = dec('BARECO', 'AVOID', 0.2, { reasons: [] })
const HELD = dec('HELDCO', 'EXIT', 0.4, { kind: 'holding', reasons: ['Fell below its stop at 92%.'] })
const KEPT = dec('KEPTCO', 'HOLD', 0.7, { kind: 'holding', reasons: ['Still rising.'] })

const RUN = {
  run_id: 'r1', kind: 'nightly', as_of: '2026-10-22', live: true, ms: 1, error: null, counts: {}, status: 'done',
  started_at: '2026-10-22T13:20:00Z', banner: { mode: 'DEFENSIVE', headline: 'Weak market today.' }, book: 'bot',
  modules: {}, quality: { overall: null, stale: [] }, sectors: [], situations: [], portfolio: {},
  decisions: [GOOD, ROOM, LOW, BARE, HELD, KEPT],
} as unknown as BrainRun
const IDEAS = [GOOD, ROOM, LOW, BARE]

const LIMITS = {
  portfolio_value: 1_000_000, cash: 900_000, rung_value: 0, max_positions: 6, open_positions: 2, max_position_pct: 0.2,
  min_position_inr: 0, sector_rule: 'pct_cap', sector_cap_pct: 0.25, max_adv_pct: null, scale_out_enabled: true,
  max_share_price_inr: null, allowed_cap_tiers: [], small_cap_budget_pct: null, cash_floor_inr: 0, risk_per_trade_pct: 0.01,
  max_drawdown_pct: 0.15, regime: 'bear', plain_regime: 'Careful market', deployable_fraction: 0.1,
  deployable_ceiling_inr: 100_000, invested_inr: 98_000, room_inr: 2_000,
  sectors: [{ sector: 'IT', value_inr: 40_000, pct_of_portfolio: 0.04 }, { sector: 'Banks', value_inr: 300_000, pct_of_portfolio: 0.3 }],
} as CurrentLimits

const pos = (symbol: string, over: Partial<DetailedPosition> = {}): DetailedPosition =>
  ({
    id: nextId++, symbol, name: null, quantity: 10, entry_price: 100, current_price: 105, invested: 1000,
    current_value: 1050, unrealized_pnl: 50, unrealized_pnl_pct: 0.05, day_pnl: null, stop_loss: 96, take_profit: 108,
    entry_at: '2026-10-20T04:00:00Z', holding_days: 2, strategy_id: 7, strategy_name: 'x', cap_tier: 'large',
    entry_confidence: null, last_confidence: null, horizon_days: 15, action_code: 'hold', action_label: '', ...over,
  }) as DetailedPosition

const SUMMARY = { total_value: 1_000_000, holdings_value: 100_000, cash: 900_000, open_positions: 2 } as PortfolioSummary
const STATUS = { trading_mode: 'paper', live_trading_enabled: false } as SystemStatus

function render(path: string, owner: boolean, seed: (c: QueryClient) => void = () => {}): string {
  store.set(LOOK_KEY, 'new')
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  client.setQueryData(['plan'], { can_see_real_account: owner, unrestricted: owner, features: [] })
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

// ------------------------------------------------------------- Discover --

describe('Discover: where the brain stopped each idea', () => {
  it('a TRADE passed; a room-blocked idea stopped at the safety check; a low score at the model check', () => {
    expect(whereItStopped(GOOD)).toMatchObject({ label: 'Passed', tone: 'pass' })
    expect(whereItStopped(ROOM)).toMatchObject({ label: 'Safety check', step: 6, tone: 'late' })
    expect(whereItStopped(LOW)).toMatchObject({ label: 'Model check', step: 5, tone: 'early' })
  })

  it('says "Not recorded" when nothing stored says why — never a guessed step', () => {
    expect(whereItStopped(BARE)).toMatchObject({ label: 'Not recorded', step: null })
  })

  it('counts every word and filters by word, sector and search', () => {
    expect(discoverCounts(IDEAS)).toEqual({ ALL: 4, TRADE: 1, WATCH: 1, WAIT: 1, AVOID: 1 })
    const sectorOf = { GOODCO: 'IT', ROOMCO: 'Banks', LOWCO: 'IT', BARECO: null }
    expect(filterIdeas(IDEAS, { filter: 'ALL', sector: 'IT', sectorOf }).map((d) => d.symbol)).toEqual(['GOODCO', 'LOWCO'])
    expect(filterIdeas(IDEAS, { filter: 'WATCH' }).map((d) => d.symbol)).toEqual(['ROOMCO'])
    expect(filterIdeas(IDEAS, { filter: 'ALL', query: 'low' }).map((d) => d.symbol)).toEqual(['LOWCO'])
    expect(sectorsIn(IDEAS, sectorOf)).toEqual(['Banks', 'IT'])
    expect(sectorsIn(IDEAS, undefined)).toEqual([]) // no map: the filter is hidden
  })

  it('an owner overrule counts under the final word', () => {
    expect(discoverCounts([dec('X', 'WATCH', 0.5, { overruled_word: 'AVOID' })]).AVOID).toBe(1)
  })

  it('renders the table in the new look: decision, score as a number, reason, where it stopped, AI analysis', () => {
    const html = render('/trademind/opportunities', false)
    expect(html).toContain('data-page="discover-new"')
    expect(html).toContain('data-testid="discover-table"')
    expect(html).toContain('Where it stopped')
    expect(html).toContain('Safety check')
    expect(html).toContain('Passed')
    expect(html).toContain('AI analysis →')
    expect(html).toContain('href="/trademind/stock/GOODCO"')
    expect(html).toContain(DISCOVER_FOOT.slice(0, 40))
    expect(html).not.toMatch(/\d+%\s*chance/i)
    // owner decision 2026-10-28: a TRADE idea is shown to customers as BUY (the stored word stays TRADE)
    expect(html).toMatch(/>\s*BUY\s*</)
    // the raw "30%" model score never shows
    expect(html).not.toContain('30%')
  })

  it('keeps the classic card list one tap away, and the classic look unchanged', () => {
    expect(render('/trademind/opportunities?view=cards', true)).toContain('data-testid="idea-cards"')
    store.set(LOOK_KEY, 'classic')
    const client = new QueryClient()
    client.setQueryData(['brainLatest', 'nightly'], RUN)
    const classic = renderToString(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={['/trademind/opportunities']}>
          <TradeMindApp ownerConsole />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    expect(classic).not.toContain('discover-new')
  })
})

// ------------------------------------------------------------ Portfolio --

describe('Portfolio: money, held stocks, room and the safety net', () => {
  it('money figures come straight from the summary', () => {
    expect(moneyFigures(SUMMARY)).toEqual({ total: 1_000_000, invested: 100_000, cash: 900_000, investedPct: 10, held: 2 })
    expect(moneyFigures({ ...SUMMARY, total_value: 0 }).investedPct).toBeNull()
  })

  it('held rows join positions with tonight’s word; the score change only when two readings exist', () => {
    const trail = [
      { date: '2026-10-21', score: 0.74, band: 'strong' as const, model_version: null },
      { date: '2026-10-22', score: 0.7, band: 'strong' as const, model_version: null },
    ]
    const rows = heldRows([pos('HELDCO', { score_trail: trail }), pos('KEPTCO'), pos('OTHER')], RUN)
    expect(rows.map((r) => [r.symbol, r.word, r.score, r.change])).toEqual([
      ['HELDCO', 'EXIT', 70, -4],
      ['KEPTCO', 'HOLD', null, null],
      ['OTHER', null, null, null],
    ])
    expect(rows[0]!.why).toBe('Fell below its stop at 92%.') // a stop level, not a model score: left as stored
    expect(wordSummary(rows)).toBe('1 HOLD · 1 EXIT')
    // No positions from the server (refused): the brain's holdings alone, no quantities invented.
    expect(heldRows(undefined, RUN).map((r) => [r.symbol, r.position])).toEqual([['HELDCO', null], ['KEPTCO', null]])
  })

  it('money room is the at-most-N%-invested limit, from the server', () => {
    expect(moneyRoom(LIMITS)).toEqual({ limitPct: 10, ceiling: 100_000, invested: 98_000, room: 2_000, regime: 'Careful market', limiting: true })
    expect(moneyRoom(undefined)).toBeNull()
  })

  it('owner: every rule with its live state, including the fall from the peak', () => {
    const rules = safetyRules({ limits: LIMITS, safety: { new_entries_enabled: true } as never, ddPct: 2.14, status: STATUS })
    const byKey = Object.fromEntries(rules.map((r) => [r.key, r]))
    expect(byKey.drawdown).toMatchObject({ state: 'on', detail: 'Now 2.1% below its peak.' })
    expect(byKey.sector!.text).toBe('At most 25% of the account in one sector')
    expect(byKey.careful!.text).toBe('Careful market: at most 10% of the account invested')
    expect(byKey.switch!.state).toBe('on')
    expect(byKey.paper!.state).toBe('on')
    expect(safetyRules({ limits: LIMITS, ddPct: 16 }).find((r) => r.key === 'drawdown')!.state).toBe('paused')
    expect(safetyRules({ limits: { ...LIMITS, scale_out_enabled: false } }).find((r) => r.key === 'half')!.state).toBe('off')
    expect(safetyRules({ limits: { ...LIMITS, sector_rule: 'one_per_sector', sector_cap_pct: null } }).find((r) => r.key === 'sector')!.text).toMatch(/one stock/)
    expect(safetyRules({ status: { ...STATUS, trading_mode: 'live' } as SystemStatus }).find((r) => r.key === 'paper')!.state).toBe('warn')
  })

  it('non-owner: the rules without owner-only numbers or switches', () => {
    const rules = safetyRules({})
    expect(rules.every((r) => r.state === 'every')).toBe(true)
    expect(rules.some((r) => r.key === 'switch')).toBe(false)
    expect(rules.map((r) => `${r.text} ${r.detail ?? ''}`).join(' ')).not.toMatch(/below its peak/)
  })

  it('sector bars against the cap, from the limits or from the positions', () => {
    const bars = sectorBars({ exposures: LIMITS.sectors, capPct: 0.25 })
    expect(bars.map((b) => [b.sector, Math.round(b.pct), Math.round(b.ofCap), b.over])).toEqual([
      ['Banks', 30, 100, true],
      ['IT', 4, 16, false],
    ])
    const fromPositions = sectorBars({ positions: [pos('A', { sector: 'IT', current_value: 50_000 }), pos('B')], total: 1_000_000 })
    expect(fromPositions.map((b) => [b.sector, b.pct])).toEqual([['IT', 5]])
    expect(sectorBars({})).toEqual([])
  })

  it('chart ranges count back from the newest point', () => {
    const pts = ['2026-07-01', '2026-09-30', '2026-10-10', '2026-10-22'].map((date) => ({ date }))
    expect(pointsInRange(pts, '1M').map((p) => p.date)).toEqual(['2026-09-30', '2026-10-10', '2026-10-22'])
    expect(pointsInRange(pts, 'ALL')).toHaveLength(4)
  })

  it('renders for the owner in order: money, needs a decision, held stocks, sectors, room, safety net, chart last', () => {
    const html = render('/trademind/portfolio', true, (c) => {
      c.setQueryData(['summary'], SUMMARY)
      c.setQueryData(['positions'], [pos('HELDCO'), pos('KEPTCO', { sector: 'IT' })])
      c.setQueryData(['riskLimits'], LIMITS)
      c.setQueryData(['status'], STATUS)
    })
    expect(html).toContain('data-page="portfolio-new"')
    const order = ['data-testid="money"', 'data-testid="needs-decision"', 'data-testid="held-table"', 'data-testid="sectors"', 'data-testid="room"', 'data-testid="safety-net"', 'data-testid="value-chart"']
    const at = order.map((k) => html.indexOf(k))
    expect(at.every((i) => i > 0)).toBe(true)
    expect([...at].sort((a, b) => a - b)).toEqual(at)
    expect(html).toMatch(/HELDCO(<!-- -->)? needs a decision./)
    expect(html).toContain('Money room')
    expect(html).toContain('Paper')
    expect(html).not.toMatch(/\d+%\s*chance/i)
  })

  it('a non-owner sees the rules with a note that the account’s own numbers are owner-only', () => {
    const html = render('/trademind/portfolio', false)
    expect(html).toContain('data-testid="safety-net"')
    expect(html).toContain('shown to the owner only')
    expect(html).not.toContain('Money room')
  })

  it('the new Portfolio is first under Portfolio; Bot / Testing / Zerodha stay listed by the same rules', () => {
    const portfolio = visibleNav(true).find((n) => n.id === 'portfolio')!
    expect(navPages(portfolio, true).map((p) => p.to)).toEqual([
      '/trademind/portfolio',
      '/trademind/positions',
      '/trademind/testing',
      '/trademind/manual-test',
      '/trademind/holdings',
    ])
    expect(navPages(portfolio, false, { realAccount: false }).map((p) => p.to)).toEqual(['/trademind/portfolio', '/trademind/positions'])
  })
})

// ------------------------------------------------------------ Watchlist --

const LIST: MyWatchlist = {
  limit: 50,
  items: [
    { symbol: 'ROOMCO', name: 'Room Co', added_at: '2026-10-12T05:00:00Z', removed_at: null, note: null },
    { symbol: 'LOWCO', name: null, added_at: '2026-10-10T05:00:00Z', removed_at: null, note: null },
    { symbol: 'NEWCO', name: null, added_at: '2026-10-09T05:00:00Z', removed_at: null, note: null },
    { symbol: 'GOODCO', name: null, added_at: '2026-10-08T05:00:00Z', removed_at: null, note: null },
    { symbol: 'GONECO', name: null, added_at: '2026-10-01T05:00:00Z', removed_at: '2026-10-20T05:00:00Z', note: null },
  ],
}

describe('My Watchlist: each person’s own list with the brain’s read', () => {
  it('close to a TRADE = a TRADE, or stopped only by the safety check', () => {
    expect(isCloseToTrade(GOOD)).toBe(true)
    expect(isCloseToTrade(ROOM)).toBe(true)
    expect(isCloseToTrade(LOW)).toBe(false)
    expect(isCloseToTrade(null)).toBe(false)
    expect(isCloseToTrade(HELD)).toBe(false)
  })

  it('what it is waiting for: the stored "what would change" line first, else the short reason', () => {
    expect(waitingFor(LOW)).toBe('The model score would need to reach the buy level.')
    expect(waitingFor(ROOM)).toMatch(/safety limits had no room/)
    expect(waitingFor(GOOD)).toMatch(/BUY/)
    expect(waitingFor(null)).toBe(NOT_CHECKED)
  })

  it('tabs: All = on the list, split into Watching and Close to a BUY; Removed apart', () => {
    const rows = watchRows(LIST.items, RUN)
    expect(tabCounts(rows)).toEqual({ all: 4, watching: 2, close: 2, removed: 1 })
    expect(rowsFor(rows, 'close').map((r) => r.item.symbol)).toEqual(['ROOMCO', 'GOODCO'])
    const newco = rows.find((r) => r.item.symbol === 'NEWCO')!
    expect([newco.word, newco.rank, newco.waitingFor]).toEqual([null, null, NOT_CHECKED])
    expect(rows.find((r) => r.item.symbol === 'ROOMCO')!.rank).toEqual({ rank: 2, of: 4 })
  })

  it('without a run, nothing is guessed', () => {
    const rows = watchRows(LIST.items, undefined)
    expect(rows.every((r) => r.word === null && r.rank === null && !r.close)).toBe(true)
  })

  it('renders for a non-owner in the new look, with their own list and remove buttons', () => {
    const html = render('/trademind/watchlist', false, (c) => c.setQueryData(['myWatchlist'], LIST))
    expect(html).toContain('data-page="watchlist-new"')
    expect(html).toContain('data-testid="watch-table"')
    expect(html).toContain('Close to a BUY')
    expect(html).toContain('aria-label="Remove ROOMCO"')
    expect(html).toContain('Not checked')
    expect(html).toContain('does not change which stocks the bot trades')
    expect(html).not.toContain('GONECO') // removed: only under its own tab
    expect(html).toContain('data-testid="nav-watchlist"')
  })

  it('the classic look keeps its owner-only shared watchlist', () => {
    store.set(LOOK_KEY, 'classic')
    const client = new QueryClient()
    const html = renderToString(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={['/trademind/watchlist']}>
          <TradeMindApp ownerConsole={false} />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    expect(html).not.toContain('watchlist-new')
  })
})
