// The TradeMind area: a full-screen app of its own (own top menu, own dark
// glowing theme) mounted at /trademind. The classic app is untouched.

import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, NavLink, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { usePlan } from '../lib/plan'

import './trademind.css'
import { api } from '../api/client'
import { formatDateTime } from '../lib/format'
import { useBrainStatus, useLatestRun } from './live'
import { staleSince } from './stateRules'
import { statusChip } from './statusChip'
import { Card, Icon } from './ui'
import { OfflineBanner } from './PageState'
import { AccountMenuList, logOut } from './AccountMenu'
import PricesBadge from './PricesBadge'
import TopBarAlerts from './TopBarAlerts'
import { Tour } from './Tour'
import Today from './pages/Today'
import NewLookShell from './NewLookShell'
import { useLook, type Look } from './look'
import Market from './pages/Market'
import MarketNew from './pages/MarketNew'
import EvidenceNew from './pages/EvidenceNew'
import HistoryNew from './pages/HistoryNew'
import AdminHome from './pages/AdminHome'
import Opportunities from './pages/Opportunities'
import Watchlist from './pages/Watchlist'
import PaperPositions from './pages/PaperPositions'
import StockAnalysis from './pages/StockAnalysis'
import StockDetail from './pages/StockDetail'
import StockNew from './pages/StockNew'
import DiscoverNew from './pages/DiscoverNew'
import PortfolioNew from './pages/PortfolioNew'
import WatchlistNew from './pages/WatchlistNew'
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
import Invites from './pages/Invites'
import Jobs from './pages/Jobs'
import Alerts from './pages/Alerts'
import PlansManager from '../pages/PlansManager'
import { bookOf } from './books'
import StockSearch from './beginner/StockSearch'
import { ADMIN_SECTION, matches, resolveSection, splitLabel, visiblePages, visibleSections } from './menu'

// The menu lives in ./menu.ts (five sections: Today, Discover, Portfolio, Insights, Admin).

// The brain chip's wording lives in ./statusChip.ts ("Brain: up to date", never "LIVE").

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

/** Both looks: the classic dark top-menu app (default) or the new light sidebar app. Same pages, same API. */
export default function TradeMindApp({ ownerConsole = false }: TradeMindAppProps) {
  const [look] = useLook()
  return look === 'new' ? <NewLookShell ownerConsole={ownerConsole} /> : <ClassicShell ownerConsole={ownerConsole} />
}

/** What both shells show around the pages: the menu for this viewer, the Paper/Real strip, the brain chip. */
export function useShell(ownerConsole: boolean) {
  const status = useBrainStatus()
  const latest = useLatestRun()
  // Only the account named in REAL_ACCOUNT_USERS may see the real Zerodha tab (the server enforces it too).
  // seesAll: the owner, or a tester while plans are off. Stock search reads /instruments, which no plan opens to
  // members, so they do not get the box (the server would refuse it anyway).
  const { canSeeRealAccount, seesAll } = usePlan()
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
  const chip = statusChip(status, {
    runAt: latest.data ? formatDateTime(latest.data.started_at) : null,
    refreshFailing: staleSince(latest) != null,
  })
  return {
    canSeeRealAccount,
    seesAll,
    location,
    book,
    broker,
    sections,
    section,
    testingOn,
    pages,
    showBook,
    paperButNotPaper,
    chip,
  }
}

function ClassicShell({ ownerConsole }: { ownerConsole: boolean }) {
  const [, setLook] = useLook()
  const {
    canSeeRealAccount,
    seesAll,
    location,
    book,
    broker,
    sections,
    section,
    pages,
    showBook,
    paperButNotPaper,
    chip,
  } = useShell(ownerConsole)
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
        {(ownerConsole || seesAll) && <StockSearch />}
        <div className="tm-topbar-right">
          {/* One chip for the market clock and the prices' age (was two). */}
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
          {/* oa8: alerts bell + trading-stage chip, owner only (the server refuses everyone else). */}
          {ownerConsole && <TopBarAlerts />}
          <span className={`tm-status-chip ${chip.ok ? 'tm-status-chip-ok' : ''}`} title={chip.title} data-testid="brain-chip">
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
              {/* The Admin pages, then Log out (moved off the bar for the owner, so the bar stays on one line). */}
              {menuOpen && <AccountMenuList pages={ADMIN_SECTION.pages} onNewLook={() => setLook('new')} />}
            </div>
          ) : (
            <span className="tm-avatar" title="TradeMind Pro">
              <Icon.User />
            </span>
          )}
          {/* The owner switches look from the account menu (the bar is full); everyone else from the bar. */}
          {!ownerConsole && (
            <button
              type="button"
              className="tm-look-switch"
              title="Switch to the new light look. You can switch back at any time; nothing else changes."
              onClick={() => setLook('new')}
              data-testid="look-switch"
            >
              New look
            </button>
          )}
          <Tour realAccount={ownerConsole && canSeeRealAccount} />
          {!ownerConsole && (
            <button type="button" className="tm-logout" title="Log out of this app" onClick={logOut}>
              Log out
            </button>
          )}
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

      <TradeMindRoutes ownerConsole={ownerConsole} testingOff={broker.data?.paper_tester_enabled === false} realAccount={canSeeRealAccount} look="classic" />
    </div>
  )
}

