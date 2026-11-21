// oa5 acceptance: "Everything Home and Dashboard did is reachable (checked against a written feature list)".
// The written list is docs/superpowers/plans/2026-10-23-oa5-today-feature-list.md; ./featureList.ts holds the same
// ids. For each item and each role this checks the item is there for the roles that should have it, and is not
// there for the others (owner-only safety and approvals, real-account-only screens).
import { readFileSync } from 'node:fs'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToString } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import type { BrainDecision, BrainRun } from '../../api/types'
import type { HorizonId } from '../horizons'
import { SECTIONS, matches, visiblePages } from '../menu'
import TradeMindApp from '../TradeMindApp'
import Today from '../pages/Today'
import { FEATURES, type Feature, type FeatureState, type Role } from './featureList'

// Outside the frontend folder, so read from disk rather than imported.
const listDoc = readFileSync(
  new URL('../../../../docs/superpowers/plans/2026-10-23-oa5-today-feature-list.md', import.meta.url),
  'utf8',
)

let nextId = 1
const dec = (symbol: string, word: string, confidence: number, over: Partial<BrainDecision> = {}): BrainDecision =>
  ({
    id: nextId++, run_id: 'r1', symbol, kind: 'idea', word, reasons: [`${symbol} reason`], entry_low: 100,
    entry_high: 102, target: 108, stop: 96, qty: word === 'TRADE' ? 10 : 0, horizon_days: 15, confidence,
    honest_score: null, evidence_text: null, downgraded_from: null, downgrade_reason: null, overruled_word: null,
    overrule_reason: null, overruled_by: null, overruled_at: null, ...over,
  }) as BrainDecision

function makeRun(withTrade: boolean): BrainRun {
  return {
    run_id: 'r1', kind: 'nightly', as_of: '2026-10-22', live: true, ms: 1, error: null, counts: {}, status: 'done',
    started_at: '2026-10-22T13:20:00Z',
    banner: withTrade
      ? { mode: 'NORMAL', headline: 'Steady market headline.' }
      : { mode: 'NO_NEW_TRADES', headline: 'Too risky to buy today.' },
    book: 'bot', modules: {}, quality: { overall: null, stale: [] },
    sectors: [{ sector: 'IT', name: 'IT', strength_20d: 0.04 }],
    situations: [{ scope: 'market', subject: null, label: 'Calm uptrend', is_unknown: false, evidence: ['Breadth is wide.'] }],
    portfolio: {},
    decisions: [
      dec('AAATRADE', withTrade ? 'TRADE' : 'WATCH', 0.81),
      dec('BBBWATCH', 'WATCH', 0.66),
      dec('CCCWAIT', 'WAIT', 0.4),
      dec('HELDFLAG', 'MONITOR', 0.5, { kind: 'holding', reasons: ['Slipped below its 10-day average.'] }),
    ],
  } as unknown as BrainRun
}

const PLAN: Record<Role, Record<string, unknown>> = {
  owner: { plan: 'owner', unrestricted: true, can_manage_plans: true, can_see_real_account: true, features: [] },
  tester: { plan: null, unrestricted: true, can_manage_plans: false, can_see_real_account: false, features: [] },
  member: { plan: 'pro', unrestricted: false, can_manage_plans: false, can_see_real_account: false, features: ['trademind'] },
}
const ROLES: Role[] = ['owner', 'tester', 'member']

/** A cache with every answer Today could ask for, for every role: the page itself must hide what a role may not see. */
function client(role: Role, run: BrainRun, realAccount?: boolean): QueryClient {
  const c = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  c.setQueryData(['brainLatest', 'nightly'], run)
  c.setQueryData(['plan'], { ...PLAN[role], ...(realAccount === undefined ? {} : { can_see_real_account: realAccount }) })
  c.setQueryData(['safetyState'], { new_entries_enabled: true, exits_enabled: true, halt_reason: null, halted_at: null, halted_by: null })
  c.setQueryData(['brainStage'], { stage: 'shadow', plain: 'Practice only.', finished: 1, needed: 30, ready: false, history: [] })
  c.setQueryData(['brainApprovals'], [
    { id: 1, symbol: 'APPRV', decision_day: '2026-10-22', price: 100, stop_loss: 96, take_profit: 108, suggested_qty: 5, reason: 'r', status: 'pending', status_plain: 'Waiting for your OK', decided_by: null, decided_at: null, decided_note: null, position_id: null, result_note: null, created_at: null, valid_until: '2026-10-23T10:00:00Z' },
  ])
  c.setQueryData(['brainProposals'], [
    { id: 1, kind: 'buy_level', title: 'Raise the buy level', evidence: 'e', change: {}, status: 'open', created_at: '2026-10-01', decided_by: null, decided_at: null, decided_note: null },
  ])
  c.setQueryData(['riskLimits'], { max_drawdown_pct: 0.15 })
  c.setQueryData(['equityCurve', 400], [{ date: '2026-10-22', total_value: 1, cash: 1, holdings_value: 0, day_pnl: 0, drawdown_pct: 0.02, open_positions: 0 }])
  c.setQueryData(['strategies'], [])
  return c
}

