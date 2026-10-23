// Navigation regression: the TradeMind shell must render, without throwing, at every URL the app serves, for the
// owner and for everyone else, and must put the page in the right section. This is the part of the earlier
// "blank page after moving to a stock" worry that can be checked without a browser: a render that throws leaves a
// blank screen. (Browser clicks are covered by the Phase 1 browser run; see the PR.)
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToString } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { beforeAll, describe, expect, it, vi } from 'vitest'

import TradeMindApp from './TradeMindApp'
import { SECTIONS, findSection } from './menu'

const PATHS = [
  '/trademind',
  ...SECTIONS.flatMap((s) => s.pages.map((p) => p.to)),
  '/trademind/dashboard', // no longer a tab (Today is one page), still routed
  '/trademind/stock/INFY',
  '/trademind/ai/INFY',
  '/trademind/positions/INFY',
  '/trademind/does-not-exist',
]

// The shell reads the sign-in token (usePlan), and these tests run in plain Node, which has no localStorage.
beforeAll(() => {
  const store = new Map<string, string>()
  vi.stubGlobal('localStorage', {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
    clear: () => store.clear(),
  })
})

// realAccount: whether this account may see the real Zerodha account (REAL_ACCOUNT_USERS). By default the owner
// may and nobody else may, which is how prod is set up (sudeeksha).
function render(path: string, ownerConsole: boolean, status?: Record<string, unknown>, realAccount = ownerConsole): string {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  if (status) client.setQueryData(['status'], status)
  client.setQueryData(['plan'], { can_see_real_account: realAccount, unrestricted: ownerConsole, features: [] })
  return renderToString(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <TradeMindApp ownerConsole={ownerConsole} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('the shell renders at every URL', () => {
  for (const owner of [true, false]) {
    it.each([...new Set(PATHS)])(`${owner ? 'owner' : 'non-owner'}: %s`, (path) => {
      const html = render(path, owner)
      expect(html).toContain('tm-nav') // the menu is there, so the screen is not blank
    })
  }

  it('highlights the section the stock page belongs to', () => {
    const html = render('/trademind/stock/INFY', true)
    const active = findSection('/trademind/stock/INFY')!.id
    expect(html).toMatch(new RegExp(`data-testid="nav-${active}"[^>]*class="[^"]*active|class="[^"]*active[^"]*"[^>]*data-testid="nav-${active}"`))
  })

  it('a non-owner never gets the Admin section in the menu', () => {
    expect(render('/trademind/control', false)).not.toContain('nav-admin')
  })
})

describe('Phase 2: Portfolio tabs and the Paper/Real strip', () => {
  const strips = (html: string) => [...html.matchAll(/data-testid="book-strip"[^>]*data-book="(paper|real)"/g)].map((m) => m[1])
  const tabs = (html: string) => {
    const nav = /data-testid="subnav"[\s\S]*?<\/nav>/.exec(html)?.[0] ?? ''
    return [...nav.matchAll(/<a [^>]*>([\s\S]*?)<\/a>/g)].map((m) => m[1]!.replace(/<[^>]+>/g, '').replace(/\s+/g, ' ').trim())
  }

  it.each([
    ['/trademind/positions', 'paper'],
    ['/trademind/positions/INFY', 'paper'],
    ['/trademind/testing', 'paper'],
    ['/trademind/holdings', 'real'],
    ['/trademind/portfolio', 'paper'],
  ])('%s shows exactly one %s indicator', (path, kind) => {
    expect(strips(render(path, true))).toEqual([kind])
  })

  it('shows no indicator outside Portfolio', () => {
    for (const p of ['/trademind', '/trademind/dashboard', '/trademind/control', '/trademind/records']) {
      expect(strips(render(p, true))).toEqual([])
    }
  })

  it('the owner sees the four approved tab names', () => {
    expect(tabs(render('/trademind/positions', true))).toEqual(['Bot (Paper)', 'Testing (Paper)', 'My Zerodha (Real)', 'Paper Overview'])
  })

  it('an owner who is not the real-account user never sees My Zerodha, its tab or its strip', () => {
    expect(tabs(render('/trademind/positions', true, undefined, false))).toEqual(['Bot (Paper)', 'Testing (Paper)', 'Paper Overview'])
    expect(strips(render('/trademind/holdings', true, undefined, false))).toEqual([])
  })

  it('a non-owner sees only the paper tabs, never My Zerodha', () => {
    expect(tabs(render('/trademind/positions', false))).toEqual(['Bot (Paper)', 'Paper Overview'])
  })

  it('hides Testing from the menu when paper testing is off, but the URL still shows its switched-off card', () => {
    const off = { paper_tester_enabled: false, trading_mode: 'paper' }
    expect(tabs(render('/trademind/positions', true, off))).not.toContain('Testing (Paper)')
    const direct = render('/trademind/testing', true, off)
    expect(direct).toContain('Testing is switched off')
    expect(strips(direct)).toEqual(['paper'])
  })

  it('warns when a Paper screen is looking at a server that is not in paper mode', () => {
    const html = render('/trademind/portfolio', true, { paper_tester_enabled: true, trading_mode: 'live' })
    expect(html).toContain('not in paper mode')
    expect(render('/trademind/portfolio', true, { paper_tester_enabled: true, trading_mode: 'paper' })).not.toContain('not in paper mode')
  })

  it('the Overview headline figure names its source', () => {
    expect(render('/trademind/portfolio', true)).toContain('Paper figures')
  })

  it('a non-owner opening My Zerodha or Testing never sees their strip (no Real flash before the redirect)', () => {
    expect(strips(render('/trademind/holdings', false))).toEqual([])
    expect(strips(render('/trademind/testing', false))).toEqual([])
  })

  it('never warns about real money on Testing, which is always paper', () => {
    expect(render('/trademind/testing', true, { paper_tester_enabled: true, trading_mode: 'live' })).not.toContain('not in paper mode')
  })

  it('also warns a non-owner when a Paper screen sees a server not in paper mode', () => {
    expect(render('/trademind/portfolio', false, { trading_mode: 'live' })).toContain('not in paper mode')
  })
})

describe('ux1: the "Prices from ..." badge is in the top bar on every page', () => {
  function renderWithPrices(path: string, ownerConsole: boolean, latest: string | null): string {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    client.setQueryData(['status'], { paper_tester_enabled: true, trading_mode: 'paper' })
    client.setQueryData(['marketSession'], {
      state: 'pre_open', plain: 'Market opens at 9:15 am', trading_day: true, opens_at: null, closes_at: null,
      next_open: '2026-10-20T09:15:00+05:30', next_close: '2026-10-20T15:30:00+05:30',
      last_closed_trading_day: '2026-10-19', today: '2026-10-20',
      recent_closed_trading_days: ['2026-10-19', '2026-10-16', '2026-10-15'], calendar_warning: null,
      latest_candle_date: latest,
    })
    client.setQueryData(['plan'], { can_see_real_account: ownerConsole, unrestricted: ownerConsole, features: [] })
    return renderToString(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[path]}>
          <TradeMindApp ownerConsole={ownerConsole} />
        </MemoryRouter>
      </QueryClientProvider>,
    )
  }

  for (const owner of [true, false]) {
    it.each([...new Set(PATHS)])(`${owner ? 'owner' : 'non-owner'}: %s`, (path) => {
      expect(renderWithPrices(path, owner, '2026-10-19')).toContain('data-testid="prices-badge"')
    })
  }

  it('is plain when fresh and amber when stale', () => {
    const fresh = renderWithPrices('/trademind', false, '2026-10-19')
    expect(fresh).toContain('Prices from yesterday&#x27;s close')
    expect(fresh).not.toContain('tm-asof-stale')
    const stale = renderWithPrices('/trademind', false, '2026-10-15')
    expect(stale).toContain('Prices are 2 days old')
    expect(stale).toContain('tm-asof-stale')
  })
})