/** The page routes, shared by both looks. Only Today differs: the new look opens the answer-first Today. */
export function TradeMindRoutes({
  ownerConsole,
  testingOff,
  realAccount,
  look,
}: {
  ownerConsole: boolean
  /** Paper testing switched off on the server (PAPER_TESTER_ENABLED). */
  testingOff: boolean
  /** This account may see the real Zerodha account (REAL_ACCOUNT_USERS). */
  realAccount: boolean
  look: Look
}) {
  return (
    <>
    {/* Rendered outside any parent <Route>, so the paths are anchored here. */}
    <Routes>
      <Route path="/trademind">
        {/* oa5: one Today page (the old Home + Swing Picks). /trademind/dashboard keeps working: Today at the pick list. */}
        <Route index element={<Today owner={ownerConsole} answerFirst={look === 'new'} />} />
        <Route path="dashboard" element={<Today owner={ownerConsole} focus="picks" />} />
        <Route path="market" element={look === 'new' ? <MarketNew /> : <Market />} />
        <Route path="opportunities" element={look === 'new' ? <DiscoverNew /> : <Opportunities />} />
        {/* New look: everyone's own list (/me/watchlist). Classic: the owner's shared watchlist, unchanged. */}
        <Route
          path="watchlist"
          element={look === 'new' ? <WatchlistNew /> : ownerConsole ? <Watchlist /> : <Navigate to="/trademind/opportunities" replace />}
        />
        <Route path="stock/:symbol" element={look === 'new' ? <StockNew /> : <StockDetail />} />
        <Route
          path="stock/:symbol/analysis"
          element={look === 'new' ? <StockAnalysis /> : <StockDetail />}
        />
        <Route path="portfolio" element={look === 'new' ? <PortfolioNew owner={ownerConsole} /> : <Portfolio />} />
        <Route path="positions" element={<Positions />} />
        <Route path="positions/:symbol" element={<Positions />} />
        <Route
          path="testing"
          element={
            !ownerConsole ? (
              <Navigate to="/trademind/positions" replace />
            ) : testingOff ? (
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
        <Route path="learn" element={look === 'new' ? <EvidenceNew owner={ownerConsole} /> : <Learn />} />
        <Route path="system" element={ownerConsole ? <System /> : <Navigate to="/trademind" replace />} />
        {/* New look only: the Admin home (status + safety switches, read only). Classic goes to Control. */}
        <Route path="admin" element={!ownerConsole ? <Navigate to="/trademind" replace /> : look === 'new' ? <AdminHome /> : <Navigate to="/trademind/control" replace />} />
        <Route path="control" element={ownerConsole ? <Control /> : <Navigate to="/trademind" replace />} />
        <Route path="golive" element={ownerConsole ? <GoLive /> : <Navigate to="/trademind" replace />} />
        <Route path="records" element={look === 'new' ? <HistoryNew owner={ownerConsole} /> : <Records />} />
        <Route path="holdings" element={ownerConsole && realAccount ? <MyHoldings /> : <Navigate to="/trademind/portfolio" replace />} />
        <Route path="setup" element={ownerConsole ? <Setup /> : <Navigate to="/trademind" replace />} />
        <Route path="jobs" element={ownerConsole ? <Jobs /> : <Navigate to="/trademind" replace />} />
        <Route path="invites" element={ownerConsole ? <Invites /> : <Navigate to="/trademind" replace />} />
        <Route path="alerts" element={ownerConsole ? <Alerts /> : <Navigate to="/trademind" replace />} />
        {/* Admin > Plans: the existing Plans manager, unchanged (it keeps its own owner check too). */}
        <Route path="plans" element={ownerConsole ? <div className="tm-page"><PlansManager /></div> : <Navigate to="/trademind" replace />} />
        <Route path="*" element={<Navigate to="/trademind" replace />} />
      </Route>
    </Routes>
    </>
  )
}
