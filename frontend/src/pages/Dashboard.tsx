import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../api/client'
import type { BuyListRow, DetailedPosition, StrategySignal } from '../api/types'
import { Empty, ErrorBox, Loading } from '../components/Loading'
import Modal from '../components/Modal'
import StockDetailModal, { type StockDetail } from '../components/StockDetailModal'
import { CheckCircleIcon, ChevronRightIcon, CircleXIcon } from '../components/icons'
import { TIERS, tierFor } from '../lib/tiers'
import {
  formatCurrency,
  formatDateTime,
  formatNumber,
  formatPercent,
  formatSignedPercent,
  pnlClass,
} from '../lib/format'

const EXIT_KIND: Record<string, { Icon: typeof CheckCircleIcon; tone: 'pos' | 'neg'; label: string }> = {
  STOP_LOSS_HIT: { Icon: CircleXIcon, tone: 'neg', label: 'stop-loss triggered' },
  TARGET_HIT: { Icon: CheckCircleIcon, tone: 'pos', label: 'hit its profit target' },
}

// One short, plain-English line per card — the model's own action_label is
// often a dense technical sentence ("Losing conviction (45% today) — alert
// already sent (original 5-day call has passed, day 6)"), which is exactly
// the kind of jargon this page exists to hide. That full text still shows up
// in the detail popup on tap; the card face only needs the headline.
const SHORT_REASON: Record<DetailedPosition['action_code'], string> = {
  exit: "The model is no longer backing this position.",
  alert: 'An alert has already been sent about this one.',
  weak: 'Losing steam, but not a sell signal yet.',
  dip: 'Confidence has dipped since you bought it.',
  hold: 'Steady — no change.',
  bullish: 'Still bullish.',
}

// Mirrors the strategy's own thresholds (ml_swing.py default_params) — base
// ML_MIN_CONFIDENCE 0.60, +0.10 whenever NIFTY is in a downtrend. Only used
// by the "advanced" full-model-ranking section below and by the buy-card
// strength tiering; the plain BUY/SELL calls for real money (buy list, held
// positions) come from the actual strategy/portfolio engines, not this page
// re-deriving them.
const EXIT = 0.35
const WATCH_GAP = 0.1
const STRONG_GAP = 0.1

function actionFor(probability: number, held: boolean, buyBar: number) {
  const watch = buyBar - WATCH_GAP
  const strong = buyBar + STRONG_GAP
  if (held && probability <= EXIT) return { label: 'SELL / EXIT', tone: 'sell' as const }
  if (probability >= strong) return { label: 'STRONG BUY', tone: 'buy' as const }
  if (probability >= buyBar) return { label: 'BUY', tone: 'buy' as const }
  if (probability >= watch) return { label: 'WATCH', tone: 'hold' as const }
  return { label: held ? 'HOLD' : 'AVOID', tone: 'hold' as const }
}

function ConfidenceBar({ probability, buyBar }: { probability: number; buyBar: number }) {
  const tier = probability >= buyBar ? 'at' : probability >= buyBar - WATCH_GAP ? 'near' : 'far'
  const pct = Math.max(0, Math.min(100, ((probability - EXIT) / (buyBar - EXIT)) * 100))
  return (
    <span className={`conf-bar conf-${tier}`}>
      <span style={{ width: `${pct}%` }} />
    </span>
  )
}

// A stock only ever reaches the buy list once it's already past the buy bar
// (see BuyListRow's own contract), so "Fair" here still means a real BUY —
// just a fresher, lower-conviction one — never a maybe.
function strengthFor(confidence: number | null, buyBar: number): { label: string; filled: number } {
  if (confidence == null) return { label: 'Buy signal', filled: 1 }
  if (confidence >= buyBar + 0.15) return { label: 'Strong signal', filled: 3 }
  if (confidence >= buyBar + 0.05) return { label: 'Good signal', filled: 2 }
  return { label: 'Fair signal', filled: 1 }
}

