import { NavLink, Navigate, Route, Routes } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'

import { api, getApiKey, setApiKey } from './api/client'
import Dashboard from './pages/Dashboard'
import Positions from './pages/Positions'
import Signals from './pages/Signals'
import Strategies from './pages/Strategies'
import Models from './pages/Models'
import Trades from './pages/Trades'
import Settings from './pages/Settings'

const NAV = [
  { to: '/dashboard', label: 'Dashboard' },
  { to: '/positions', label: 'Positions' },
  { to: '/signals', label: 'Signals' },
  { to: '/trades', label: 'Trades' },
  { to: '/strategies', label: 'Strategies' },
  { to: '/models', label: 'ML Models' },
  { to: '/settings', label: 'Settings' },
]

export default function App() {
  const { data: status } = useQuery({
    queryKey: ['status'],
    queryFn: api.status,
    refetchInterval: 30_000,
  })

  // First run: no key stored yet, so every protected call would 401. Prompt for
  // it once rather than showing a dashboard full of errors.
  if (!getApiKey()) {
    return <ApiKeyPrompt />
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
          <div className="row">
            <span className="muted">Model</span>
            <span className="muted">{status?.active_model ?? 'none'}</span>
          </div>
        </div>
      </aside>

      <main className="content">
        {status?.live_trading_enabled && (
          <div className="banner banner-live">
            <strong>LIVE TRADING IS ENABLED.</strong> Orders placed by this system use real money.
          </div>
        )}
        {status && !status.broker_authenticated && (
          <div className="banner banner-warn">
            No active Zerodha session. Market data and new orders will fail until you log in —
            Kite tokens expire daily at ~06:00 IST.{' '}
            <a href="http://localhost:8000/api/v1/auth/kite/login" style={{ color: 'inherit', textDecoration: 'underline' }}>
              Log in to Kite
            </a>
          </div>
        )}

        <Routes>
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/positions" element={<Positions />} />
          <Route path="/signals" element={<Signals />} />
          <Route path="/trades" element={<Trades />} />
          <Route path="/strategies" element={<Strategies />} />
          <Route path="/models" element={<Models />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </main>
    </div>
  )
}

function ApiKeyPrompt() {
  return (
    <div style={{ display: 'grid', placeItems: 'center', minHeight: '100vh', padding: '1rem' }}>
      <form
        className="card"
        style={{ maxWidth: 420, width: '100%' }}
        onSubmit={(event) => {
          event.preventDefault()
          const value = new FormData(event.currentTarget).get('key')
          if (typeof value === 'string' && value.trim()) {
            setApiKey(value)
            window.location.reload()
          }
        }}
      >
        <h1 style={{ marginBottom: '0.5rem' }}>Swing Trade ML</h1>
        <p className="muted" style={{ marginTop: 0 }}>
          Enter the <code>API_KEY</code> from your <code>.env</code> file to connect to the backend.
        </p>
        <input name="key" type="password" placeholder="API key" autoFocus />
        <button className="primary" type="submit" style={{ marginTop: '0.8rem', width: '100%' }}>
          Connect
        </button>
      </form>
    </div>
  )
}
