import { NavLink, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'

import { api, captureTokenFromRedirect, clearToken, getToken } from './api/client'
import AuthScreen from './components/AuthScreen'
import Dashboard from './pages/Dashboard'
import Finance from './pages/Finance'
import Positions from './pages/Positions'
import Recommendations from './pages/Recommendations'
import Signals from './pages/Signals'
import Suggestions from './pages/Suggestions'
import Strategies from './pages/Strategies'
import Models from './pages/Models'
import Trades from './pages/Trades'
import Settings from './pages/Settings'

const NAV = [
  { to: '/dashboard', label: 'Dashboard' },
  { to: '/suggestions', label: 'Suggestions' },
  { to: '/recommendations', label: 'Recommendations' },
  { to: '/positions', label: 'Positions' },
  { to: '/signals', label: 'Signals' },
  { to: '/trades', label: 'Trades' },
  { to: '/strategies', label: 'Strategies' },
  { to: '/models', label: 'ML Models' },
  { to: '/finance', label: 'Finance' },
  { to: '/settings', label: 'Settings' },
]

// Runs once at module load, before the first render decides whether to show
// the auth screen — a Google login redirect lands here with ?token=... and
// must be captured before that check runs, or it would flash the login
// screen and drop the token.
captureTokenFromRedirect()

export default function App() {
  const hasToken = !!getToken()
  const location = useLocation()

  const { data: status } = useQuery({
    queryKey: ['status'],
    queryFn: api.status,
    refetchInterval: 30_000,
    enabled: hasToken,
  })
  const { data: me } = useQuery({
    queryKey: ['me'],
    queryFn: api.me,
    enabled: hasToken,
    retry: false,
  })

  if (!hasToken) {
    return <AuthScreen />
  }

  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="brand">
          Swing Trade ML
          <small>{status?.environment ?? '—'}</small>
        </div>

        <nav className="nav">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) => (isActive ? 'active' : '')}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div style={{ marginTop: 'auto', fontSize: '0.78rem' }}>
          <div className="row" style={{ marginBottom: '0.4rem' }}>
            <span className="muted">Mode</span>
            <span
              className={`badge ${status?.live_trading_enabled ? 'badge-live' : 'badge-paper'}`}
            >
              {status?.live_trading_enabled ? 'LIVE' : 'PAPER'}
            </span>
          </div>
          <div className="row" style={{ marginBottom: '0.4rem' }}>
            <span className="muted">Kite</span>
            <span className={`badge ${status?.broker_authenticated ? 'badge-on' : 'badge-off'}`}>
              {status?.broker_authenticated ? 'connected' : 'no session'}
            </span>
          </div>
          <div className="row" style={{ marginBottom: '0.6rem' }}>
            <span className="muted">Model</span>
            <span className="muted">{status?.active_model ?? 'none'}</span>
          </div>
          <div className="row" style={{ justifyContent: 'space-between' }}>
            <span className="muted" title={me?.email ?? undefined}>
              {me?.username ?? '…'}
            </span>
            <button
              onClick={() => {
                clearToken()
                window.location.reload()
              }}
            >
              Log out
            </button>
          </div>
        </div>
      </aside>

      <main className="content">
        {status && !status.broker_authenticated && (
          <div className="banner banner-warn">
            No active Zerodha session — Kite tokens expire daily at ~06:00 IST.{' '}
            {status.open_positions > 0 ? (
              <strong>
                Stop-loss/target checks are NOT running on your {status.open_positions} open
                position{status.open_positions === 1 ? '' : 's'} until you log in.
              </strong>
            ) : (
              'Market data and new orders will fail until you log in.'
            )}{' '}
            <a
              href="#"
              onClick={(e) => {
                e.preventDefault()
                api.kiteLogin().then((r) => window.open(r.login_url, '_blank'))
              }}
              style={{ color: 'inherit', textDecoration: 'underline' }}
            >
              Log in to Kite
            </a>
          </div>
        )}

        <div key={location.pathname} className="page-transition">
          <Routes>
            <Route path="/" element={<Navigate to="/dashboard" replace />} />
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/suggestions" element={<Suggestions />} />
            <Route path="/recommendations" element={<Recommendations />} />
            <Route path="/positions" element={<Positions />} />
            <Route path="/signals" element={<Signals />} />
            <Route path="/trades" element={<Trades />} />
            <Route path="/strategies" element={<Strategies />} />
            <Route path="/models" element={<Models />} />
            <Route path="/finance" element={<Finance />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </div>
      </main>
    </div>
  )
}