// "Confirmed today" vs "Confirmed 2 days ago" — a stock stays on the buy
// list as long as it keeps reconfirming, but a couple of days can still
// pass between reconfirmations; this is what tells you whether the price
// you're seeing is still current before you act on it.
function signalFreshness(generatedAt: string): string {
  const days = Math.floor((Date.now() - new Date(generatedAt).getTime()) / 86_400_000)
  if (days <= 0) return `Confirmed today, ${formatDateTime(generatedAt)}`
  if (days === 1) return 'Confirmed yesterday — check the price has held up'
  return `Confirmed ${days} days ago — check the price has held up`
}

function StrengthBar({ filled }: { filled: number }) {
  return (
    <span className="strength-bar">
      {[0, 1, 2].map((i) => (
        <span key={i} className={`strength-seg${i < filled ? ' filled' : ''}`} />
      ))}
    </span>
  )
}

// The single best current BUY/HOLD candidate in a tier's scan — EXIT signals
// are deliberately excluded here, not just re-labelled: showing an exiting
// stock as a "candidate" under a buying-focused panel reads as a
// contradiction no matter how it's worded, and EXIT's own confidence field
// is inverted (1 - probability, "confidence in exiting") so it isn't even on
// the same scale as a BUY/HOLD confidence. A strategy's own signal list is
// "most recent scan first", so the first time a symbol is seen here is its
// latest score — but that dedup has to happen BEFORE the EXIT filter, or an
// older, stale HOLD row for a symbol whose latest signal is actually EXIT
// could get mistaken for a live candidate.
function topPick(signals: StrategySignal[] | undefined): StrategySignal | null {
  if (!signals?.length) return null
  const seen = new Set<string>()
  let best: StrategySignal | null = null
  for (const s of signals) {
    if (seen.has(s.tradingsymbol)) continue
    seen.add(s.tradingsymbol)
    if (s.signal_type === 'EXIT') continue
    if (s.confidence != null && (!best || s.confidence > (best.confidence ?? -1))) best = s
  }
  return best
}

type RankedRow = {
  instrument_id: number
  symbol: string
  price: number
  probability: number
  ts: string
  held: boolean
  action: { label: string; tone: 'buy' | 'sell' | 'hold' }
}

function TechField({ label, value }: { label: string; value: string }) {
  return (
    <div className="tech-field">
      <span className="tech-label">{label}</span>
      <span className="tech-value">{value}</span>
    </div>
  )
}

function TechnicalGrid({ features }: { features: StrategySignal['features'] }) {
  if (!features) return <p className="sig-detail-note muted">No technical breakdown available for this row yet.</p>
  return (
    <div className="tech-grid">
      {features.model && <TechField label="Model" value={features.model} />}
      {features.probability != null && <TechField label="Raw probability" value={formatPercent(features.probability, 1)} />}
      {features.threshold != null && <TechField label="Effective threshold" value={formatPercent(features.threshold, 0)} />}
      {features.atr_14 != null && <TechField label="ATR (14)" value={formatCurrency(features.atr_14)} />}
      {features.daily_volatility_20 != null && (
        <TechField label="Daily volatility (20)" value={formatPercent(features.daily_volatility_20, 2)} />
      )}
      {features.avg_volume_20 != null && <TechField label="Avg. volume (20)" value={formatNumber(features.avg_volume_20)} />}
      {features.return_5d != null && <TechField label="5-day return" value={formatSignedPercent(features.return_5d, 1)} />}
      {features.bear_market != null && (
        <TechField label="Regime" value={features.bear_market ? 'NIFTY downtrend' : 'neutral / up'} />
      )}
    </div>
  )
}

