// The TradeMind menu: five sections (owner-approved 2026-10-16), the pages in each, and which of them only
// the owner may open. Pure data and functions, so it can be tested; TradeMindApp.tsx renders from it.
// The route table in TradeMindApp.tsx is separate and unchanged: this only decides where a page appears
// in the menu and which section is highlighted.

export type Page = { to: string; label: string; end?: boolean; ownerOnly?: boolean }
export type SectionId = 'today' | 'discover' | 'portfolio' | 'insights' | 'admin'
export type Section = { id: SectionId; label: string; pages: Page[]; also?: string[]; ownerOnly?: boolean }

export const SECTIONS: Section[] = [
  {
    id: 'today',
    label: 'Today',
    pages: [
      { to: '/trademind', label: 'Today', end: true },
      { to: '/trademind/dashboard', label: 'Swing Picks' },
    ],
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
      { to: '/trademind/positions', label: 'Positions' },
      { to: '/trademind/testing', label: 'Testing', ownerOnly: true },
      { to: '/trademind/holdings', label: 'My Holdings', ownerOnly: true },
      { to: '/trademind/portfolio', label: 'Overview' },
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
    pages: [
      { to: '/trademind/control', label: 'Control' },
      { to: '/trademind/golive', label: 'Go-live' },
      { to: '/trademind/risk', label: 'Risk' },
      { to: '/trademind/system', label: 'System' },
      { to: '/trademind/setup', label: 'Setup' },
      { to: '/trademind/observatory', label: 'Observatory' },
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

export function visiblePages(section: Section, owner: boolean): Page[] {
  return section.pages.filter((p) => owner || !p.ownerOnly)
}
