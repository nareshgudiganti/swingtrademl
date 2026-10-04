// The TradeMind area: a full-screen app of its own (own top menu, own dark
// glowing theme) mounted at /trademind. The classic app is untouched.

import { useQuery } from '@tanstack/react-query'
import { Link, NavLink, Navigate, Route, Routes, useLocation } from 'react-router-dom'

import './trademind.css'
import { api } from '../api/client'
import { clearToken } from '../api/client'
import { formatDateTime } from '../lib/format'
import { useBrainStatus, useLatestRun, useMarketSession } from './live'
import { Icon } from './ui'
import Home from './pages/Home'
import Market from './pages/Market'
import Opportunities from './pages/Opportunities'
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

// One final app in five sections (owner-approved design, 2026-10-04): the top
// row is the section, the row under it the pages of that section. Finance and
// Classic view are hidden from the menu for now (owner, 2026-10-04); their
// pages still exist and come back when asked for.
type Page = { to: string; label: string; end?: boolean }
type Section = { label: string; pages: Page[]; also?: string[] }

const SECTIONS: Section[] = [
  {
    label: 'Decisions',
    pages: [
      { to: '/trademind', label: 'Home', end: true },
      { to: '/trademind/ai', label: 'AI' },
    ],
  },
  {
    label: 'Discover',
    pages: [
      { to: '/trademind/opportunities', label: 'Opportunities' },
      { to: '/trademind/market', label: 'Market' },
    ],
    also: ['/trademind/stock'],
  },
  {
    label: 'Portfolio',
    pages: [
      { to: '/trademind/positions', label: 'Positions' },
      { to: '/trademind/holdings', label: 'My Holdings' },
      { to: '/trademind/portfolio', label: 'Overview' },
    ],
  },
  {
    label: 'Performance',
    pages: [
      { to: '/trademind/records', label: 'Records' },
      { to: '/trademind/learn', label: 'Learn' },
    ],
  },
  {
    label: 'Settings',
    pages: [
      { to: '/trademind/control', label: 'Control' },
      { to: '/trademind/golive', label: 'Go-live' },
      { to: '/trademind/risk', label: 'Risk' },
      { to: '/trademind/system', label: 'System' },
      { to: '/trademind/setup', label: 'Setup' },
    ],
  },
]

function matches(path: string, to: string, end?: boolean): boolean {
  return end ? path === to || path === `${to}/` : path === to || path.startsWith(`${to}/`)
}

function sectionFor(path: string): Section {
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
  const visibleSections = SECTIONS.filter((s) => {
    if (!ownerConsole && s.label === 'Settings') return false
    return true
  }).map((s) => {
    if (!ownerConsole && s.label === 'Portfolio') {
      return { ...s, pages: s.pages.filter((p) => p.to !== '/trademind/holdings') }
    }
    return s
  })
  const section = sectionFor(useLocation().pathname)
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
            <Link key={sec.label} to={sec.pages[0]!.to} className={sec === section ? 'active' : ''}>
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
          {ownerConsole && (
            <a href="/plans" className="tm-zchip" title="Free / Pro plans, preview, and users">
              Plans
            </a>
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
            <Link to="/trademind/setup" className="tm-avatar" title="Your account and settings">
              <Icon.User />
            </Link>
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
      <nav className="tm-subnav" aria-label={`${section.label} pages`}>
        {section.pages.map((pg) => (
          <NavLink key={pg.to} to={pg.to} end={pg.end} className={({ isActive }) => (isActive ? 'active' : '')}>
            {pg.label}
          </NavLink>
        ))}
      </nav>

      {/* Rendered outside any parent <Route>, so the paths are anchored here. */}
      <Routes>
        <Route path="/trademind">
          <Route index element={<Home />} />
          <Route path="market" element={<Market />} />
          <Route path="opportunities" element={<Opportunities />} />
          <Route path="stock/:symbol" element={<StockDetail />} />
          <Route path="portfolio" element={<Portfolio />} />
          <Route path="positions" element={<Positions />} />
          <Route path="positions/:symbol" element={<Positions />} />
          <Route path="ai" element={<AIDecision />} />
          <Route path="ai/:symbol" element={<AIDecision />} />
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