export default function Dashboard() {
  const queryClient = useQueryClient()
  const summary = useQuery({ queryKey: ['summary'], queryFn: () => api.summary() })
  const positions = useQuery({ queryKey: ['positions'], queryFn: api.positions })
  const buyList = useQuery({ queryKey: ['buyList'], queryFn: api.buyList })
  const regime = useQuery({ queryKey: ['marketRegime'], queryFn: api.marketRegime })
  const status = useQuery({ queryKey: ['status'], queryFn: api.status, refetchInterval: 30_000 })
  const trades = useQuery({
    queryKey: ['trades', 50],
    queryFn: () => api.trades(50),
    refetchInterval: 60_000,
  })
  const refresh = useMutation({
    mutationFn: api.refreshData,
    onSuccess: (data) => {
      queryClient.setQueryData(['status'], data)
      queryClient.invalidateQueries({ queryKey: ['signals'] })
      queryClient.invalidateQueries({ queryKey: ['predictions'] })
      queryClient.invalidateQueries({ queryKey: ['strategySignals'] })
      queryClient.invalidateQueries({ queryKey: ['buyList'] })
      queryClient.invalidateQueries({ queryKey: ['positions'] })
    },
  })

  const [selectedDetail, setSelectedDetail] = useState<StockDetail | null>(null)
  const [tab, setTab] = useState<'attention' | 'buy' | 'exits'>('attention')

  // Advanced section: the full model-ranked watchlist, collapsed by default.
  const [showAdvanced, setShowAdvanced] = useState(false)
  const predictions = useQuery({
    queryKey: ['predictions'],
    queryFn: () => api.predict(true),
    enabled: showAdvanced,
  })
  // Also needed (just the large-cap signals) for the tier comparison on the
  // Buy tab, so its own condition covers both cases rather than adding a
  // second, duplicate query for the same data.
  const strategies = useQuery({
    queryKey: ['strategies'],
    queryFn: api.strategies,
    enabled: showAdvanced || tab === 'buy',
  })
  const mainStrategy = strategies.data?.find((s) => s.name === 'ml_swing_main')
  const mainSignals = useQuery({
    queryKey: ['strategySignals', mainStrategy?.id],
    queryFn: () => api.strategySignals(mainStrategy!.id, mainStrategy!.symbols.length || 60),
    enabled: (showAdvanced || tab === 'buy') && !!mainStrategy,
  })
  const featuresBySymbol = useMemo(
    () => new Map((mainSignals.data ?? []).map((s) => [s.tradingsymbol, s.features])),
    [mainSignals.data],
  )

  // One current best candidate per cap tier, regardless of whether it
  // clears today's buy bar — lets you see for yourself why (say) large-cap
  // isn't showing up in "Worth buying today" instead of it just looking
  // empty/broken. Mid/small-cap each get their own signal fetch since,
  // unlike main, nothing else on this page already pulls their full scan.
  const midStrategy = strategies.data?.find((s) => s.name === 'ml_swing_midcap')
  const smallStrategy = strategies.data?.find((s) => s.name === 'ml_swing_smallcap')
  const midSignals = useQuery({
    queryKey: ['strategySignals', midStrategy?.id],
    queryFn: () => api.strategySignals(midStrategy!.id, midStrategy!.symbols.length || 100),
    enabled: tab === 'buy' && !!midStrategy,
  })
  const smallSignals = useQuery({
    queryKey: ['strategySignals', smallStrategy?.id],
    queryFn: () => api.strategySignals(smallStrategy!.id, smallStrategy!.symbols.length || 100),
    enabled: tab === 'buy' && !!smallStrategy,
  })
  const tierSignalsByMatch: Record<string, StrategySignal[] | undefined> = {
    ml_swing_main: mainSignals.data,
    ml_swing_midcap: midSignals.data,
    ml_swing_smallcap: smallSignals.data,
  }
  const tierPicks = TIERS.map((tier) => ({
    tier,
    pick: topPick(tierSignalsByMatch[tier.match]),
    hasData: (tierSignalsByMatch[tier.match]?.length ?? 0) > 0,
  }))
  const heldSymbols = useMemo(() => new Set((positions.data ?? []).map((p) => p.symbol)), [positions.data])
  const bearMarket = regime.data?.regime === 'bearish'
  const buyBar = 0.6 + (bearMarket ? 0.1 : 0)
  const rankedRows: RankedRow[] = useMemo(
    () =>
      (predictions.data ?? []).map((p) => ({
        ...p,
        held: heldSymbols.has(p.symbol),
        action: actionFor(p.probability, heldSymbols.has(p.symbol), buyBar),
      })),
    [predictions.data, heldSymbols, buyBar],
  )
  const [selectedRankedId, setSelectedRankedId] = useState<number | null>(null)
  const selectedRankedRow = rankedRows.find((r) => r.instrument_id === selectedRankedId)

  if (summary.isLoading) return <Loading />
  if (summary.error) return <ErrorBox error={summary.error} />

  const s = summary.data!
  const st = status.data

  const openPositions = positions.data ?? []
  // Anything the portfolio engine itself is flagging — its own held-position
  // read, not a re-derivation, so it always agrees with the Portfolio page.
  const needsAttention = openPositions.filter((p) => p.action_code === 'exit' || p.action_code === 'alert')
  const watchClosely = openPositions.filter((p) => p.action_code === 'weak' || p.action_code === 'dip')
  const flaggedIds = new Set([...needsAttention, ...watchClosely].map((p) => p.id))
  // A separate, simpler signal from the model's confidence read: price alone,
  // regardless of what the model currently thinks. If it drops further it
  // auto-sells at the stop, so "close to the stop" is worth surfacing on its
  // own even when the model still likes the stock.
  const NEAR_STOP_THRESHOLD = 0.03
  const nearStopLoss = openPositions.filter((p) => {
    if (flaggedIds.has(p.id) || p.stop_loss == null || p.current_price <= 0) return false
    const gap = (p.current_price - p.stop_loss) / p.current_price
    return gap >= 0 && gap <= NEAR_STOP_THRESHOLD
  })
  const attentionCount = needsAttention.length + watchClosely.length + nearStopLoss.length

  const buyRows = (buyList.data ?? []).slice(0, 8)

  const recentExits = (trades.data ?? [])
    .filter((t) => t.exit_reason === 'STOP_LOSS_HIT' || t.exit_reason === 'TARGET_HIT')
    .slice(0, 5)

  return (
    <>
      <div className="page-head">
        <h1>Dashboard</h1>
        <div className="row" style={{ gap: '0.5rem' }}>
          {/* "All good" isn't actionable, so it doesn't need a full banner
              row of its own — just the actual last-scan time next to the
              other status badges, not a vague "up to date" hidden behind a
              hover tooltip (useless on mobile anyway). The moment a scan is
              overdue or something's actually wrong, status_level flips to
              'warning' and the full banner below takes over with the real
              reason — this line only ever appears when there's nothing to
              act on. */}
          {st && st.status_level === 'ok' && (
            <span className="muted" style={{ fontSize: '0.78rem' }}>
              ✅ {st.last_scan_at ? `Scanned ${formatDateTime(st.last_scan_at)}` : 'No scan yet today'}
            </span>
          )}
          <span className={`badge ${s.mode === 'live' ? 'badge-live' : 'badge-paper'}`}>
            {s.mode.toUpperCase()}
          </span>
          {regime.data && regime.data.regime !== 'unknown' && (
            <span className={`badge ${regime.data.regime === 'bullish' ? 'badge-buy' : 'badge-sell'}`}>
              {regime.data.regime.toUpperCase()}
            </span>
          )}
        </div>
      </div>

      {st && st.status_level === 'warning' && (
        <div className="banner banner-warn">
          ⚠️ {st.status_message}
          {st.broker_authenticated && (
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

      {positions.isLoading && <Loading />}
      {positions.error && <ErrorBox error={positions.error} />}

      {/* The tab labels themselves carry the "what needs attention" headline
          (via their counts) — a separate banner repeating the same number
          was just extra height above the fold for no new information. */}
      <div className="row" style={{ gap: '0.5rem', marginBottom: '1.25rem', flexWrap: 'wrap' }}>
        <button
          className={tab === 'attention' ? 'primary' : ''}
          onClick={() => setTab('attention')}
          title="Open positions whose stop, target, or confidence changed enough to be worth a look."
        >
          Needs attention{attentionCount > 0 ? ` (${attentionCount})` : ''}
        </button>
        <button
          className={tab === 'buy' ? 'primary' : ''}
          onClick={() => setTab('buy')}
          title="Fresh BUY signals from today's scan, not yet held. This is informational — the bot decides sizing and timing on its own schedule, there's nothing to click to buy here."
        >
          Worth buying{buyRows.length > 0 ? ` (${buyRows.length})` : ''}
        </button>
        <button
          className={tab === 'exits' ? 'primary' : ''}
          onClick={() => setTab('exits')}
          title="Positions closed in the last 14 days, so you can see whether the exit held up."
        >
          Recent exits{recentExits.length > 0 ? ` (${recentExits.length})` : ''}
        </button>
      </div>

      {tab === 'attention' && (
        <>
          {attentionCount === 0 ? (
            <Empty label="Nothing needs attention — your open positions look fine." />
          ) : (
          <div style={{ marginBottom: '1.5rem' }}>
            {needsAttention.map((p) => (
              <button
                key={p.id}
                className="action-card"
                style={{ width: '100%', textAlign: 'left', display: 'block' }}
                onClick={() =>
                  setSelectedDetail({
                    symbol: p.symbol,
                    tone: 'sell',
                    actionLabel: 'SELL',
                    price: p.current_price,
                    entryPrice: p.entry_price,
                    stopLoss: p.stop_loss,
                    takeProfit: p.take_profit,
                    confidence: p.last_confidence ?? p.entry_confidence,
                    note: p.action_label,
                  })
                }
              >
                <div className="action-card-head">
                  <div className="action-card-left">
                    <span className="pill-action sell">SELL</span>
                    <span className="action-card-symbol">{p.symbol}</span>
                  </div>
                  <span className={pnlClass(p.unrealized_pnl)} style={{ fontSize: '0.82rem', fontWeight: 650 }}>
                    {formatCurrency(p.unrealized_pnl)}
                  </span>
                </div>
                <div className="strength-row">
                  <span className="muted" style={{ fontSize: '0.82rem' }}>Sell around</span>
                  <span className="mono" style={{ fontWeight: 650 }}>{formatCurrency(p.current_price)}</span>
                </div>
                <div className="action-card-reason">{SHORT_REASON[p.action_code]}</div>
              </button>
            ))}
            {watchClosely.map((p) => (
              <button
                key={p.id}
                className="action-card"
                style={{ width: '100%', textAlign: 'left', display: 'block' }}
                onClick={() =>
                  setSelectedDetail({
                    symbol: p.symbol,
                    tone: 'watch',
                    actionLabel: 'WATCH',
                    price: p.current_price,
                    entryPrice: p.entry_price,
                    stopLoss: p.stop_loss,
                    takeProfit: p.take_profit,
                    confidence: p.last_confidence ?? p.entry_confidence,
                    note: p.action_label,
                  })
                }
              >
                <div className="action-card-head">
                  <div className="action-card-left">
                    <span className="pill-action watch">WATCH</span>
                    <span className="action-card-symbol">{p.symbol}</span>
                  </div>
                  <span className={pnlClass(p.unrealized_pnl)} style={{ fontSize: '0.82rem', fontWeight: 650 }}>
                    {formatCurrency(p.unrealized_pnl)}
                  </span>
                </div>
                <div className="strength-row">
                  <span className="muted" style={{ fontSize: '0.82rem' }}>Current price</span>
                  <span className="mono" style={{ fontWeight: 650 }}>{formatCurrency(p.current_price)}</span>
                </div>
                <div className="action-card-reason">{SHORT_REASON[p.action_code]}</div>
              </button>
            ))}
            {nearStopLoss.map((p) => {
              const gap = (p.current_price - p.stop_loss!) / p.current_price
              const shortReason = `${formatPercent(gap, 1)} above its stop-loss — could auto-sell soon.`
              const note = `Price is only ${formatPercent(gap, 1)} above its stop-loss (${formatCurrency(p.stop_loss!)}) — it will auto-sell if it drops further. Decide now: sell ahead of it, or hold and let the stop handle it.`
              return (
                <button
                  key={p.id}
                  className="action-card"
                  style={{ width: '100%', textAlign: 'left', display: 'block' }}
                  onClick={() =>
                    setSelectedDetail({
                      symbol: p.symbol,
                      tone: 'watch',
                      actionLabel: 'NEAR STOP',
                      price: p.current_price,
                      entryPrice: p.entry_price,
                      stopLoss: p.stop_loss,
                      takeProfit: p.take_profit,
                      confidence: p.last_confidence ?? p.entry_confidence,
                      note,
                    })
                  }
                >
                  <div className="action-card-head">
                    <div className="action-card-left">
                      <span className="pill-action watch">NEAR STOP</span>
                      <span className="action-card-symbol">{p.symbol}</span>
                    </div>
                    <span className={pnlClass(p.unrealized_pnl)} style={{ fontSize: '0.82rem', fontWeight: 650 }}>
                      {formatCurrency(p.unrealized_pnl)}
                    </span>
                  </div>
                  <div className="strength-row">
                    <span className="muted" style={{ fontSize: '0.82rem' }}>
                      Current <span className="mono" style={{ fontWeight: 650, color: 'var(--text)' }}>{formatCurrency(p.current_price)}</span>
                    </span>
                    <span className="muted" style={{ fontSize: '0.82rem' }}>
                      Stop-loss <span className="mono neg" style={{ fontWeight: 650 }}>{formatCurrency(p.stop_loss!)}</span>
                    </span>
                  </div>
                  <div className="action-card-reason">{shortReason}</div>
                </button>
              )
            })}
          </div>
          )}
        </>
      )}

      {tab === 'buy' && (
        <>
          <span className="muted" style={{ display: 'block', marginBottom: '0.75rem' }}>
            Fresh BUY signals only — a stock stays here as long as it keeps reconfirming, and drops off
            the moment it doesn't. Tap a card for the full detail.
          </span>
          {buyList.isLoading ? (
            <Loading />
          ) : buyList.error ? (
            <ErrorBox error={buyList.error} />
          ) : buyRows.length === 0 ? (
            <Empty label="Nothing to buy right now — no symbol is currently at a fresh BUY signal." />
          ) : (
        <div style={{ marginBottom: '1.5rem' }}>
          {buyRows.map((row: BuyListRow) => {
            const tier = tierFor(row.strategy_name)
            const strength = strengthFor(row.confidence, buyBar)
            return (
              <button
                key={row.symbol}
                className="action-card"
                style={{ width: '100%', textAlign: 'left', display: 'block' }}
                onClick={() =>
                  setSelectedDetail({
                    symbol: row.symbol,
                    tone: 'buy',
                    actionLabel: 'BUY',
                    price: row.price,
                    stopLoss: row.stop_loss,
                    takeProfit: row.take_profit,
                    confidence: row.confidence,
                    note: row.reason,
                    asOf: row.generated_at,
                  })
                }
              >
                <div className="action-card-head">
                  <div className="action-card-left">
                    <span className="pill-action buy">BUY</span>
                    <span className="action-card-symbol">{row.symbol}</span>
                    {tier && (
                      <span className="badge" style={{ background: `${tier.color}26`, color: tier.color }}>
                        {tier.label}
                      </span>
                    )}
                  </div>
                  <ChevronRightIcon />
                </div>
                <div className="strength-row">
                  <span className="muted mono" style={{ fontSize: '0.86rem' }}>{formatCurrency(row.price)}</span>
                  <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <span className="strength-label">{strength.label}</span>
                    <StrengthBar filled={strength.filled} />
                  </span>
                </div>
                {/* When this was last confirmed — a signal from yesterday's
                    scan may not still reflect today's price, so this is
                    what tells you whether to double-check before entering. */}
                <div className="action-card-reason">{signalFreshness(row.generated_at)}</div>
              </button>
            )
          })}
        </div>
          )}

          {/* Deliberately below the real buy list, and collapsed by default —
              this is diagnostic context for "why is my buy list short/empty",
              not a second set of suggestions. Surfacing it above or beside the
              actual BUY cards read as if the app were recommending these too,
              when a "below the buy bar" pick here is explicitly one the model
              is rejecting. */}
          <details style={{ marginBottom: '1.5rem' }}>
            <summary className="advanced-link-row" style={{ cursor: 'pointer', listStyle: 'none' }}>
              <span>Why isn't more showing up here?</span>
              <ChevronRightIcon />
            </summary>
            <span className="muted" style={{ display: 'block', margin: '0.75rem 0' }}>
              The closest each cap size came today — none of these are suggestions. A stock only
              reaches the BUY list above once it actually clears the bar.
            </span>
            <div className="grid" style={{ gridTemplateColumns: 'repeat(3, minmax(0, 1fr))' }}>
              {tierPicks.map(({ tier, pick, hasData }) => {
                // Only ever a BUY or HOLD candidate here — topPick() already
                // excludes EXIT entirely, so a null pick with real data means
                // this tier's models are bearish across the board right now,
                // not that something failed to load.
                const isHeld = pick ? heldSymbols.has(pick.tradingsymbol) : false
                const statusText = pick?.signal_type === 'BUY' ? 'fresh BUY signal' : isHeld ? 'already held' : 'below the buy bar — not a suggestion'
                const statusTone = pick?.signal_type === 'BUY' ? 'pos' : 'muted'
                return (
                  <div className="card" key={tier.match}>
                    <div className="row" style={{ gap: '0.4rem', marginBottom: '0.3rem' }}>
                      <span style={{ color: tier.color, display: 'flex' }}>
                        <tier.Icon />
                      </span>
                      <span className="stat-label" style={{ margin: 0 }}>{tier.label}</span>
                    </div>
                    {!pick ? (
                      <div className="muted" style={{ fontSize: '0.82rem' }}>
                        {hasData ? 'Nothing to buy — models are bearish here right now' : 'No scan data yet'}
                      </div>
                    ) : (
                      <>
                        <div style={{ fontWeight: 700, fontSize: '1rem' }}>{pick.tradingsymbol}</div>
                        <div style={{ fontSize: '0.82rem', marginTop: '0.2rem' }}>
                          <span style={{ fontWeight: 650 }}>{formatPercent(pick.confidence!, 0)}</span>{' '}
                          <span className={statusTone}>{statusText}</span>
                        </div>
                      </>
                    )}
                  </div>
                )
              })}
            </div>
          </details>
        </>
      )}

      {tab === 'exits' && (
        <>
          {recentExits.length === 0 ? (
            <Empty label="No recent stop-loss or target hits — this fills in the moment one fires." />
          ) : (
          <div className="card" style={{ marginBottom: '1.5rem', padding: '0.25rem 1rem' }}>
            {recentExits.map((t) => {
              const kind = EXIT_KIND[t.exit_reason!]
              return (
                <div className="exit-row" key={t.id}>
                  <span className={`exit-icon ${kind?.tone ?? ''}`}>
                    {kind ? <kind.Icon /> : null}
                  </span>
                  <span className="exit-text">
                    <strong>{t.symbol}</strong>{' '}
                    <span className="muted">sold — {kind?.label ?? t.exit_reason}</span>
                  </span>
                  <span className={pnlClass(t.net_pnl)} style={{ fontSize: '0.82rem', fontWeight: 650 }}>
                    {formatSignedPercent(t.return_pct)}
                  </span>
                </div>
              )
            })}
          </div>
          )}
        </>
      )}

      <details style={{ marginBottom: '1.5rem' }} onToggle={(e) => setShowAdvanced(e.currentTarget.open)}>
        <summary className="advanced-link-row" style={{ cursor: 'pointer', listStyle: 'none' }}>
          <span>Advanced — full model ranking &amp; technical detail</span>
          <ChevronRightIcon />
        </summary>
        {!showAdvanced ? null : predictions.isLoading || strategies.isLoading ? (
          <Loading />
        ) : (
          <>
            <span className="muted" style={{ display: 'block', margin: '0.75rem 0' }}>
              Every symbol the large-cap model scores, ranked by confidence. Buy bar right now:{' '}
              <strong style={{ color: 'var(--text)' }}>{formatPercent(buyBar, 0)}</strong>
              {bearMarket ? ' — raised because NIFTY is currently in a downtrend.' : ''}
              {' '}Click a row for the full technical breakdown.
            </span>
            <div className="table-wrap">
              {!rankedRows.length ? (
                <Empty label="No predictions yet." />
              ) : (
                <table>
                  <thead>
                    <tr>
                      <th>Symbol</th>
                      <th className="num">Price</th>
                      <th
                        className="num"
                        title="How sure the model is about this call, 0-100%. Higher isn't a guarantee — it's a relative ranking against other candidates."
                      >
                        Confidence
                      </th>
                      <th>Status</th>
                      <th>Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rankedRows
                      .slice()
                      .sort((a, b) => b.probability - a.probability)
                      .map((r) => (
                        <tr key={r.instrument_id} className="sig-row" onClick={() => setSelectedRankedId(r.instrument_id)}>
                          <td>
                            <strong>{r.symbol}</strong>
                          </td>
                          <td className="num">{formatCurrency(r.price)}</td>
                          <td className="num">
                            <span className="conf-cell">
                              <span>{formatPercent(r.probability, 1)}</span>
                              <ConfidenceBar probability={r.probability} buyBar={buyBar} />
                            </span>
                          </td>
                          <td>{r.held ? <span className="badge badge-on">holding</span> : <span className="muted">—</span>}</td>
                          <td>
                            <span className={`badge badge-${r.action.tone}`}>{r.action.label}</span>
                          </td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              )}
            </div>
          </>
        )}
      </details>

      {selectedDetail && (
        <StockDetailModal detail={selectedDetail} onClose={() => setSelectedDetail(null)} />
      )}

      {selectedRankedRow && (
        <Modal onClose={() => setSelectedRankedId(null)}>
          <div className="detail-panel">
            <div className="detail-head">
              <div>
                <h2 className="detail-symbol">{selectedRankedRow.symbol}</h2>
                <div className="detail-sub">
                  {selectedRankedRow.held ? 'Currently held' : 'Not held'} · scored {formatDateTime(selectedRankedRow.ts)}
                </div>
              </div>
              <span className={`badge badge-lg badge-${selectedRankedRow.action.tone}`}>
                {selectedRankedRow.action.label}
              </span>
            </div>
            <div className="detail-stat-row">
              <div className="detail-stat">
                <div className="tech-label">Price</div>
                <div className="detail-stat-value">{formatCurrency(selectedRankedRow.price)}</div>
              </div>
              <div className="detail-stat">
                <div className="tech-label">Confidence</div>
                <div className="detail-stat-value">{formatPercent(selectedRankedRow.probability, 1)}</div>
              </div>
              <div className="detail-stat">
                <div className="tech-label">Buy bar</div>
                <div className="detail-stat-value">{formatPercent(buyBar, 0)}</div>
              </div>
            </div>
            <div className="section-label">Technical readout</div>
            <TechnicalGrid features={featuresBySymbol.get(selectedRankedRow.symbol) ?? null} />
          </div>
        </Modal>
      )}
    </>
  )
}