function renderToday(role: Role, state?: FeatureState): string {
  const horizon: HorizonId | undefined =
    state === 'unavailable-horizon' ? '1d' : state === 'research-horizon' ? '5d' : undefined
  return renderToString(
    <QueryClientProvider client={client(role, makeRun(state !== 'no-trade'))}>
      <MemoryRouter initialEntries={['/trademind']}>
        <Today owner={role === 'owner'} initialHorizon={horizon} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function renderApp(path: string, role: Role, realAccount?: boolean): string {
  return renderToString(
    <QueryClientProvider client={client(role, makeRun(true), realAccount)}>
      <MemoryRouter initialEntries={[path]}>
        <TradeMindApp ownerConsole={role === 'owner'} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

/** Can this role get to `where` from the menu (or, for the stock page, from any idea)? */
function inMenu(where: string, role: Role, realAccount: boolean): boolean {
  const owner = role === 'owner'
  return SECTIONS.some(
    (s) =>
      (owner || !s.ownerOnly) &&
      (visiblePages(s, owner, { realAccount }).some((p) => matches(where, p.to, p.end)) ||
        (s.also ?? []).some((a) => matches(where, a))),
  )
}

const marker = (f: Feature) => `data-feature="${f.id}"`
const onToday = (f: Feature) => f.where === '/trademind'

describe('the written feature list', () => {
  it('lists exactly the ids the test checks, in the same order', () => {
    const docIds = [...listDoc.matchAll(/^\| ([a-z0-9-]+) \| (?:Home|Swing Picks|New|Classic Dashboard) \|/gm)].map((m) => m[1])
    expect(docIds).toEqual(FEATURES.map((f) => f.id))
  })

  it('gives every item at least one role, and real-account items to the owner only', () => {
    for (const f of FEATURES) {
      expect(f.roles.length, f.id).toBeGreaterThan(0)
      if (f.realAccount) expect(f.roles, f.id).toEqual(['owner'])
    }
  })
})

describe.each(ROLES)('reachable for %s', (role) => {
  for (const f of FEATURES.filter(onToday)) {
    const should = f.roles.includes(role)
    it(`${f.id} is ${should ? '' : 'not '}on Today`, () => {
      const html = renderToday(role, f.state)
      if (should) expect(html).toContain(marker(f))
      else expect(html).not.toContain(marker(f))
    })
  }

  // The strategy signals sit on a page every role can open; whether they are drawn is checked by rendering it below.
  const DRAWN_IN_PAGE = new Set(['classic-strategy-signals'])
  for (const f of FEATURES.filter((x) => !onToday(x) && x.id !== 'dashboard-url')) {
    const should = f.roles.includes(role)
    if (!should && DRAWN_IN_PAGE.has(f.id)) continue
    it(`${f.id}: ${f.where} is ${should ? '' : 'not '}in the menu`, () => {
      expect(inMenu(f.where, role, PLAN[role].can_see_real_account as boolean)).toBe(should)
    })
  }

  it('the strategy signals list is drawn on Discover only for accounts that see the whole app', () => {
    const f = FEATURES.find((x) => x.id === 'classic-strategy-signals')!
    const html = renderApp('/trademind/opportunities', role)
    if (f.roles.includes(role)) expect(html).toContain(marker(f))
    else expect(html).not.toContain(marker(f))
  })

  it('/trademind opens Today, and /trademind/dashboard opens Today at the pick list', () => {
    expect(renderApp('/trademind', role)).toContain(marker(FEATURES.find((x) => x.id === 'market-mode')!))
    const dash = renderApp('/trademind/dashboard', role)
    expect(dash).toContain('data-feature="market-mode"')
    expect(dash).toContain('id="picks"')
    expect(dash).toContain('data-focus="picks"')
  })
})

describe('real-account items', () => {
  it('an owner who is not a real-account user cannot reach My Zerodha', () => {
    for (const f of FEATURES.filter((x) => x.realAccount)) expect(inMenu(f.where, 'owner', false)).toBe(false)
  })

  it('Today never shows a real-money figure or button, for any role', () => {
    for (const role of ROLES) {
      const html = renderToday(role)
      expect(html).not.toMatch(/My Zerodha|Real money|real order/i)
      expect(html).not.toContain('/trademind/holdings')
    }
  })
})
