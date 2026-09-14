import { useState } from 'react'
import { NavLink, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, captureTokenFromRedirect, clearToken, getToken } from './api/client'
import AuthScreen from './components/AuthScreen'
import Dashboard from './pages/Dashboard'
import Finance from './pages/Finance'
import Positions from './pages/Positions'
import Reports from './pages/Reports'
import ScanResults from './pages/ScanResults'
import Strategies from './pages/Strategies'
import Models from './pages/Models'
import Holdings from './pages/Holdings'
import Settings from './pages/Settings'
import { BarChartIcon, BriefcaseIcon, HomeIcon, LayersIcon, ScaleIcon, WalletIcon } from './components/icons'

// Settings and ML Models are still routed but deliberately left out of the
// top-level nav — they're admin/config screens, not something a day-to-day
// user needs alongside Dashboard/Strategies/Portfolio/Reports. The user and
// Log out already live in the sidebar status strip below, so Settings earned
// no place in the nav once auto-login removed the daily Kite login chore.
//
// They remain reachable by URL: /settings (watchlist editor, sync + backfill,
// scheduler status) and /models. Nothing was deleted — if either needs to
// come back, add it here.
const NAV = [
  { to: '/dashboard', label: 'Dashboard', Icon: HomeIcon },
  { to: '/strategies', label: 'Strategies', Icon: ScaleIcon },
  { to: '/holdings', label: 'My Holdings', Icon: WalletIcon },
  { to: '/portfolio', label: 'Portfolio', Icon: BriefcaseIcon },
  { to: '/reports', label: 'Reports', Icon: BarChartIcon },
  { to: '/scans', label: 'Scan Results', Icon: LayersIcon },
  { to: '/finance', label: 'Finance', Icon: WalletIcon },
]

// The 4 destinations worth a one-tap reach on a phone — a real bottom tab
// bar, shown only under the same 800px breakpoint the sidebar already
// collapses at. This sits alongside that collapsed horizontal strip rather
// than replacing it: the strip stays the full 6-item list (Settings and
// Scan Results included), the tab bar is just the handful used every day.
const TAB_BAR = [
  { to: '/dashboard', label: 'Dashboard', Icon: HomeIcon },
  { to: '/portfolio', label: 'Portfolio', Icon: BriefcaseIcon },
  { to: '/reports', label: 'Reports', Icon: BarChartIcon },
  { to: '/finance', label: 'Finance', Icon: WalletIcon },
]

// Real money is at stake once live_trading_enabled flips true — this must be
// acknowledged explicitly per browser before the rest of the app is usable,
// rather than trusting someone to notice the small PAPER/LIVE badge in the
// sidebar on their own.
const LIVE_ACK_STORAGE = 'stml_live_trading_ack'

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
  const [liveAcked, setLiveAcked] = useState(
    () => localStorage.getItem(LIVE_ACK_STORAGE) === 'true',
  )

  if (!hasToken) {
    return <AuthScreen />
  }

  if (status?.live_trading_enabled && !liveAcked) {
    return (
      <div className="layout" style={{ display: 'grid', placeItems: 'center', minHeight: '100vh' }}>
        <div className="card" style={{ maxWidth: 480 }}>
          <h1 style={{ marginTop: 0 }}>⚠️ Live trading is enabled</h1>
          <p>
            This account is currently placing <strong>real orders with real money</strong> on
            Zerodha, not simulated paper trades. Signals, stop-losses, and everything else in
            this app now affect an actual brokerage account.
          </p>
          <button
            className="primary"
            onClick={() => {
              localStorage.setItem(LIVE_ACK_STORAGE, 'true')
              setLiveAcked(true)
            }}
          >
            I understand — continue
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="brand" title="Swing Trade ML">
          <span className="brand-mark">📈</span>
          <span className="brand-label">
            Swing Trade ML
            <small>{status?.environment ?? '—'}</small>
          </span>
        </div>

        <nav className="nav">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              title={item.label}
              className={({ isActive }) => (isActive ? 'active' : '')}
            >
              <item.Icon />
              <span className="nav-label">{item.label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="status-strip">
          <div className="status-strip-badges">
            <span
              className={`badge ${status?.live_trading_enabled ? 'badge-live' : 'badge-paper'}`}
              title="Mode"
            >
              {status?.live_trading_enabled ? 'LIVE' : 'PAPER'}
            </span>
            <span
              className={`badge ${status?.broker_authenticated ? 'badge-on' : 'badge-off'}`}
              title="Kite"
            >
              {status?.broker_authenticated ? 'Kite connected' : 'Kite: no session'}
            </span>
            <span className="badge badge-off" title="Active model">
              {status?.active_model ?? 'no model'}
            </span>
          </div>
          <div className="status-strip-user">
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
            <Route path="/holdings" element={<Holdings />} />
            <Route path="/portfolio" element={<Positions />} />
            <Route path="/reports" element={<Reports />} />
            <Route path="/scans" element={<ScanResults />} />
            <Route path="/strategies" element={<Strategies />} />
            <Route path="/models" element={<Models />} />
            <Route path="/finance" element={<Finance />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="*" element={<Navigate to="/dashboard" replace />} />
          </Routes>
        </div>
      </main>

      <nav className="tab-bar">
        {TAB_BAR.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) => `tab-bar-item${isActive ? ' active' : ''}`}
          >
            <item.Icon />
            <span>{item.label}</span>
          </NavLink>
        ))}
      </nav>
    </div>
  )
}
