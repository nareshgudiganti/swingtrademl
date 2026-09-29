import { useState, type ComponentType, type ReactNode } from 'react'
import { NavLink, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, captureTokenFromRedirect, clearToken, getToken, setPreviewPlan } from './api/client'
import AuthScreen from './components/AuthScreen'
import { Loading } from './components/Loading'
import Dashboard from './pages/Dashboard'
import Finance from './pages/Finance'
import Positions from './pages/Positions'
import Reports from './pages/Reports'
import ScanResults from './pages/ScanResults'
import Strategies from './pages/Strategies'
import Models from './pages/Models'
import Holdings from './pages/Holdings'
import Safety from './pages/Safety'
import Capital from './pages/Capital'
import ModelLab from './pages/ModelLab'
import PlanHome from './pages/PlanHome'
import PlansManager from './pages/PlansManager'
import Settings from './pages/Settings'
import { PLAN_LABELS, usePlan } from './lib/plan'
import {
  AlertTriangleIcon,
  BarChartIcon,
  BriefcaseIcon,
  GearIcon,
  HomeIcon,
  LayersIcon,
  ScaleIcon,
  SproutIcon,
  WalletIcon,
} from './components/icons'

// Who sees a screen:
//  - `feature` set: anyone whose plan includes that feature (the owner
//    always does). The API refuses the same data to everyone else, so the
//    menu is a convenience, not the lock.
//  - `planHome`: the home screen for Free / Plus / Pro users.
//  - neither: the owner only — the real account, money and switches.
type Screen = {
  to: string
  label: string
  Icon: ComponentType
  element: ReactNode
  feature?: string
  planHome?: boolean
  inNav?: boolean
}

// Settings and ML Models are still routed but deliberately left out of the
// top-level nav — they're admin/config screens, not something a day-to-day
// user needs alongside Dashboard/Strategies/Portfolio/Reports. The user and
// Log out already live in the sidebar status strip below, so Settings earned
// no place in the nav once auto-login removed the daily Kite login chore.
//
// Finance is hidden the same way as of 2026-09-28 — parked at the user's
// request until they confirm it should come back, not retired. Its page,
// route and API surface are all untouched.
//
// They remain reachable by URL: /settings (watchlist editor, sync + backfill,
// scheduler status), /models and /finance. Nothing was deleted — if any of
// them needs to come back, set inNav.
const SCREENS: Screen[] = [
  { to: '/home', label: "Today's picks", Icon: HomeIcon, element: <PlanHome />, planHome: true, inNav: true },
  { to: '/dashboard', label: 'Dashboard', Icon: HomeIcon, element: <Dashboard />, inNav: true },
  { to: '/strategies', label: 'Strategies', Icon: ScaleIcon, element: <Strategies />, inNav: true },
  { to: '/holdings', label: 'My Holdings', Icon: WalletIcon, element: <Holdings />, inNav: true },
  {
    to: '/portfolio',
    label: 'Portfolio',
    Icon: BriefcaseIcon,
    element: <Positions />,
    feature: 'bot_portfolio',
    inNav: true,
  },
  { to: '/capital', label: 'Capital', Icon: SproutIcon, element: <Capital />, inNav: true },
  {
    to: '/reports',
    label: 'Reports',
    Icon: BarChartIcon,
    element: <Reports />,
    feature: 'bot_performance',
    inNav: true,
  },
  {
    to: '/scans',
    label: 'Scan Results',
    Icon: LayersIcon,
    element: <ScanResults />,
    feature: 'track_record',
    inNav: true,
  },
  {
    to: '/model-lab',
    label: 'Model Lab',
    Icon: BarChartIcon,
    element: <ModelLab />,
    feature: 'model_lab',
    inNav: true,
  },
  { to: '/safety', label: 'Safety', Icon: AlertTriangleIcon, element: <Safety />, inNav: true },
  { to: '/plans', label: 'Plans', Icon: GearIcon, element: <PlansManager />, inNav: true },
  { to: '/models', label: 'ML Models', Icon: BarChartIcon, element: <Models /> },
  { to: '/finance', label: 'Finance', Icon: WalletIcon, element: <Finance /> },
  { to: '/settings', label: 'Settings', Icon: GearIcon, element: <Settings /> },
]

