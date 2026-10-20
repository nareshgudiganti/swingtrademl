import { describe, expect, it } from 'vitest'

import appSource from './TradeMindApp.tsx?raw'
import { ADMIN_SECTION, SECTIONS, findSection, resolveSection, splitLabel, visiblePages, visibleSections } from './menu'

// Every TradeMind path that existed before the redesign, and the section it now belongs to.
const EXPECTED: Record<string, string> = {
  '/trademind': 'today',
  '/trademind/dashboard': 'today',
  '/trademind/opportunities': 'discover',
  '/trademind/watchlist': 'discover',
  '/trademind/market': 'discover',
  '/trademind/ai': 'discover',
  '/trademind/positions': 'portfolio',
  '/trademind/testing': 'portfolio',
  '/trademind/holdings': 'portfolio',
  '/trademind/portfolio': 'portfolio',
  '/trademind/records': 'insights',
  '/trademind/learn': 'insights',
  '/trademind/control': 'admin',
  '/trademind/golive': 'admin',
  '/trademind/risk': 'admin',
  '/trademind/system': 'admin',
  '/trademind/setup': 'admin',
  '/trademind/observatory': 'admin',
  '/trademind/jobs': 'admin',
  '/trademind/alerts': 'admin',
}
const PARAM_ROUTES: Record<string, string> = {
  '/trademind/stock/INFY': 'discover',
  '/trademind/positions/INFY': 'portfolio',
  '/trademind/ai/INFY': 'discover',
}

describe('the five sections', () => {
  it('are Today, Discover, Portfolio, Insights, Admin, in that order', () => {
    expect(SECTIONS.map((s) => s.label)).toEqual(['Today', 'Discover', 'Portfolio', 'Insights', 'Admin'])
    expect(SECTIONS.map((s) => s.id)).toEqual(['today', 'discover', 'portfolio', 'insights', 'admin'])
  })

  it('show five to the owner and four (no Admin) to anyone else', () => {
    expect(visibleSections(true).map((s) => s.id)).toEqual(['today', 'discover', 'portfolio', 'insights', 'admin'])
    expect(visibleSections(false).map((s) => s.id)).toEqual(['today', 'discover', 'portfolio', 'insights'])
  })

  it('list no page twice', () => {
    const all = SECTIONS.flatMap((s) => s.pages.map((p) => p.to))
    expect(new Set(all).size).toBe(all.length)
    expect(all.every((to) => to.startsWith('/trademind'))).toBe(true)
  })

  it('make Admin the only owner-only section, holding the same pages the avatar menu lists', () => {
    expect(SECTIONS.filter((s) => s.ownerOnly).map((s) => s.id)).toEqual(['admin'])
    expect(ADMIN_SECTION.id).toBe('admin')
  })
})

describe('where every existing page lives', () => {
  it.each(Object.entries(EXPECTED))('%s is in %s', (path, id) => {
    expect(findSection(path)?.id).toBe(id)
    expect(resolveSection(path, true).id).toBe(id)
  })

  it.each(Object.entries(PARAM_ROUTES))('parameter routes resolve to their section: %s', (path, id) => {
    expect(findSection(path)?.id).toBe(id)
  })

  it('does not treat a longer path as a prefix of "/trademind" itself', () => {
    expect(findSection('/trademind/dashboard')?.id).toBe('today')
    expect(findSection('/trademind/nothing-here')).toBeUndefined()
  })

  it('every route in TradeMindApp.tsx belongs to a section', () => {
    const routes = [...appSource.matchAll(/<Route\s+path="([^"]+)"/g)].map((m) => m[1]!)
    const concrete = routes
      .filter((r) => r !== '/trademind' && r !== '*')
      .map((r) => `/trademind/${r.replace(/:[A-Za-z]+/g, 'X')}`)
    concrete.push('/trademind')
    expect(concrete.length).toBeGreaterThan(15) // the route table was actually read
    const orphans = concrete.filter((p) => findSection(p) === undefined)
    expect(orphans).toEqual([])
  })
})

