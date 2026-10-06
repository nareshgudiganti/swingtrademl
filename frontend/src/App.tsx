import { useEffect, useRef, useState, type ComponentType, type ReactNode } from 'react'
import { NavLink, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, captureTokenFromRedirect, clearToken, getToken, setPreviewPlan } from './api/client'
import AuthScreen from './components/AuthScreen'
import { Loading } from './components/Loading'
import Dashboard from './pages/Dashboard'
import Finance from './pages/Finance'
import Positions from './pages/Positions'
import PaperTesting from './pages/PaperTesting'
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
import Brain from './pages/Brain'
import TradeMindApp from './trademind/TradeMindApp'
import { PLAN_LABELS, usePlan } from './lib/plan'
import { modelLabel } from './lib/format'
import {
  AlertTriangleIcon,
  BarChartIcon,
  BrainIcon,
  BriefcaseIcon,
  ChevronDownIcon,
  GearIcon,
  HomeIcon,
  LayersIcon,
  ScaleIcon,
  SproutIcon,
  UserIcon,
  WalletIcon,
} from './components/icons'

// Who sees a screen:
//  - `feature` set: anyone whose plan includes that feature (the owner
//    always does). The API refuses the same data to everyone else, so the
//    menu is a convenience, not the lock.
//  - `planHome`: the home screen for Free / Pro users.
//  - `manage`: the real owner only, even while previewing (the Plans page).
//  - none of these: accounts that see the whole app — the owner, or anyone
//    while plans are switched off (the app as it was before plans).
type Screen = {
  to: string
  label: string
  Icon: ComponentType
  element: ReactNode
  feature?: string
  planHome?: boolean
  manage?: boolean
  inNav?: boolean
  /** Shown only when PAPER_TESTER_ENABLED is on (status.paper_tester_enabled). */
  paperTester?: boolean
}

// Settings and ML Models are still routed but deliberately left out of the
// top-level nav — they're admin/config screens, not something a day-to-day
// user needs alongside Dashboard/Strategies/Portfolio/Reports. The user and
// Log out live in the top bar's account menu (which also links Settings), so
// Settings earned no place in the main nav once auto-login removed the daily Kite login chore.
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
  {
    to: '/paper-testing',
    label: 'Paper testing',
    Icon: LayersIcon,
    element: <PaperTesting />,
    paperTester: true,
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
  { to: '/plans', label: 'Plans', Icon: GearIcon, element: <PlansManager />, manage: true, inNav: true },
  { to: '/models', label: 'ML Models', Icon: BarChartIcon, element: <Models /> },
  { to: '/finance', label: 'Finance', Icon: WalletIcon, element: <Finance /> },
  { to: '/settings', label: 'Settings', Icon: GearIcon, element: <Settings /> },
]

// The destinations worth a one-tap reach on a phone — a real bottom tab
// bar, shown only under the same 800px breakpoint the top bar's menu
// collapses at. This sits alongside that collapsed horizontal strip rather
// than replacing it: the strip stays the full list, the tab bar is just the
// handful used every day. Filtered by plan like everything else.
const TAB_BAR = ['/home', '/dashboard', '/portfolio', '/reports', '/scans']

// The top bar shows this many menu entries directly; the rest sit under
// "More", the way most broker sites do it. On phones the bar turns into a
// sideways-scrolling strip of every entry instead, so nothing is hidden there.
const PRIMARY_NAV_COUNT = 6

