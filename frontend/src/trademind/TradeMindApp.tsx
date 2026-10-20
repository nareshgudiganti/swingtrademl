// The TradeMind area: a full-screen app of its own (own top menu, own dark
// glowing theme) mounted at /trademind. The classic app is untouched.

import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, NavLink, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { usePlan } from '../lib/plan'

import './trademind.css'
import { api } from '../api/client'
import { clearToken } from '../api/client'
import { formatDateTime } from '../lib/format'
import { useBrainStatus, useLatestRun, useMarketSession } from './live'
import { Card, Icon } from './ui'
import { OfflineBanner } from './PageState'
import PricesBadge from './PricesBadge'
import Home from './pages/Home'
import Dashboard from './pages/Dashboard'
import Market from './pages/Market'
import Opportunities from './pages/Opportunities'
import Watchlist from './pages/Watchlist'
import PaperPositions from './pages/PaperPositions'
import StockDetail from './pages/StockDetail'
import Portfolio from './pages/Portfolio'
import Positions from './pages/Positions'
import AIDecision from './pages/AIDecision'
import Risk from './pages/Risk'
import Learn from './pages/Learn'
import System from './pages/System'
import Control from './pages/Control'
import GoLive from './pages/GoLive'
import Records from './pages/Records'
import MyHoldings from './pages/MyHoldings'
import Setup from './pages/Setup'
import Observatory from './pages/Observatory'
import Jobs from './pages/Jobs'
import Alerts from './pages/Alerts'
import { bookOf } from './books'
import { ADMIN_SECTION, matches, resolveSection, splitLabel, visiblePages, visibleSections } from './menu'

// The menu lives in ./menu.ts (five sections: Today, Discover, Portfolio, Insights, Admin).

const STATUS_CHIP: Record<ReturnType<typeof useBrainStatus>, { label: string; title: string }> = {
  live: { label: 'Live', title: "Connected to the brain's latest run" },
  'no-run': { label: 'No run yet', title: 'The brain is on but has not run yet.' },
  off: { label: 'Brain off', title: 'The brain is switched off on this server' },
  loading: { label: 'Connecting…', title: 'Checking the connection to the brain' },
  error: { label: 'Error', title: 'Could not reach the brain' },
}

type TradeMindAppProps = {
  /** Owner / full-app account: control room, go-live, Zerodha chip, setup. */
  ownerConsole?: boolean
}

// A tab name with its Paper/Real tag kept visible (as a small pill on a phone, where the text is shortened).
function TabLabel({ label }: { label: string }) {
  const { text, tag } = splitLabel(label)
  if (!tag) return <>{label}</>
  return (
    <>
      {text}{' '}
      <span className={`tm-tabtag tm-tabtag-${tag.toLowerCase()}`}>
        <i>(</i>
        {tag}
        <i>)</i>
      </span>
    </>
  )
}

