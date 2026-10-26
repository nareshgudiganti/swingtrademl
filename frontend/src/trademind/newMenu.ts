// The new look's menu (owner decision 2026-10-25): eight items in a left sidebar instead of the classic five
// sections. Pure data + functions; NewLookShell.tsx renders it. Every link points at a page that already exists,
// so both looks share one route table (TradeMindApp.tsx). Owner-only and real-account rules are the same as the
// classic menu's (menu.ts): this only regroups where a page is listed.

import { ADMIN_SECTION, SECTIONS, matches, type Page } from './menu'

export type NavId = 'today' | 'discover' | 'portfolio' | 'shadow' | 'watchlist' | 'market' | 'evidence' | 'history' | 'admin'
export type NavItem = {
  id: NavId
  label: string
  /** The pages listed under the item when it is open (the first is where the item links to). */
  pages: Page[]
  /** Other paths that belong to this item (a stock page belongs to Discover). */
  also?: string[]
  ownerOnly?: boolean
}

// Wave 2: the new Portfolio screen (/trademind/portfolio) comes first; the Bot / Testing / My Zerodha tabs follow.
const classicPortfolio = SECTIONS.find((s) => s.id === 'portfolio')!.pages
const portfolioPages: Page[] = [
  { to: '/trademind/portfolio', label: 'Overview (Paper)' },
  ...classicPortfolio.filter((p) => p.to !== '/trademind/portfolio'),
]

export const NAV: NavItem[] = [
  { id: 'today', label: 'Today', pages: [{ to: '/trademind', label: 'Today', end: true }], also: ['/trademind/dashboard'] },
  {
    id: 'discover',
    label: 'Discover',
    pages: [{ to: '/trademind/opportunities', label: 'Discover' }],
    also: ['/trademind/stock', '/trademind/ai'],
  },
  { id: 'portfolio', label: 'Portfolio', pages: portfolioPages },
  // Owner only while it is an exploration: every ranked stock followed for 15 days, bought or not.
  { id: 'shadow', label: 'Shadow Test', pages: [{ to: '/trademind/shadow-test', label: 'Shadow Test' }], ownerOnly: true },
  // Wave 2: everyone's own list (/me/watchlist), so the item is no longer owner-only.
  { id: 'watchlist', label: 'Watchlist', pages: [{ to: '/trademind/watchlist', label: 'My Watchlist' }] },
  { id: 'market', label: 'Market', pages: [{ to: '/trademind/market', label: 'Market' }] },
  {
    id: 'evidence',
    label: 'Evidence',
    pages: [
      { to: '/trademind/learn', label: 'Learning & trial' },
      { to: '/trademind/observatory', label: 'Observatory', ownerOnly: true },
    ],
  },
  { id: 'history', label: 'History', pages: [{ to: '/trademind/records', label: 'History' }] },
  // Wave 3: the new look opens Admin on its status page (/trademind/admin); the classic Admin pages follow.
  { id: 'admin', label: 'Admin', pages: [{ to: '/trademind/admin', label: 'Status' }, ...ADMIN_SECTION.pages], ownerOnly: true },
]

function holds(item: NavItem, path: string): boolean {
  return item.pages.some((p) => matches(path, p.to, p.end)) || (item.also ?? []).some((a) => matches(path, a))
}

/** The items this viewer sees. */
export function visibleNav(owner: boolean): NavItem[] {
  return NAV.filter((n) => owner || !n.ownerOnly)
}

/** The item to highlight for a path; Today when no visible item lists it. */
export function activeNav(path: string, owner: boolean): NavItem {
  return visibleNav(owner).find((n) => holds(n, path)) ?? NAV[0]!
}

/** The pages listed under an item for this viewer (same filters as the classic menu). */
export function navPages(
  item: NavItem,
  owner: boolean,
  opts: { testingOn?: boolean; realAccount?: boolean } = {},
): Page[] {
  const testingOn = opts.testingOn ?? true
  const realAccount = opts.realAccount ?? true
  return item.pages.filter(
    (p) => (owner || !p.ownerOnly) && (testingOn || !p.needsTesting) && (realAccount || !p.realAccount),
  )
}
