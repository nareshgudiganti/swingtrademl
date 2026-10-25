// The TradeMind menu: five sections (owner-approved 2026-10-16), the pages in each, and which of them only
// the owner may open. Pure data and functions, so it can be tested; TradeMindApp.tsx renders from it.
// The route table in TradeMindApp.tsx is separate and unchanged: this only decides where a page appears
// in the menu and which section is highlighted.

// realAccount: shown only to the account allowed to see the real Zerodha account (REAL_ACCOUNT_USERS).
export type Page = {
  to: string
  label: string
  end?: boolean
  ownerOnly?: boolean
  needsTesting?: boolean
  realAccount?: boolean
}
export type SectionId = 'today' | 'discover' | 'portfolio' | 'insights' | 'admin'
export type Section = { id: SectionId; label: string; pages: Page[]; also?: string[]; ownerOnly?: boolean }

export const SECTIONS: Section[] = [
  {
    id: 'today',
    label: 'Today',
    // One page, so no row of tabs under the bar. oa5 folded Swing Picks into Today; its old tab is gone, but
    // /trademind/dashboard still opens Today at the full pick list (the route is in TradeMindApp.tsx).
    pages: [{ to: '/trademind', label: 'Today', end: true }],
    also: ['/trademind/dashboard'],
  },
  {
    id: 'discover',
    label: 'Discover',
    pages: [
      { to: '/trademind/opportunities', label: 'Opportunities' },
      { to: '/trademind/watchlist', label: 'Watchlist', ownerOnly: true },
      { to: '/trademind/market', label: 'Market' },
      { to: '/trademind/ai', label: 'Why (AI)' },
    ],
    also: ['/trademind/stock'],
  },
  {
    id: 'portfolio',
    label: 'Portfolio',
    pages: [
      { to: '/trademind/positions', label: 'Bot (Paper)' },
      { to: '/trademind/testing', label: 'Testing (Paper)', ownerOnly: true, needsTesting: true },
      { to: '/trademind/holdings', label: 'My Zerodha (Real)', ownerOnly: true, realAccount: true },
      { to: '/trademind/portfolio', label: 'Paper Overview' },
    ],
  },
  {
    id: 'insights',
    label: 'Insights',
    pages: [
      { to: '/trademind/records', label: 'Records' },
      { to: '/trademind/learn', label: 'Learn' },
    ],
  },
  {
    id: 'admin',
    label: 'Admin',
    ownerOnly: true,
    // The new look's Admin status page (/trademind/admin); the classic look sends it on to Control.
    also: ['/trademind/admin'],
    pages: [
      { to: '/trademind/control', label: 'Control' },
      { to: '/trademind/golive', label: 'Go-live' },
      { to: '/trademind/risk', label: 'Risk' },
      { to: '/trademind/system', label: 'System' },
      { to: '/trademind/setup', label: 'Setup' },
      { to: '/trademind/alerts', label: 'Alerts' },
      { to: '/trademind/observatory', label: 'Observatory' },
      { to: '/trademind/jobs', label: 'Jobs' },
      { to: '/trademind/invites', label: 'Invites' },
      { to: '/trademind/plans', label: 'Plans' },
    ],
  },
]

export const ADMIN_SECTION: Section = SECTIONS.find((s) => s.id === 'admin')!

export function matches(path: string, to: string, end?: boolean): boolean {
  return end ? path === to || path === `${to}/` : path === to || path.startsWith(`${to}/`)
}

/** The section a path belongs to, or undefined when no section lists it. */
export function findSection(path: string): Section | undefined {
  return SECTIONS.find(
    (s) => s.pages.some((p) => matches(path, p.to, p.end)) || s.also?.some((a) => matches(path, a)),
  )
}

/** The section to highlight. A non-owner never lands in an owner-only section: they get Today. */
export function resolveSection(path: string, owner: boolean): Section {
  const found = findSection(path)
  if (!found || (found.ownerOnly && !owner)) return SECTIONS[0]!
  return found
}

export function visibleSections(owner: boolean): Section[] {
  return SECTIONS.filter((s) => owner || !s.ownerOnly)
}

/**
 * The pages this viewer sees in the menu. `testingOn: false` (paper testing switched off on the server) hides the
 * Testing tab from the menu only; its URL is still routed and still shows its own "switched off" card.
 * `realAccount: false` (this account is not in REAL_ACCOUNT_USERS) hides the real Zerodha tab, even for an owner.
 */
export function visiblePages(
  section: Section,
  owner: boolean,
  opts: { testingOn?: boolean; realAccount?: boolean } = {},
): Page[] {
  const testingOn = opts.testingOn ?? true
  const realAccount = opts.realAccount ?? true
  return section.pages.filter(
    (p) => (owner || !p.ownerOnly) && (testingOn || !p.needsTesting) && (realAccount || !p.realAccount),
  )
}

/** "My Zerodha (Real)" -> the text and its Paper/Real tag, so the tag can be styled and kept visible on a phone. */
export function splitLabel(label: string): { text: string; tag: 'Paper' | 'Real' | undefined } {
  const m = /^(.*?)\s*\((Paper|Real)\)$/.exec(label)
  return m ? { text: m[1]!, tag: m[2] as 'Paper' | 'Real' } : { text: label, tag: undefined }
}
