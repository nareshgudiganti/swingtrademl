// The research experiment screen (owner-selected 5- and 30-day picks, design rev 3). Shown only to the owner, only
// on the 5- and 30-day horizons, always labelled research and unproven, never "validated", never a buy plan.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToString } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import type { BrainDecision, BrainRun } from '../api/types'
import Dashboard from './pages/Dashboard'
// The Swing Picks code moved to today/SwingPicks.tsx (oa5).
import dashboardSource from './today/SwingPicks.tsx?raw'
import { ResearchExperiment, canStillChange } from './ResearchExperiment'
import type { HorizonId } from './horizons'
import { HORIZONS, horizonById } from './horizons'

const report = {
  protocol: {
    code: 'horizon-v1',
    notional_inr: 100000,
    slippage_bps: 10,
    cutoff_ist: '09:00',
    costs: { brokerage_per_order: 0, tax_bps_buy: 11.9, tax_bps_sell: 10.4, dp_charge_per_sell: 15.93 },
    min_independent_samples: 30,
    earliest_verdict: '2026-12-31',
    label: 'Research, owner-selected, unproven',
  },
  owner_selected_note: 'These picks were chosen by hand.',
  intended_filter: null,
  horizons: [
    {
      horizon: 5, label: 'Research, owner-selected, unproven', verdict: 'Not proven', closed: 2, open: 1, pending: 1,
      data_issues: 1, void: 0, independent_samples: 2, independent_entry_dates: 2, non_overlapping: 1,
      minimum_needed: 30, period: { from: '2026-10-19', to: '2026-10-30' }, mean_net_return: 0.012,
      median_net_return: 0.012, mean_net_return_per_day: 0.0024, mean_excess_vs_nifty: 0.004,
      mean_excess_vs_universe: -0.002, net_return_range_90: [-0.01, 0.03], win_rate: 0.5,
    },
    {
      horizon: 30, label: 'Research, owner-selected, unproven', verdict: 'Not proven', closed: 0, open: 1, pending: 0,
      data_issues: 0, void: 0, independent_samples: 0, independent_entry_dates: 0, non_overlapping: 0,
      minimum_needed: 30, period: { from: null, to: null }, mean_net_return: null, median_net_return: null,
      mean_net_return_per_day: null, mean_excess_vs_nifty: null, mean_excess_vs_universe: null,
      net_return_range_90: null, win_rate: null,
    },
  ],
  rejected_picks: 1,
  limits: ['Daily prices only: slippage is an assumption (0.10% a side), not a measured fill.'],
}

const outcome = (symbol: string, horizon: number, state: string, net: number | null, flags = {}) => ({
  selection_id: symbol.length, symbol, intended_horizon: horizon, horizon, state, entry_session: '2026-10-19',
  exit_session: state === 'closed' ? '2026-10-26' : null, mark_session: state === 'open' ? '2026-10-22' : null,
  entry_price: 100, exit_price: state === 'closed' ? 104 : null, gross_return: net, net_return: net, costs_inr: 120,
  slippage_inr: 200, nifty_return: 0.01, universe_return: 0.02, universe_count: 300, buy_hold_return: net,
  excess_vs_nifty: net == null ? null : net - 0.01, excess_vs_universe: net == null ? null : net - 0.02,
  data_flags: flags, scored_at: '2026-10-26T15:10:00Z',
})

const outcomes = [
  outcome('TCSPICK', 5, 'closed', 0.031),
  outcome('INFYPICK', 5, 'open', -0.004),
  outcome('GAPPICK', 5, 'data_issue', null, { big_gap: { day: '2026-10-21', move: -0.5 } }),
  outcome('LONGPICK', 30, 'open', 0.02),
]

const selections = [
  { id: 9, symbol: 'NOSUCH', intended_horizon: 5, note: null, submitted_at: '2026-10-19T08:10:00+05:30',
    submitted_by: 'sudeeksha', entry_session: '2026-10-19', status: 'rejected',
    reject_reason: 'No NSE stock with this symbol.', supersedes_id: null },
]

function client(owner: boolean) {
  const c = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  c.setQueryData(['plan'], { can_manage_plans: owner, unrestricted: owner, features: [] })
  c.setQueryData(['experiments', 'report'], report)
  c.setQueryData(['experiments', 'outcomes'], outcomes)
  c.setQueryData(['experiments', 'selections'], selections)
  return c
}

