// oa5: the written feature list for "Today = Home + Dashboard merged". Every thing the old TradeMind Home and Swing
// Picks (Dashboard) pages showed or let you do, plus the classic Dashboard, and where it lives now.
// The human-readable copy is docs/superpowers/plans/2026-10-23-oa5-today-feature-list.md; today/featureList.test.tsx
// checks that both list the same ids and that every item is reachable for each role that should have it.
//
// `where` is the page it lives on now. Items on Today carry `data-feature="<id>"` in the page, so the test can find
// them. `roles` is who gets it: owner (the owner console), tester (sees the whole app while plans are off, never
// the owner's private areas), member (a plan user with TradeMind). `realAccount`: only for REAL_ACCOUNT_USERS.
// `state` is the situation the item needs to appear (most need nothing special).

export type Role = 'owner' | 'tester' | 'member'
export type FeatureState = 'trade' | 'no-trade' | 'unavailable-horizon' | 'research-horizon'

export type Feature = {
  id: string
  from: 'Home' | 'Swing Picks' | 'Classic Dashboard' | 'New'
  item: string
  where: string
  roles: Role[]
  realAccount?: boolean
  state?: FeatureState
}

const ALL: Role[] = ['owner', 'tester', 'member']
const OWNER: Role[] = ['owner']
const SEES_ALL: Role[] = ['owner', 'tester']
const TODAY = '/trademind'

export const FEATURES: Feature[] = [
  // ---- TradeMind Home (pages/Home.tsx) ----
  { id: 'market-mode', from: 'Home', item: 'Market mode word, its icon and plain-English tag', where: TODAY, roles: ALL },
  { id: 'run-time', from: 'Home', item: "When the brain's run was made", where: TODAY, roles: ALL },
  { id: 'banner-headline', from: 'Home', item: "The market banner's headline", where: TODAY, roles: ALL },
  { id: 'market-situation', from: 'Home', item: 'The market situation the brain recognised', where: TODAY, roles: ALL },
  { id: 'idea-counts', from: 'Home', item: 'How many ideas got TRADE / WATCH / WAIT / AVOID, with View All', where: TODAY, roles: ALL },
  { id: 'no-trade-reason', from: 'Home', item: 'Why there is no TRADE idea today', where: TODAY, roles: ALL, state: 'no-trade' },
  { id: 'holdings-attention', from: 'Home', item: 'Holdings needing attention (MONITOR / REDUCE / EXIT), each opens its stock page', where: TODAY, roles: ALL },
  { id: 'changes-summary', from: 'Home', item: 'What changed since yesterday', where: TODAY, roles: ALL },
  { id: 'top-ideas', from: 'Home', item: 'Top 5 ideas as the one recommendation card, with View All', where: TODAY, roles: ALL },
  { id: 'insights', from: 'Home', item: "Today's insights (holding reasons, situation evidence, learning notes)", where: TODAY, roles: ALL },

  // ---- TradeMind Swing Picks (pages/Dashboard.tsx, /trademind/dashboard) ----
  { id: 'horizon-cards', from: 'Swing Picks', item: 'Horizon selector (1 / 5 / 15 / 30 / 90 days) with honest states', where: TODAY, roles: ALL },
  { id: 'how-it-works', from: 'Swing Picks', item: '"How it works?"', where: TODAY, roles: ALL },
  { id: 'summary-strip', from: 'Swing Picks', item: 'Summary strip: market view, NIFTY 50, top sectors, estimated chance, total picks', where: TODAY, roles: ALL },
  { id: 'horizon-pills', from: 'Swing Picks', item: 'Horizon pills above the pick list, with the pick count', where: TODAY, roles: ALL },
  { id: 'pick-filters', from: 'Swing Picks', item: 'Search, sector filter, minimum ranking, Reset', where: TODAY, roles: ALL },
  { id: 'pick-table', from: 'Swing Picks', item: 'Pick list: price, setup, entry, targets, stop, estimated chance, timeframe, View', where: TODAY, roles: ALL },
  { id: 'pick-detail', from: 'Swing Picks', item: 'Pick detail: price chart with ranges, quote, trade setup, why this pick, key risks', where: TODAY, roles: ALL, state: 'trade' },
  { id: 'horizon-unavailable', from: 'Swing Picks', item: 'A horizon with no strategy says so and shows no picks', where: TODAY, roles: ALL, state: 'unavailable-horizon' },
  { id: 'research-experiment', from: 'Swing Picks', item: "The owner's research experiment on 5 and 30 days", where: TODAY, roles: OWNER, state: 'research-horizon' },
  { id: 'disclaimer', from: 'Swing Picks', item: 'Practice-mode note (ideas to study, nothing places an order)', where: TODAY, roles: ALL },
  { id: 'dashboard-url', from: 'Swing Picks', item: '/trademind/dashboard still opens, now Today at the pick list', where: '/trademind/dashboard', roles: ALL },

  // ---- New on Today (oa5) ----
  { id: 'kill-switch', from: 'New', item: 'Status strip: new buys on, or paused by the kill switch (and why)', where: TODAY, roles: OWNER },
  { id: 'drawdown', from: 'New', item: 'Status strip: how far below its peak the paper account is, against the halt level', where: TODAY, roles: OWNER },
  { id: 'stage', from: 'New', item: 'Status strip: trading stage (Practice / Approval / Auto)', where: TODAY, roles: OWNER },
  { id: 'approvals-waiting', from: 'New', item: 'Needs you: ideas waiting for your OK (decided on Go-live)', where: TODAY, roles: OWNER },
  { id: 'proposals-waiting', from: 'New', item: 'Needs you: learning proposals waiting for a decision (decided on Learn)', where: TODAY, roles: OWNER },

  // ---- Classic Dashboard (pages/Dashboard.tsx, /dashboard). Today does not replace it: the classic route stays for
  // accounts without TradeMind until Phase 6. Each feature already has a TradeMind home. ----
  { id: 'classic-status', from: 'Classic Dashboard', item: 'Last scan time, Paper badge, market trend badge, warning banner', where: '/trademind/system', roles: OWNER },
  { id: 'classic-refresh', from: 'Classic Dashboard', item: 'Refresh now', where: '/trademind/control', roles: OWNER },
  { id: 'classic-attention-bot', from: 'Classic Dashboard', item: "Bot's own trades to look at (sell / alert / weak / near stop)", where: '/trademind/positions', roles: ALL },
  { id: 'classic-attention-real', from: 'Classic Dashboard', item: 'Your own Zerodha shares that need a decision', where: '/trademind/holdings', roles: OWNER, realAccount: true },
  { id: 'classic-worth-buying', from: 'Classic Dashboard', item: 'Worth buying today', where: '/trademind/opportunities', roles: ALL },
  { id: 'classic-tier-performance', from: 'Classic Dashboard', item: 'How each company size did in the last 90 days', where: '/trademind/records', roles: ALL },
  { id: 'classic-strategy-signals', from: 'Classic Dashboard', item: "Per-strategy signals (\"Why isn't more showing up?\"), read only", where: '/trademind/opportunities', roles: SEES_ALL },
  { id: 'classic-recent-exits', from: 'Classic Dashboard', item: 'Recent stop-loss and target exits', where: '/trademind/records', roles: ALL },
  { id: 'classic-stock-detail', from: 'Classic Dashboard', item: "A stock's detail", where: '/trademind/stock/INFY', roles: ALL },
]

/** The classic "full model-ranked watchlist" (POST /ml/predict) is not moved: it is the owner's decision (oa15). */
export const NOT_MOVED = ['classic-ranked-watchlist'] as const