export default function TradeMindApp({ ownerConsole = false }: TradeMindAppProps) {
  const status = useBrainStatus()
  const latest = useLatestRun()
  // Only the account named in REAL_ACCOUNT_USERS may see the real Zerodha tab (the server enforces it too).
  const { canSeeRealAccount } = usePlan()
  const location = useLocation()
  const book = bookOf(location.pathname)
  // Also read for everyone on a Portfolio screen, so the Paper strip can warn a non-owner if the server is ever not
  // in paper mode. Everything else that uses it stays owner-only (each use checks ownerConsole).
  const broker = useQuery({ queryKey: ['status'], queryFn: api.status, enabled: ownerConsole || book != null })
  const sections = visibleSections(ownerConsole)
  const section = resolveSection(location.pathname, ownerConsole)
  // The row under the bar lists only pages this account can open.
  // Testing is left out of the row while paper testing is off; its URL is still routed (see the testing Route).
  const testingOn = broker.data?.paper_tester_enabled !== false
  const pages = visiblePages(section, ownerConsole, { testingOn, realAccount: canSeeRealAccount })
  // One strip per Portfolio screen this viewer may open (a non-owner on an owner-only URL is being redirected, so
  // no Real strip flashes first). Testing is always paper money, so it never gets the real-money warning.
  const showBook = book != null && visiblePages(section, ownerConsole, { realAccount: canSeeRealAccount }).some((p) => matches(location.pathname, p.to))
  const paperButNotPaper =
    book?.kind === 'paper' &&
    !matches(location.pathname, '/trademind/testing') &&
    broker.data != null &&
    broker.data.trading_mode !== 'paper'
  const [menuOpen, setMenuOpen] = useState(false)
  useEffect(() => setMenuOpen(false), [location.pathname])
  useEffect(() => {
    if (!menuOpen) return
    const close = (e: Event) => {
      if (!(e.target as HTMLElement).closest?.('.tm-menu')) setMenuOpen(false)
    }
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && setMenuOpen(false)
    document.addEventListener('pointerdown', close)
    document.addEventListener('keydown', esc)
    return () => {
      document.removeEventListener('pointerdown', close)
      document.removeEventListener('keydown', esc)
    }
  }, [menuOpen])
  const market = useMarketSession()
  const chip = STATUS_CHIP[status]
  const chipTitle =
    status === 'live' && latest.data ? `From the brain's run on ${formatDateTime(latest.data.started_at)}` : chip.title

  return (
    <div className="tm">
      <header className="tm-topbar">
        <Link to="/trademind" className="tm-logo" style={{ color: 'inherit', textDecoration: 'none' }}>
          <span className="tm-logo-mark" />
          TradeMind
        </Link>
        <nav className="tm-nav" aria-label="Sections">
          {sections.map((sec) => (
            <Link
              key={sec.id}
              to={visiblePages(sec, ownerConsole, { realAccount: canSeeRealAccount })[0]!.to}
              className={sec.id === section.id ? 'active' : ''}
              data-testid={`nav-${sec.id}`}
            >
              {sec.label}
            </Link>
          ))}
        </nav>
        <div className="tm-topbar-right">
          <PricesBadge />
          {market.data && (
            <span
              className={`tm-zchip tm-market-chip ${market.data.state === 'open' ? 'tm-zchip-ok' : ''}`}
              title={market.data.calendar_warning ?? 'Indian stock market (NSE) hours, 9:15 am to 3:30 pm on trading days'}
            >
              {market.data.plain}
            </span>
          )}
          {ownerConsole && broker.data && (
            <Link
              to="/trademind/control"
              className={`tm-zchip ${broker.data.broker_authenticated ? 'tm-zchip-ok' : ''}`}
              title="Open the control room"
            >
              {broker.data.broker_authenticated ? 'Zerodha connected' : 'Zerodha: not logged in'}
            </Link>
          )}
          <span className="tm-status-chip" title={chipTitle}>
            {chip.label}
          </span>
          {ownerConsole ? (
            <div className="tm-menu">
              <button
                className="tm-avatar"
                aria-haspopup="menu"
                aria-expanded={menuOpen}
                title="Your account and settings"
                onClick={() => setMenuOpen((o) => !o)}
              >
                <Icon.User />
              </button>
              {menuOpen && (
                <div className="tm-menu-list" role="menu">
                  {ADMIN_SECTION.pages.map((pg) => (
                    <Link key={pg.to} to={pg.to} role="menuitem">
                      {pg.label}
                    </Link>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <span className="tm-avatar" title="TradeMind Pro">
              <Icon.User />
            </span>
          )}
          <button
            className="tm-logout"
            title="Log out of this app"
            onClick={() => {
              clearToken()
              window.location.assign('/')
            }}
          >
            Log out
          </button>
        </div>
      </header>
      {pages.length > 1 && (
        <nav className="tm-subnav" aria-label={`${section.label} pages`} data-testid="subnav">
          {pages.map((pg) => (
            <NavLink key={pg.to} to={pg.to} end={pg.end} className={({ isActive }) => (isActive ? 'active' : '')}>
              <TabLabel label={pg.label} />
            </NavLink>
          ))}
        </nav>
      )}
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

      {/* Rendered outside any parent <Route>, so the paths are anchored here. */}
      <Routes>
        <Route path="/trademind">
          <Route index element={<Home />} />
          <Route path="dashboard" element={<Dashboard />} />
          <Route path="market" element={<Market />} />
          <Route path="opportunities" element={<Opportunities />} />
          <Route path="watchlist" element={ownerConsole ? <Watchlist /> : <Navigate to="/trademind/opportunities" replace />} />
          <Route path="stock/:symbol" element={<StockDetail />} />
          <Route path="portfolio" element={<Portfolio />} />
          <Route path="positions" element={<Positions />} />
          <Route path="positions/:symbol" element={<Positions />} />
          <Route
            path="testing"
            element={
              !ownerConsole ? (
                <Navigate to="/trademind/positions" replace />
              ) : broker.data?.paper_tester_enabled === false ? (
                <div className="tm-page tm-grid">
                  <Card glow title="Testing is switched off" sub="Paper testing is not turned on for this server.">
                    <p>
                      Nothing is broken. The owner switch for manual paper trades (PAPER_TESTER_ENABLED) is off on the
                      server, so buying here is refused. Your real Positions tab is not affected.
                    </p>
                  </Card>
                </div>
              ) : (
                <PaperPositions />
              )
            }
          />
          <Route path="ai" element={<AIDecision />} />
          <Route path="ai/:symbol" element={<AIDecision />} />
          <Route path="observatory" element={ownerConsole ? <Observatory /> : <Navigate to="/trademind" replace />} />
          <Route path="risk" element={ownerConsole ? <Risk /> : <Navigate to="/trademind" replace />} />
          <Route path="learn" element={<Learn />} />
          <Route path="system" element={ownerConsole ? <System /> : <Navigate to="/trademind" replace />} />
          <Route path="control" element={ownerConsole ? <Control /> : <Navigate to="/trademind" replace />} />
          <Route path="golive" element={ownerConsole ? <GoLive /> : <Navigate to="/trademind" replace />} />
          <Route path="records" element={<Records />} />
          <Route path="holdings" element={ownerConsole && canSeeRealAccount ? <MyHoldings /> : <Navigate to="/trademind/portfolio" replace />} />
          <Route path="setup" element={ownerConsole ? <Setup /> : <Navigate to="/trademind" replace />} />
          <Route path="jobs" element={ownerConsole ? <Jobs /> : <Navigate to="/trademind" replace />} />
          <Route path="alerts" element={ownerConsole ? <Alerts /> : <Navigate to="/trademind" replace />} />
          <Route path="*" element={<Navigate to="/trademind" replace />} />
        </Route>
      </Routes>
    </div>
  )
}