// Real money is at stake once live_trading_enabled flips true — this must be
// acknowledged explicitly per browser before the rest of the app is usable,
// rather than trusting someone to notice the small PAPER/LIVE badge in the
// top bar on their own.
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
  const { plan, seesAll, canManage, has, isLoading: planLoading } = usePlan()

  // Account status (mode, Kite session, portfolio) is the owner's business;
  // the API refuses it to plan users, so they don't ask.
  const { data: status, isError: statusFailed } = useQuery({
    queryKey: ['status'],
    queryFn: api.status,
    refetchInterval: 30_000,
    enabled: hasToken && (seesAll || canManage),
  })
  const { data: me } = useQuery({
    queryKey: ['me'],
    queryFn: api.me,
    enabled: hasToken,
    retry: false,
  })
  const isOwnerEarly = canManage || !!me?.is_superuser
  const { data: brainRun } = useQuery({
    queryKey: ['brainLatest'],
    queryFn: () => api.brainLatestRun('nightly'),
    enabled: hasToken && (isOwnerEarly ? !!status?.brain_enabled : !!plan?.brain_enabled),
    retry: false,
    refetchInterval: 300_000,
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
  // Which top-bar dropdown is open. Closed on every page change and on any
  // click outside the menus.
  const [openMenu, setOpenMenu] = useState<'more' | 'user' | null>(null)
  const menusRef = useRef<HTMLElement>(null)
  const userMenuRef = useRef<HTMLDivElement>(null)
  useEffect(() => setOpenMenu(null), [location.pathname])
  useEffect(() => {
    if (!openMenu) return
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node
      if (!menusRef.current?.contains(t) && !userMenuRef.current?.contains(t)) setOpenMenu(null)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [openMenu])
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

  const waiting = statusFailed ? <Navigate to="/dashboard" replace /> : <p className="muted">Loading…</p>

  const isOwner = canManage || !!me?.is_superuser
  const brainOn = isOwner ? !!status?.brain_enabled : !!plan?.brain_enabled
  const canTradeMind = brainOn && (isOwner || has('trademind'))
  const plansPath =
    location.pathname === '/plans' ||
    location.pathname.startsWith('/plans/') ||
    location.pathname === '/trademind/plans'

  // Plans manager: classic light shell (not inside the dark TradeMind chrome).
  if (plansPath) {
    if (planLoading) return <Loading />
    const backTo = isOwner && status?.brain_enabled ? '/trademind' : '/dashboard'
    return (
      <div className="layout">
        <header className="topbar">
          <div className="topbar-inner between">
            <NavLink to={backTo} className="brand" title="Back">
              <span className="brand-mark">←</span>
              <span className="brand-label">
                Swing Trade ML
                <small>Plans</small>
              </span>
            </NavLink>
          </div>
        </header>
        <main className="content">
          <PlansManager />
        </main>
      </div>
    )
  }

  // When the brain is on, the owner lives in TradeMind. Classic tabs stay off
  // the menu; /plans and /settings remain reachable by URL.
  if (isOwner && status?.brain_enabled) {
    if (location.pathname.startsWith('/trademind')) {
      return <TradeMindApp ownerConsole />
    }
    if (location.pathname === '/settings') {
      return (
        <div className="layout">
          <main className="content">
            <Settings />
          </main>
        </div>
      )
    }
    return <Navigate to="/trademind" replace />
  }

  if (location.pathname.startsWith('/trademind')) {
    if (!canTradeMind) {
      return <Navigate to={plan && !seesAll ? '/home' : '/dashboard'} replace />
    }
    if (isOwner && !status) {
      return planLoading || !plan ? <Loading /> : waiting
    }
    return <TradeMindApp ownerConsole={isOwner} />
  }

  if (isOwner && !status && !statusFailed) {
    return planLoading || !plan ? <Loading /> : <Loading />
  }

  const canSee = (s: Screen): boolean => {
    if (s.manage) return canManage
    // Manual paper testing is not a Free/Pro feature. Owner (and plans-off) only.
    if (s.paperTester) return seesAll
    return seesAll || !!s.planHome || (!!s.feature && has(s.feature))
  }
  // A full-app account's home is the Dashboard; /home stays reachable by URL.
  // While previewing, the Plans link is hidden so the menu matches the plan
  // exactly — the preview banner is the way back.
  const inMenu = (s: Screen): boolean =>
    !!s.inNav &&
    canSee(s) &&
    !(seesAll && s.planHome) &&
    !(s.manage && plan?.previewing) &&
    (!s.paperTester || !!status?.paper_tester_enabled)
  // Brain on → TradeMind is the whole app (see above). Brain off → console link only.
  const brainNav: Screen[] =
    isOwner && status?.brain_enabled
      ? []
      : isOwner
        ? [{ to: '/brain', label: 'Brain', Icon: BrainIcon, element: <Brain />, inNav: true }]
        : []
  const trademindNav: Screen[] =
    plan && !seesAll && canTradeMind
      ? [{ to: '/trademind', label: 'TradeMind', Icon: BrainIcon, element: null, inNav: true }]
      : []
  const nav = plan ? [...SCREENS.filter(inMenu), ...trademindNav, ...brainNav] : []
  const tabBar = TAB_BAR.map((to) => nav.find((s) => s.to === to)).filter((s): s is Screen => !!s)
  const moreItems = nav.slice(PRIMARY_NAV_COUNT)
  const moreActive = moreItems.some((s) => location.pathname.startsWith(s.to))
  const homePath = isOwner
    ? status?.brain_enabled
      ? '/trademind'
      : '/dashboard'
    : canTradeMind
      ? '/trademind'
      : '/home'
  const planKey = plan?.plan ?? 'free'

  return (
    <div className="layout">
      <header className="topbar">
        <div className="topbar-inner">
          <NavLink to={homePath} className="brand" title="Swing Trade ML">
            <span className="brand-mark">📈</span>
            <span className="brand-label">
              Swing Trade ML
              <small>{seesAll ? (status?.environment ?? '—') : `${PLAN_LABELS[planKey] ?? planKey} plan`}</small>
            </span>
          </NavLink>

          <nav className="nav" ref={menusRef}>
            {nav.map((item, i) => (
              <NavLink
                key={item.to}
                to={item.to}
                title={item.label}
                className={({ isActive }) =>
                  `${isActive ? 'active' : ''}${i >= PRIMARY_NAV_COUNT ? ' nav-overflow' : ''}`
                }
              >
                <item.Icon />
                <span className="nav-label">{item.label}</span>
              </NavLink>
            ))}
            {moreItems.length > 0 && (
              <div className="nav-more">
                <button
                  type="button"
                  className={`nav-more-button${moreActive ? ' active' : ''}`}
                  aria-expanded={openMenu === 'more'}
                  onClick={() => setOpenMenu(openMenu === 'more' ? null : 'more')}
                >
                  More <ChevronDownIcon />
                </button>
                {openMenu === 'more' && (
                  <div className="dropdown">
                    {moreItems.map((item) => (
                      <NavLink
                        key={item.to}
                        to={item.to}
                        className={({ isActive }) => `dropdown-item${isActive ? ' active' : ''}`}
                      >
                        <item.Icon />
                        {item.label}
                      </NavLink>
                    ))}
                  </div>
                )}
              </div>
            )}
          </nav>

          <div className="topbar-right" ref={userMenuRef}>
            {seesAll && (
              <>
                <span
                  className={`badge ${status?.live_trading_enabled ? 'badge-live' : 'badge-paper'}`}
                  title={status?.live_trading_enabled ? 'Real money' : 'Practice money — no real orders'}
                >
                  {status?.live_trading_enabled ? 'LIVE' : 'PAPER'}
                </span>
                {status?.brain_enabled && brainRun?.banner.mode && (
                  <NavLink
                    to="/brain"
                    className={`badge ${
                      brainRun.banner.mode === 'NORMAL'
                        ? 'badge-on'
                        : brainRun.banner.mode === 'DEFENSIVE'
                          ? 'badge-warn'
                          : 'badge-off'
                    }`}
                    title={brainRun.banner.headline ?? undefined}
                  >
                    Brain: {brainRun.banner.mode === 'NO_NEW_TRADES' ? 'NO NEW TRADES' : brainRun.banner.mode}
                  </NavLink>
                )}
                <span
                  className="badge badge-off"
                  title={(status?.active_models ?? []).map(modelLabel).join('\n') || 'Active model'}
                >
                  {(status?.active_models ?? []).length > 1
                    ? `${status!.active_models!.length} models`
                    : status?.active_model ?? 'no model'}
                </span>
              </>
            )}
            <button
              type="button"
              className="user-button"
              aria-expanded={openMenu === 'user'}
              onClick={() => setOpenMenu(openMenu === 'user' ? null : 'user')}
            >
              <UserIcon />
              <span className="user-name">{me?.username ?? '…'}</span>
              <ChevronDownIcon />
            </button>
            {openMenu === 'user' && (
              <div className="dropdown dropdown-right">
                {me?.email && <div className="dropdown-note">{me.email}</div>}
                {seesAll && (
                  <>
                    <div className="dropdown-row">
                      <span>Zerodha (Kite)</span>
                      <span className={`badge ${status?.broker_authenticated ? 'badge-on' : 'badge-off'}`}>
                        {status?.broker_authenticated ? 'Connected' : 'Not connected'}
                      </span>
                    </div>
                    <div className="dropdown-row">
                      <span>Model</span>
                      <span className="badge badge-off">{status?.active_model ?? 'none'}</span>
                    </div>
                    <NavLink to="/settings" className="dropdown-item">
                      <GearIcon />
                      Settings
                    </NavLink>
                  </>
                )}
                <button
                  type="button"
                  className="dropdown-item"
                  onClick={() => {
                    setPreviewPlan(null)
                    clearToken()
                    window.location.reload()
                  }}
                >
                  Log out
                </button>
              </div>
            )}
          </div>
        </div>
      </header>

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

        {statusFailed && !status && (
          <p className="muted">Could not reach the server — showing the classic screens.</p>
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
                  element={
                    s.paperTester ? (
                      seesAll && status?.paper_tester_enabled ? (
                        s.element
                      ) : (
                        <Navigate to={homePath} replace />
                      )
                    ) : canSee(s) ? (
                      s.element
                    ) : (
                      <NotInPlan plan={planKey} />
                    )
                  }
                />
              ))}
              <Route
                path="/brain"
                element={
                  !seesAll ? (
                    <NotInPlan plan={planKey} />
                  ) : !status ? (
                    waiting
                  ) : status.brain_enabled ? (
                    <Brain />
                  ) : (
                    <Navigate to="/dashboard" replace />
                  )
                }
              />
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