const text = (html: string) =>
  html.replace(/<!-- -->/g, '').replace(/<[^>]+>/g, ' ').replace(/&#x27;|&apos;/g, "'").replace(/&amp;/g, '&')
    .replace(/\s+/g, ' ')

function renderSection(id: HorizonId, owner = true) {
  return renderToString(
    <QueryClientProvider client={client(owner)}>
      <ResearchExperiment horizon={horizonById(id)} />
    </QueryClientProvider>,
  )
}

describe('which horizons run a research experiment', () => {
  it('5 and 30 days only', () => {
    expect(HORIZONS.filter((h) => h.experiment).map((h) => h.days)).toEqual([5, 30])
  })
})

describe('ResearchExperiment (owner)', () => {
  const html = renderSection('5d')
  const t = text(html)

  it('says what it is: research, owner-selected, simulated, unproven, not a trading strategy', () => {
    expect(t).toContain('Research, owner-selected, unproven')
    expect(t).toMatch(/simulated/i)
    expect(t).toMatch(/not a trading strategy/i)
    expect(t).not.toMatch(/\bvalidated\b/i)
  })

  it('shows the sample size against the minimum, the verdict and the period', () => {
    expect(t).toContain('Not proven')
    expect(t).toContain('2 of 30')
    expect(t).toContain('19 Oct')
  })

  it('shows returns after costs and against NIFTY and the average stock', () => {
    expect(t).toMatch(/after costs/i)
    expect(t).toContain('+1.2%')
    expect(t).toMatch(/NIFTY/)
    expect(t).toMatch(/average stock/i)
  })

  it('lists only this horizon’s picks, with their state', () => {
    expect(t).toContain('TCSPICK')
    expect(t).toContain('INFYPICK')
    expect(t).not.toContain('LONGPICK')
    expect(t).toMatch(/Closed/)
    expect(t).toMatch(/Running/)
  })

  it('explains a data issue instead of showing a number', () => {
    expect(t).toContain('GAPPICK')
    expect(t).toMatch(/not scored/i)
  })

  it('offers the owner a form to add a pick, with the cutoff rule', () => {
    expect(html).toContain('data-testid="experiment-form"')
    expect(html).toMatch(/name="symbol"/)
    expect(t).toMatch(/09:00/)
  })

  it('shows refused picks with their reason', () => {
    expect(t).toContain('NOSUCH')
    expect(t).toContain('No NSE stock with this symbol.')
  })

  it('never shows a buy plan', () => {
    expect(t).not.toMatch(/target|stop loss|entry zone|buy now/i)
  })

  it('the 30-day section shows only the 30-day pick', () => {
    const t30 = text(renderSection('30d'))
    expect(t30).toContain('LONGPICK')
    expect(t30).not.toContain('TCSPICK')
  })
})

describe('Swing Picks: the research section appears only for the owner, on 5 and 30 days', () => {
  const run = {
    run_id: 'r1', kind: 'nightly', as_of: '2026-10-16', live: true, ms: 1, error: null, counts: {}, status: 'done',
    started_at: '2026-10-16T10:20:00Z', banner: { mode: 'NORMAL', headline: null }, book: 'bot', modules: {},
    quality: { overall: null, stale: [] }, sectors: [], situations: [], portfolio: {},
    decisions: [] as BrainDecision[],
  } as unknown as BrainRun

  function page(h: HorizonId, owner: boolean) {
    const c = client(owner)
    c.setQueryData(['brainLatest', 'nightly'], run)
    return renderToString(
      <QueryClientProvider client={c}>
        <MemoryRouter initialEntries={['/trademind/dashboard']}>
          <Dashboard initialHorizon={h} />
        </MemoryRouter>
      </QueryClientProvider>,
    )
  }

  it('owner on 5 and 30 days: research section and the note that it runs below', () => {
    for (const h of ['5d', '30d'] as const) {
      const html = page(h, true)
      expect(html).toContain('data-testid="research-experiment"')
      expect(text(html)).toMatch(/research experiment is running below/i)
    }
  })

  it('owner on 1 day and 3 months: no research section', () => {
    for (const h of ['1d', '90d'] as const) expect(page(h, true)).not.toContain('data-testid="research-experiment"')
  })

  it('non-owner: never', () => {
    for (const h of ['5d', '30d'] as const) {
      const html = page(h, false)
      expect(html).not.toContain('data-testid="research-experiment"')
      expect(text(html)).not.toMatch(/research experiment is running below/i)
    }
  })
})

describe('review fixes', () => {
  const accepted = (id: number, symbol: string, entry: string, extra = {}) => ({
    id, symbol, intended_horizon: 5, note: 'why', submitted_at: '2026-10-18T10:00:00+05:30',
    submitted_by: 'sudeeksha', entry_session: entry, status: 'accepted', reject_reason: null, supersedes_id: null,
    ...extra,
  })

  function renderWith(sel: unknown[], outs: unknown[] = outcomes, id: HorizonId = '5d') {
    const c = client(true)
    c.setQueryData(['experiments', 'selections'], sel)
    c.setQueryData(['experiments', 'outcomes'], outs)
    return text(
      renderToString(
        <QueryClientProvider client={c}>
          <ResearchExperiment horizon={horizonById(id)} />
        </QueryClientProvider>,
      ),
    )
  }

  it('a recorded pick shows straight away, on both tabs, before the evening scoring', () => {
    const sel = [accepted(21, 'NEWPICK', '2099-01-05')]
    for (const h of ['5d', '30d'] as const) {
      const t = renderWith(sel, [], h)
      expect(t).toContain('NEWPICK')
      expect(t).toMatch(/Recorded, waiting to start/)
      expect(t).not.toMatch(/No picks yet/)
    }
  })

  it('a corrected pick shows once, as the new stock, in the change list and the table', () => {
    const sel = [accepted(31, 'OLDSYM', '2099-01-05'), accepted(32, 'NEWSYM', '2099-01-05', { supersedes_id: 31 })]
    const t = renderWith(sel, [])
    expect(t).not.toContain('OLDSYM')
    expect(t.match(/NEWSYM/g)?.length).toBe(2) // once in "can still be changed", once in the table
  })

  it('the range is labelled rough and unreliable while the sample is small', () => {
    const t = renderWith(selections)
    expect(t).not.toMatch(/Likely range/)
    expect(t).toMatch(/Rough range/)
    expect(t).toMatch(/unreliable until 30/i)
    expect(t).toMatch(/too few samples/i)
  })

  it('says each pick is scored at both windows', () => {
    expect(renderWith(selections)).toMatch(/scored at both 5 and 30 days/i)
  })

  it('a status line is always present for screen readers', () => {
    const c = client(true)
    const html = renderToString(
      <QueryClientProvider client={c}>
        <ResearchExperiment horizon={horizonById('5d')} />
      </QueryClientProvider>,
    )
    expect(html).toMatch(/role="status"[^>]*aria-live="polite"|aria-live="polite"[^>]*role="status"/)
  })
})

describe('canStillChange (09:00 IST on the start day, whatever the browser time zone)', () => {
  // 2026-10-19 08:59 IST = 03:29 UTC; 09:00 IST = 03:30 UTC
  it('before 09:00 IST on the start day: yes', () => {
    expect(canStillChange('2026-10-19', new Date('2026-10-19T03:29:00Z'))).toBe(true)
  })
  it('at 09:00 IST: no', () => {
    expect(canStillChange('2026-10-19', new Date('2026-10-19T03:30:00Z'))).toBe(false)
  })
  it('the day before: yes; the day after: no', () => {
    expect(canStillChange('2026-10-19', new Date('2026-10-18T20:00:00Z'))).toBe(true)
    expect(canStillChange('2026-10-19', new Date('2026-10-20T01:00:00Z'))).toBe(false)
  })
  it('late evening UTC that is already the start day in India: compares in IST', () => {
    // 2026-10-18 20:00 UTC = 2026-10-19 01:30 IST: still before the cutoff
    expect(canStillChange('2026-10-19', new Date('2026-10-18T20:00:00Z'))).toBe(true)
    // 2026-10-19 04:00 UTC = 09:30 IST: too late, even though it is only 04:00 in UTC
    expect(canStillChange('2026-10-19', new Date('2026-10-19T04:00:00Z'))).toBe(false)
  })
  it('no start day: no', () => {
    expect(canStillChange(null, new Date())).toBe(false)
  })
})

describe('switching between the 5- and 30-day tabs starts a fresh form', () => {
  it('the section is keyed by the horizon, so typed text never carries over to the other tab', () => {
    expect(dashboardSource).toMatch(/<ResearchExperiment key=\{active\.id\}/)
  })
})