// The destinations worth a one-tap reach on a phone — a real bottom tab
// bar, shown only under the same 800px breakpoint the sidebar already
// collapses at. This sits alongside that collapsed horizontal strip rather
// than replacing it: the strip stays the full list, the tab bar is just the
// handful used every day. Filtered by plan like everything else.
const TAB_BAR = ['/home', '/dashboard', '/portfolio', '/reports', '/scans']

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

function NotInPlan({ plan }: { plan: string }) {
  return (
    <div className="card" style={{ maxWidth: 520 }}>
      <h2 style={{ marginTop: 0 }}>Not in your plan</h2>
      <p className="muted" style={{ marginBottom: 0 }}>
        This page isn't included in the {PLAN_LABELS[plan] ?? plan} plan.
      </p>
    </div>
  )
}

export default function App() {
  const hasToken = !!getToken()
  const location = useLocation()
  const queryClient = useQueryClient()
  const { plan, isOwner, has, isLoading: planLoading } = usePlan()

  // Account status (mode, Kite session, portfolio) is the owner's business;
  // the API refuses it to plan users, so they don't ask.
  const { data: status } = useQuery({
    queryKey: ['status'],
    queryFn: api.status,
    refetchInterval: 30_000,
    enabled: hasToken && isOwner,
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

  const canSee = (s: Screen): boolean => isOwner || !!s.planHome || (!!s.feature && has(s.feature))
  // The owner's home is the Dashboard; /home stays reachable by URL for them.
  const nav = plan ? SCREENS.filter((s) => s.inNav && canSee(s) && !(isOwner && s.planHome)) : []
  const tabBar = TAB_BAR.map((to) => nav.find((s) => s.to === to)).filter((s): s is Screen => !!s)
  const homePath = isOwner ? '/dashboard' : '/home'
  const planKey = plan?.plan ?? 'free'

  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="brand" title="Swing Trade ML">
          <span className="brand-mark">📈</span>
          <span className="brand-label">
            Swing Trade ML
            <small>{isOwner ? (status?.environment ?? '—') : `${PLAN_LABELS[planKey] ?? planKey} plan`}</small>
          </span>
        </div>

        <nav className="nav">
          {nav.map((item) => (
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
          {isOwner && (
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
          )}
          <div className="status-strip-user">
            <span className="muted" title={me?.email ?? undefined}>
              {me?.username ?? '…'}
            </span>
            <button
              onClick={() => {
                setPreviewPlan(null)
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
        {plan?.previewing && (
          <div className="banner banner-info">
            👁️ You're previewing the {PLAN_LABELS[planKey] ?? planKey} plan: this is exactly what its users
            see.{' '}
            <a
              href="/plans"
              onClick={(e) => {
                e.preventDefault()
                setPreviewPlan(null)
                window.location.assign('/plans')
              }}
              style={{ color: 'inherit', textDecoration: 'underline' }}
            >
              Exit preview
            </a>
          </div>
        )}

        {/* Dashboard only. This is a system-health notice, not something that
            changes what any other page means, and repeating it on every tab
            cost the top of every screen — the Holdings table in particular
            started below the fold because of it. The Dashboard is where you
            go to ask "is everything working", so it lives there. */}
        {status && status.status_level === 'warning' && location.pathname === '/dashboard' && (
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
          {planLoading || !plan ? (
            <Loading />
          ) : (
            <Routes>
              <Route path="/" element={<Navigate to={homePath} replace />} />
              {SCREENS.map((s) => (
                <Route
                  key={s.to}
                  path={s.to}
                  element={canSee(s) ? s.element : <NotInPlan plan={planKey} />}
                />
              ))}
              <Route path="*" element={<Navigate to={homePath} replace />} />
            </Routes>
          )}
        </div>
      </main>

      <nav className="tab-bar">
        {tabBar.map((item) => (
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
