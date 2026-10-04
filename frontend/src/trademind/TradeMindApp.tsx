// The TradeMind area: a full-screen app of its own (own top menu, own dark
// glowing theme) mounted at /trademind. The classic app is untouched.

import { useQuery } from '@tanstack/react-query'
import { NavLink, Navigate, Route, Routes, Link } from 'react-router-dom'

import './trademind.css'
import { api } from '../api/client'
import { clearToken } from '../api/client'
import { formatDateTime } from '../lib/format'
import { useBrainStatus, useLatestRun } from './live'
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

// One final app: everything the owner uses, most-used first. Finance is a
// separate app (owner decision) and Classic view is the old screens, kept
// reachable during the changeover — both leave the TradeMind area.
const NAV = [
  { to: '/trademind', label: 'Home', end: true },
  { to: '/trademind/control', label: 'Control' },
  { to: '/trademind/opportunities', label: 'Opportunities' },
  { to: '/trademind/positions', label: 'Positions' },
  { to: '/trademind/holdings', label: 'My Holdings' },
  { to: '/trademind/portfolio', label: 'Portfolio' },
  { to: '/trademind/market', label: 'Market' },
  { to: '/trademind/ai', label: 'AI' },
  { to: '/trademind/risk', label: 'Risk' },
  { to: '/trademind/records', label: 'Records' },
  { to: '/trademind/golive', label: 'Go-live' },
  { to: '/trademind/learn', label: 'Learn' },
  { to: '/trademind/system', label: 'System' },
  { to: '/trademind/setup', label: 'Setup' },
  { to: '/finance', label: 'Finance ↗' },
  { to: '/dashboard', label: 'Classic view ↗' },
]

const STATUS_CHIP: Record<ReturnType<typeof useBrainStatus>, { label: string; title: string }> = {
  live: { label: 'Live', title: "Connected to the brain's latest run" },
  'no-run': { label: 'No run yet', title: 'The brain is on but has not run yet.' },
  off: { label: 'Brain off', title: 'The brain is switched off on this server' },
  loading: { label: 'Connecting…', title: 'Checking the connection to the brain' },
  error: { label: 'Error', title: 'Could not reach the brain' },
}

export default function TradeMindApp() {
  const status = useBrainStatus()
  const latest = useLatestRun()
  const broker = useQuery({ queryKey: ['status'], queryFn: api.status })
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
        <nav className="tm-nav">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end} className={({ isActive }) => (isActive ? 'active' : '')}>
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="tm-topbar-right">
          {broker.data && (
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
          <Link to="/trademind/setup" className="tm-avatar" title="Your account and settings">
            <Icon.User />
          </Link>
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
          <Route path="risk" element={<Risk />} />
          <Route path="learn" element={<Learn />} />
          <Route path="system" element={<System />} />
          <Route path="control" element={<Control />} />
          <Route path="golive" element={<GoLive />} />
          <Route path="records" element={<Records />} />
          <Route path="holdings" element={<MyHoldings />} />
          <Route path="setup" element={<Setup />} />
          <Route path="*" element={<Navigate to="/trademind" replace />} />
        </Route>
      </Routes>
    </div>
  )
}
