// The TradeMind area: a full-screen app of its own (own top menu, own dark
// glowing theme) mounted at /trademind. The classic app is untouched.

import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, NavLink, Navigate, Route, Routes, useLocation } from 'react-router-dom'

import './trademind.css'
import { api } from '../api/client'
import { clearToken } from '../api/client'
import { formatDateTime } from '../lib/format'
import { useBrainStatus, useLatestRun, useMarketSession } from './live'
import { Card, Icon } from './ui'
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

// One final app in five sections (owner-approved design, 2026-10-04): the top
// row is the section, the row under it the pages of that section. Finance and
// Classic view are hidden from the menu for now (owner, 2026-10-04); their
// pages still exist and come back when asked for.
type Page = { to: string; label: string; end?: boolean }
type Section = { label: string; pages: Page[]; also?: string[] }

// The top bar is one flat row (see the TradeMind mockup). A section with several pages shows them in a
// second row; the owner's own pages live in the avatar menu, not in the bar.
const SECTIONS: Section[] = [
  {
    label: 'Dashboard',
    pages: [{ to: '/trademind/dashboard', label: 'Swing Picks' }],
  },
  {
    label: 'Market',
    pages: [{ to: '/trademind/market', label: 'Market' }],
  },
  {
    label: 'Swing Picks',
    pages: [
      { to: '/trademind/opportunities', label: 'Opportunities' },
      { to: '/trademind/watchlist', label: 'Watchlist' },
    ],
    also: ['/trademind/stock'],
  },
  {
    label: 'My Portfolio',
    pages: [
      { to: '/trademind/positions', label: 'Positions' },
      { to: '/trademind/testing', label: 'Testing' },
      { to: '/trademind/holdings', label: 'My Holdings' },
      { to: '/trademind/portfolio', label: 'Overview' },
    ],
  },
  {
    label: 'Analytics',
    pages: [
      { to: '/trademind/records', label: 'Records' },
      { to: '/trademind/learn', label: 'Learn' },
    ],
  },
  {
    label: 'Brain Logs',
    pages: [
      { to: '/trademind', label: 'Decisions', end: true },
      { to: '/trademind/ai', label: 'AI' },
      { to: '/trademind/observatory', label: 'Observatory' },
    ],
  },
]

// Owner only. Reached from the avatar; when one is open, the same pages show in the second row.
const OWNER_SECTION: Section = {
  label: 'Settings',
  pages: [
    { to: '/trademind/control', label: 'Control' },
    { to: '/trademind/golive', label: 'Go-live' },
    { to: '/trademind/risk', label: 'Risk' },
    { to: '/trademind/system', label: 'System' },
    { to: '/trademind/setup', label: 'Setup' },
  ],
}

function matches(path: string, to: string, end?: boolean): boolean {
  return end ? path === to || path === `${to}/` : path === to || path.startsWith(`${to}/`)
}

function sectionFor(path: string): Section {
  if (OWNER_SECTION.pages.some((p) => matches(path, p.to))) return OWNER_SECTION
  return (
    SECTIONS.find((s) => s.pages.some((p) => matches(path, p.to, p.end)) || s.also?.some((a) => matches(path, a))) ??
    SECTIONS[0]!
  )
}

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

export default function TradeMindApp({ ownerConsole = false }: TradeMindAppProps) {
  const status = useBrainStatus()
  const latest = useLatestRun()
  const broker = useQuery({ queryKey: ['status'], queryFn: api.status, enabled: ownerConsole })
  const visibleSections = SECTIONS.map((s) => {
    if (!ownerConsole && s.label === 'My Portfolio') {
      return {
        ...s,
        pages: s.pages.filter((p) => p.to !== '/trademind/holdings' && p.to !== '/trademind/testing'),
      }
    }
    if (!ownerConsole && s.label === 'Swing Picks') {
      return { ...s, pages: s.pages.filter((p) => p.to !== '/trademind/watchlist') }
    }
    if (!ownerConsole && s.label === 'Brain Logs') {
      return { ...s, pages: s.pages.filter((p) => p.to !== '/trademind/observatory') }
    }
    return s
  })
  const location = useLocation()
  const found = sectionFor(location.pathname)
  // The row under the bar lists only pages this account can open.
  const section = visibleSections.find((s) => s.label === found.label) ?? found
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
          {visibleSections.map((sec) => (
            <Link key={sec.label} to={sec.pages[0]!.to} className={sec.label === section.label ? 'active' : ''}>
              {sec.label}
            </Link>
          ))}
        </nav>
        <div className="tm-topbar-right">
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
                  {OWNER_SECTION.pages.map((pg) => (
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
      {section.pages.length > 1 && (
        <nav className="tm-subnav" aria-label={`${section.label} pages`}>
          {section.pages.map((pg) => (
            <NavLink key={pg.to} to={pg.to} end={pg.end} className={({ isActive }) => (isActive ? 'active' : '')}>
              {pg.label}
            </NavLink>
          ))}
        </nav>
      )}

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
          <Route path="holdings" element={ownerConsole ? <MyHoldings /> : <Navigate to="/trademind/portfolio" replace />} />
          <Route path="setup" element={ownerConsole ? <Setup /> : <Navigate to="/trademind" replace />} />
          <Route path="*" element={<Navigate to="/trademind" replace />} />
        </Route>
      </Routes>
    </div>
  )
}
