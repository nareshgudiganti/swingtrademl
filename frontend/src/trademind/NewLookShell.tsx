// The new look: a light app with a left sidebar of eight items (owner decisions 2026-10-25, newMenu.ts). It wraps
// the SAME pages and route table as the classic look (useShell + TradeMindRoutes in TradeMindApp.tsx); only the
// frame, Today and the stock page differ. Display only. "Classic look" at the foot of the sidebar switches back
// (see look.ts). On a phone the sidebar becomes a scrolling row at the top.

import type { ReactNode } from 'react'
import { Link, NavLink, useLocation } from 'react-router-dom'

import './newlook.css'
import { logOut } from './AccountMenu'
import StockSearch from './beginner/StockSearch'
import { useLook } from './look'
import { splitLabel } from './menu'
import { activeNav, navPages, visibleNav, type NavId } from './newMenu'
import { OfflineBanner } from './PageState'
import PricesBadge from './PricesBadge'
import TopBarAlerts from './TopBarAlerts'
import { TradeMindRoutes, useShell } from './TradeMindApp'

const svg = (children: ReactNode) => (
  <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {children}
  </svg>
)

const NAV_ICON: Record<NavId, ReactNode> = {
  today: svg(<path d="M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z" />),
  discover: svg(<><circle cx="11" cy="11" r="7" /><path d="M20 20l-4-4" /></>),
  portfolio: svg(<><rect x="3" y="7" width="18" height="13" rx="2" /><path d="M8 7V5h8v2" /></>),
  watchlist: svg(<path d="M12 3l2.8 5.8 6.2.9-4.5 4.4 1 6.3L12 17.5 6.5 20.4l1-6.3L3 9.7l6.2-.9z" />),
  market: svg(<><path d="M3 17l6-6 4 4 8-8" /><path d="M15 7h6v6" /></>),
  evidence: svg(<><path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z" /><path d="M9 12l2 2 4-4" /></>),
  history: svg(<><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>),
  admin: svg(<><path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12" /><circle cx="16" cy="6" r="2" /><circle cx="10" cy="12" r="2" /><circle cx="18" cy="18" r="2" /></>),
}

export default function NewLookShell({ ownerConsole }: { ownerConsole: boolean }) {
  const [, setLook] = useLook()
  const location = useLocation()
  const { canSeeRealAccount, manualTest, seesAll, book, broker, testingOn, showBook, paperButNotPaper, chip } = useShell(ownerConsole)
  const items = visibleNav(ownerConsole)
  const active = activeNav(location.pathname, ownerConsole)
  const opts = { testingOn, realAccount: canSeeRealAccount, manualTest }
  const activePages = navPages(active, ownerConsole, opts)

  return (
    <div className="tm tm-new" data-look="new">
      <aside className="tmn-side" aria-label="Menu">
        <Link to="/trademind" className="tmn-logo">
          <span className="tm-logo-mark" />
          TradeMind
        </Link>
        <span className="tmn-practice" title="Everything here is paper trading">
          Practice · paper money
        </span>
        <nav className="tmn-nav" aria-label="Main menu">
          {items.map((item) => {
            const pages = navPages(item, ownerConsole, opts)
            const open = item.id === active.id
            return (
              <div key={item.id} className={`tmn-sec ${open ? 'open' : ''}`}>
                <Link to={pages[0]!.to} className={`tmn-sec-link ${open ? 'active' : ''}`} data-testid={`nav-${item.id}`}>
                  {NAV_ICON[item.id]}
                  <span>{item.label}</span>
                </Link>
                {open && pages.length > 1 && (
                  <div className="tmn-pages" data-testid="subnav">
                    {pages.map((pg) => {
                      const { text, tag } = splitLabel(pg.label)
                      return (
                        <NavLink key={pg.to} to={pg.to} end={pg.end} className={({ isActive }) => (isActive ? 'active' : '')}>
                          {text}
                          {tag && <span className={`tmn-tag tmn-tag-${tag.toLowerCase()}`}>{tag}</span>}
                        </NavLink>
                      )
                    })}
                  </div>
                )}
              </div>
            )
          })}
        </nav>
        <div className="tmn-side-foot">
          <button
            type="button"
            className="tmn-switch"
            onClick={() => setLook('classic')}
            title="Go back to the classic dark look. Nothing else changes."
            data-testid="look-switch"
          >
            {svg(<path d="M15 18l-6-6 6-6" />)} Classic look
          </button>
          <button type="button" className="tmn-logout" onClick={logOut} title="Log out of this app">
            Log out
          </button>
        </div>
      </aside>

      <div className="tmn-main">
        <header className="tmn-top">
          <h1 className="tmn-title">{activePages.length > 1 ? active.label : (activePages[0]?.label ?? active.label)}</h1>
          {(ownerConsole || seesAll) && <StockSearch />}
          <div className="tmn-top-right">
            <PricesBadge />
            {ownerConsole && broker.data && (
              <Link
                to="/trademind/control"
                className={`tm-zchip tm-zerodha-chip ${broker.data.broker_authenticated ? 'tm-zchip-ok' : ''}`}
                title="Open the control room"
              >
                {broker.data.broker_authenticated ? 'Zerodha connected' : 'Zerodha: not logged in'}
              </Link>
            )}
            {ownerConsole && <TopBarAlerts />}
            <span className={`tm-status-chip ${chip.ok ? 'tm-status-chip-ok' : ''}`} title={chip.title} data-testid="brain-chip">
              {chip.label}
            </span>
          </div>
        </header>
        {book && showBook && (
          <div className={`tm-bookstrip tm-bookstrip-${book.kind}`} data-testid="book-strip" data-book={book.kind}>
            <span className="tm-booktag">{book.kind === 'real' ? 'Real' : 'Paper'}</span>
            <span>
              <strong>{book.name}.</strong> {book.note}
              {paperButNotPaper && (
                <strong className="tm-neg"> Warning: the server is not in paper mode, so these figures may be real money.</strong>
              )}
            </span>
          </div>
        )}
        <OfflineBanner />
        <TradeMindRoutes
          ownerConsole={ownerConsole}
          testingOff={broker.data?.paper_tester_enabled === false}
          realAccount={canSeeRealAccount}
          look="new"
        />
      </div>
    </div>
  )
}
