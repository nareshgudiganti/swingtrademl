import { NavLink, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

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
  const queryClient = useQueryClient()

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
  const refresh = useMutation({
    mutationFn: api.refreshData,
    onSuccess: (data) => {
      queryClient.setQueryData(['status'], data)
      // Refetch everything data-dependent, not just status — a stale-data
      // warning means predictions/signals were stale too, and the whole
      // point of this button is not needing a page reload to see it fixed.
      queryClient.invalidateQueries({ queryKey: ['signals'] })
      queryClient.invalidateQueries({ queryKey: ['signalHistory'] })
      queryClient.invalidateQueries({ queryKey: ['strategySignals'] })
      queryClient.invalidateQueries({ queryKey: ['predictions'] })
    },
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
        {status && status.status_level === 'warning' && (
          <div className="banner banner-warn">
            ⚠️ {status.status_message}
            {!status.broker_authenticated ? (
              <>
                {' '}
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
              </>
            ) : (
              <>
                {' '}
                <a
                  href="#"
                  onClick={(e) => {
                    e.preventDefault()
                    if (!refresh.isPending) refresh.mutate()
                  }}
                  style={{ color: 'inherit', textDecoration: 'underline' }}
                >
                  {refresh.isPending ? 'Refreshing…' : 'Refresh now'}
                </a>
                {refresh.isError && (
                  <span> — {(refresh.error as Error)?.message ?? 'refresh failed'}</span>
                )}
              </>
            )}
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
