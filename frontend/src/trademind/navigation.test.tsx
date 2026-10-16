// Navigation regression: the TradeMind shell must render, without throwing, at every URL the app serves, for the
// owner and for everyone else, and must put the page in the right section. This is the part of the earlier
// "blank page after moving to a stock" worry that can be checked without a browser: a render that throws leaves a
// blank screen. (Browser clicks are covered by the Phase 1 browser run; see the PR.)
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToString } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import TradeMindApp from './TradeMindApp'
import { SECTIONS, findSection } from './menu'

const PATHS = [
  '/trademind',
  ...SECTIONS.flatMap((s) => s.pages.map((p) => p.to)),
  '/trademind/stock/INFY',
  '/trademind/ai/INFY',
  '/trademind/positions/INFY',
  '/trademind/does-not-exist',
]

function render(path: string, ownerConsole: boolean, status?: Record<string, unknown>): string {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  if (status) client.setQueryData(['status'], status)
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
