// The TradeMind area: a full-screen app of its own (own top menu, own dark
// glowing theme) mounted at /trademind. The classic app is untouched.

import { NavLink, Navigate, Route, Routes, Link } from 'react-router-dom'

import './trademind.css'
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

const NAV = [
  { to: '/trademind', label: 'Brain', end: true },
  { to: '/trademind/market', label: 'Market' },
  { to: '/trademind/opportunities', label: 'Opportunities' },
  { to: '/trademind/portfolio', label: 'Portfolio' },
  { to: '/trademind/positions', label: 'Positions' },
  { to: '/trademind/ai', label: 'AI' },
  { to: '/trademind/risk', label: 'Risk' },
  { to: '/trademind/learn', label: 'Learn' },
  { to: '/trademind/system', label: 'System' },
]

export default function TradeMindApp() {
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
          <span className="tm-demo-chip" title="These screens show sample numbers until the brain is connected">
            Demo data
          </span>
          <Link to="/dashboard" className="tm-avatar" title="Back to the classic app">
            <Icon.User />
          </Link>
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
          <Route path="*" element={<Navigate to="/trademind" replace />} />
        </Route>
      </Routes>
    </div>
  )
}