describe('what a non-owner can see', () => {
  const ownerOnlyPaths = ['/trademind/watchlist', '/trademind/testing', '/trademind/holdings', ...SECTIONS.filter((s) => s.ownerOnly).flatMap((s) => s.pages.map((p) => p.to))]

  it('never includes an owner-only section or page', () => {
    for (const sec of visibleSections(false)) {
      expect(sec.ownerOnly).toBeFalsy()
      for (const page of visiblePages(sec, false)) expect(ownerOnlyPaths).not.toContain(page.to)
    }
  })

  it('a non-owner on an admin path resolves to Today, never to the hidden Admin section', () => {
    for (const p of ['/trademind/control', '/trademind/golive', '/trademind/observatory']) {
      expect(resolveSection(p, false).id).toBe('today')
    }
  })

  it("a section's link is its first page visible to this viewer", () => {
    for (const owner of [true, false]) {
      for (const sec of visibleSections(owner)) {
        const first = visiblePages(sec, owner)[0]
        expect(first, `${sec.id} has a visible page for owner=${owner}`).toBeDefined()
        expect(first!.ownerOnly && !owner).toBeFalsy()
      }
    }
  })

  it('keeps the pages a non-owner could open before the redesign', () => {
    const shown = new Set(visibleSections(false).flatMap((s) => visiblePages(s, false).map((p) => p.to)))
    for (const p of ['/trademind', '/trademind/dashboard', '/trademind/opportunities', '/trademind/market', '/trademind/ai', '/trademind/positions', '/trademind/portfolio', '/trademind/records', '/trademind/learn']) {
      expect(shown.has(p), p).toBe(true)
    }
  })
})

describe('owner-only pages are guarded by their route, not only hidden from the menu', () => {
  // The text of each <Route path="..."> element, up to the next <Route path=.
  const blocks = new Map<string, string>()
  const parts = appSource.split(/<Route\s+path="/).slice(1)
  for (const part of parts) blocks.set(part.slice(0, part.indexOf('"')), part)

  const ownerPaths = [...SECTIONS.flatMap((s) => s.pages.map((p) => ({ section: s, page: p })))]
    .filter(({ section, page }) => section.ownerOnly || page.ownerOnly)
    .map(({ page }) => page.to)

  it('read the route table', () => {
    expect(ownerPaths.length).toBeGreaterThanOrEqual(9)
    expect(blocks.size).toBeGreaterThan(15)
  })

  it.each(ownerPaths)('%s redirects a non-owner away', (to) => {
    const key = to.replace('/trademind/', '')
    const block = blocks.get(key)
    expect(block, `no <Route path="${key}"> in TradeMindApp.tsx`).toBeDefined()
    expect(block).toMatch(/ownerConsole/)
    expect(block).toMatch(/<Navigate /)
  })
})

describe('Phase 2: the four Portfolio tabs', () => {
  const portfolio = SECTIONS.find((s) => s.id === 'portfolio')!

  it('use the approved names, in order, on the same URLs', () => {
    expect(portfolio.pages.map((p) => [p.to, p.label])).toEqual([
      ['/trademind/positions', 'Bot (Paper)'],
      ['/trademind/testing', 'Testing (Paper)'],
      ['/trademind/holdings', 'My Zerodha (Real)'],
      ['/trademind/portfolio', 'Paper Overview'],
    ])
  })

  it('keep Testing and My Zerodha owner-only', () => {
    expect(visiblePages(portfolio, false).map((p) => p.to)).toEqual(['/trademind/positions', '/trademind/portfolio'])
  })

  it('hide My Zerodha (Real) from an owner who is not the real-account user', () => {
    expect(visiblePages(portfolio, true, { realAccount: false }).map((p) => p.to)).not.toContain('/trademind/holdings')
    expect(visiblePages(portfolio, true, { realAccount: true }).map((p) => p.to)).toContain('/trademind/holdings')
    expect(visiblePages(portfolio, false, { realAccount: true }).map((p) => p.to)).not.toContain('/trademind/holdings')
  })

  it('hide Testing from the menu when paper testing is off, and only then', () => {
    expect(visiblePages(portfolio, true, { testingOn: false }).map((p) => p.to)).not.toContain('/trademind/testing')
    expect(visiblePages(portfolio, true, { testingOn: true }).map((p) => p.to)).toContain('/trademind/testing')
    expect(visiblePages(portfolio, true).map((p) => p.to)).toContain('/trademind/testing')
  })

  it('still files /trademind/testing under Portfolio when it is hidden (the direct URL keeps working)', () => {
    expect(findSection('/trademind/testing')?.id).toBe('portfolio')
    expect(resolveSection('/trademind/testing', true).id).toBe('portfolio')
  })

  it('splits a tab name into its text and its Paper/Real tag', () => {
    expect(splitLabel('My Zerodha (Real)')).toEqual({ text: 'My Zerodha', tag: 'Real' })
    expect(splitLabel('Bot (Paper)')).toEqual({ text: 'Bot', tag: 'Paper' })
    expect(splitLabel('Paper Overview')).toEqual({ text: 'Paper Overview', tag: undefined })
  })
})
