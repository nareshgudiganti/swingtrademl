import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { api } from '../api/client'
import type { StrategySignal } from '../api/types'
import { Empty, ErrorBox, Loading } from '../components/Loading'
import { BuildingIcon } from '../components/icons'
import { formatCurrency, formatDateTime, formatNumber, formatPercent, formatSignedPercent } from '../lib/format'

// Mirrors the strategy's own thresholds (ml_swing.py default_params) — base
// ML_MIN_CONFIDENCE 0.60, +0.10 whenever NIFTY is in a downtrend
// (bear_market_confidence_boost). Fixed at 0.60/0.70 here used to silently
// diverge from that during a bear market: this page would label a stock
// "BUY" at 62% while the real strategy, needing 70%, would reject it. The
// buy bar now moves with the same regime read the strategy itself uses, so
// the label always means what it says.
const EXIT = 0.35
const WATCH_GAP = 0.10 // how far below the buy bar "WATCH" starts
const STRONG_GAP = 0.10 // how far above the buy bar "STRONG BUY" starts

function actionFor(probability: number, held: boolean, buyBar: number) {
  const watch = buyBar - WATCH_GAP
  const strong = buyBar + STRONG_GAP
  if (held && probability <= EXIT) return { label: 'SELL / EXIT', tone: 'sell' as const }
  if (probability >= strong) return { label: 'STRONG BUY', tone: 'buy' as const }
  if (probability >= buyBar) return { label: 'BUY', tone: 'buy' as const }
  if (probability >= watch) return { label: 'WATCH', tone: 'hold' as const }
  return { label: held ? 'HOLD' : 'AVOID', tone: 'hold' as const }
}

/** Same "how close is this to mattering" scale as the Suggestions page —
 * grey/amber/green from the exit floor up to today's buy bar — so a page
 * full of similar-looking probabilities is scannable without opening rows. */
function ConfidenceBar({ probability, buyBar }: { probability: number; buyBar: number }) {
  const tier = probability >= buyBar ? 'at' : probability >= buyBar - WATCH_GAP ? 'near' : 'far'
  const pct = Math.max(0, Math.min(100, ((probability - EXIT) / (buyBar - EXIT)) * 100))
  return (
    <span className={`conf-bar conf-${tier}`}>
      <span style={{ width: `${pct}%` }} />
    </span>
  )
}

type Row = {
  instrument_id: number
  symbol: string
  price: number
  probability: number
  ts: string
  held: boolean
  action: { label: string; tone: 'buy' | 'sell' | 'hold' }
}

type SortKey = 'symbol' | 'price' | 'probability' | 'held' | 'action' | 'ts'
type SortDir = 'asc' | 'desc'

const RANKING_COLUMNS: { key: SortKey; label: string; num?: boolean; defaultDir: SortDir }[] = [
  { key: 'symbol', label: 'Symbol', defaultDir: 'asc' },
  { key: 'price', label: 'Price', num: true, defaultDir: 'desc' },
  { key: 'probability', label: 'Confidence', num: true, defaultDir: 'desc' },
  { key: 'held', label: 'Status', defaultDir: 'desc' },
  { key: 'action', label: 'Action', defaultDir: 'asc' },
  { key: 'ts', label: 'Scored', defaultDir: 'desc' },
]

function compareRows(a: Row, b: Row, key: SortKey): number {
  if (key === 'action') return a.action.label.localeCompare(b.action.label)
  if (key === 'held') return Number(a.held) - Number(b.held)
  const av = a[key]
  const bv = b[key]
  if (typeof av === 'string' && typeof bv === 'string') return av.localeCompare(bv)
  if (typeof av === 'number' && typeof bv === 'number') return av - bv
  return 0
}

function useSort<T>(rows: T[], compare: (a: T, b: T, key: SortKey) => number, initialKey: SortKey, initialDir: SortDir) {
  const [sortKey, setSortKey] = useState<SortKey>(initialKey)
  const [sortDir, setSortDir] = useState<SortDir>(initialDir)
  const sorted = useMemo(() => {
    const copy = [...rows]
    copy.sort((a, b) => compare(a, b, sortKey) * (sortDir === 'asc' ? 1 : -1))
    return copy
  }, [rows, compare, sortKey, sortDir])
  return { sorted, sortKey, sortDir, setSortKey, setSortDir }
}

function SortableHead({
  columns,
  sortKey,
  sortDir,
  onToggle,
}: {
  columns: { key: SortKey; label: string; num?: boolean; defaultDir: SortDir }[]
  sortKey: SortKey
  sortDir: SortDir
  onToggle: (col: { key: SortKey; label: string; num?: boolean; defaultDir: SortDir }) => void
}) {
  return (
    <tr>
      {columns.map((col) => (
        <th
          key={col.key}
          className={`sortable${col.num ? ' num' : ''}`}
          onClick={() => onToggle(col)}
          aria-sort={sortKey === col.key ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'}
        >
          {col.label}
          <span className="sort-arrow">{sortKey === col.key ? (sortDir === 'asc' ? ' ▲' : ' ▼') : ''}</span>
        </th>
      ))}
      <th />
    </tr>
  )
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

/** One row plus its click-to-expand technical detail — shared by all three
 * tables on this page so "click a BUY/SELL to see the full picture" works
 * everywhere, not just the ranking table. */
function ExpandableRow({
  row,
  features,
  buyBar,
  showStatus,
}: {
  row: Row
  features: StrategySignal['features'] | undefined
  buyBar: number
  showStatus?: boolean
}) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <tr className="sig-row" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <td>
          <strong>{row.symbol}</strong>
        </td>
        <td className="num">{formatCurrency(row.price)}</td>
        <td className="num">
          <span className="conf-cell">
            <span>{formatPercent(row.probability, 1)}</span>
            <ConfidenceBar probability={row.probability} buyBar={buyBar} />
          </span>
        </td>
        {showStatus && (
          <td>
            {row.held ? <span className="badge badge-on">holding</span> : <span className="muted">—</span>}
          </td>
        )}
        <td>
          <span className={`badge badge-${row.action.tone}`}>{row.action.label}</span>
        </td>
        <td className="caret">{open ? '▾' : '▸'}</td>
      </tr>
      {open && (
        <tr className="sig-detail-row">
          <td colSpan={showStatus ? 6 : 5}>
            <div className="sig-detail">
              <div className="sig-detail-line muted">
                <span>Scored {formatDateTime(row.ts)}</span>
                <span>{row.held ? 'Currently held' : 'Not held'}</span>
              </div>
              <TechnicalGrid features={features ?? null} />
            </div>
          </td>
        </tr>
      )}
    </>
  )
}

export default function Recommendations() {
  const models = useQuery({ queryKey: ['models'], queryFn: api.models })
  const positions = useQuery({ queryKey: ['positions'], queryFn: api.positions })
  const predictions = useQuery({ queryKey: ['predictions'], queryFn: () => api.predict(true) })
  const strategies = useQuery({ queryKey: ['strategies'], queryFn: api.strategies })

  // This page always scores the large-cap watchlist (api.predict() defaults
  // to that server-side too), so the banner must name that model
  // specifically — picking "whichever model is ACTIVE" is what let a
  // mid-cap/small-cap promotion silently shadow this page's own numbers.
  const activeModel = models.data?.find(
    (m) => m.status === 'ACTIVE' && m.name === 'swing_classifier',
  )
  const mainStrategy = strategies.data?.find((s) => s.name === 'ml_swing_main')

  // The technical breakdown (ATR, volatility, volume, threshold, regime)
  // isn't part of a plain prediction — it only exists on a real strategy
  // signal. Pull ml_swing_main's latest scan purely to enrich the expanded
  // row view; the ranking/probability data above still comes from predict().
  const mainSignals = useQuery({
    queryKey: ['strategySignals', mainStrategy?.id],
    queryFn: () => api.strategySignals(mainStrategy!.id, mainStrategy!.symbols.length || 60),
    enabled: !!mainStrategy,
  })
  const featuresBySymbol = useMemo(
    () => new Map((mainSignals.data ?? []).map((s) => [s.tradingsymbol, s.features])),
    [mainSignals.data],
  )

  const heldSymbols = useMemo(
    () => new Set((positions.data ?? []).map((p) => p.symbol)),
    [positions.data],
  )

  const regime = useQuery({ queryKey: ['marketRegime'], queryFn: api.marketRegime })
  const bearMarket = regime.data?.regime === 'bearish'
  const buyBar = 0.6 + (bearMarket ? 0.1 : 0)

  const rows: Row[] = useMemo(
    () =>
      (predictions.data ?? []).map((p) => {
        const held = heldSymbols.has(p.symbol)
        return { ...p, held, action: actionFor(p.probability, held, buyBar) }
      }),
    [predictions.data, heldSymbols, buyBar],
  )

  const sellFocus = rows.filter((r) => r.action.label === 'SELL / EXIT')
  const buyFocus = rows
    .filter((r) => r.action.label === 'BUY' || r.action.label === 'STRONG BUY')
    .slice(0, 8)

  const ranking = useSort(rows, compareRows, 'probability', 'desc')

  return (
    <>
      <div className="page-head">
        <h1>Recommendations</h1>
        <button onClick={() => predictions.refetch()} disabled={predictions.isFetching}>
          {predictions.isFetching ? 'Scanning…' : 'Refresh now'}
        </button>
      </div>

      {activeModel ? (
        <div className="banner banner-info" style={{ display: 'flex', gap: '0.9rem', alignItems: 'flex-start' }}>
          <div className="icon-chip chip-accent" style={{ marginTop: '0.1rem' }}>
            <BuildingIcon />
          </div>
          <div>
            <div>
              <strong>
                {activeModel.name}:{activeModel.version}
              </strong>{' '}
              scores the watchlist for a ≥{formatPercent(activeModel.target_return_pct, 1)} move within{' '}
              {activeModel.prediction_horizon_days} trading days — roughly a day to two weeks out. A
              strategy still applies liquidity/volatility filters before acting on any signal. Click
              a row for the full technical breakdown.
            </div>
            <div className="muted" style={{ marginTop: '0.4rem' }}>
              Buy bar right now: <strong style={{ color: 'var(--text)' }}>{formatPercent(buyBar, 0)}</strong>
              {bearMarket
                ? ' — raised from the usual 60% because NIFTY is currently in a downtrend.'
                : ' (normal — NIFTY is not in a downtrend, so no penalty is applied).'}
            </div>
          </div>
        </div>
      ) : (
        <div className="banner banner-warn">
          No active model, so there is nothing to rank yet. Train and activate one on the ML
          Models page first.
        </div>
      )}

      {predictions.error && <ErrorBox error={predictions.error} />}

      {sellFocus.length > 0 && (
        <>
          <h2>Holdings losing conviction — consider selling</h2>
          <div className="table-wrap" style={{ marginBottom: '1.5rem' }}>
            <table>
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th className="num">Price</th>
                  <th className="num">Confidence</th>
                  <th>Action</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {sellFocus.map((r) => (
                  <ExpandableRow row={r} features={featuresBySymbol.get(r.symbol)} buyBar={buyBar} key={r.instrument_id} />
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      <h2>Top focus — buy candidates</h2>
      <span className="muted" style={{ display: 'block', marginBottom: '0.5rem' }}>
        Click a row for the complete picture before you decide on entry
      </span>
      <div className="table-wrap" style={{ marginBottom: '1.5rem' }}>
        {predictions.isLoading ? (
          <Loading />
        ) : !buyFocus.length ? (
          <Empty label="No buy-strength candidates right now. Refresh after the next candle close, or check that the watchlist has enough history." />
        ) : (
          <table>
            <thead>
              <tr>
                <th>Symbol</th>
                <th className="num">Price</th>
                <th className="num">Confidence</th>
                <th>Action</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {buyFocus.map((r) => (
                <ExpandableRow row={r} features={featuresBySymbol.get(r.symbol)} buyBar={buyBar} key={r.instrument_id} />
              ))}
            </tbody>
          </table>
        )}
      </div>

      <h2>Full watchlist ranking</h2>
      <span className="muted" style={{ display: 'block', marginBottom: '0.5rem' }}>
        Click a column to sort, or a row to expand
      </span>
      <div className="table-wrap">
        {predictions.isLoading ? (
          <Loading />
        ) : !rows.length ? (
          <Empty label="No predictions yet. Sync instruments, set a watchlist, backfill history, and train a model first." />
        ) : (
          <table>
            <thead>
              <SortableHead
                columns={RANKING_COLUMNS}
                sortKey={ranking.sortKey}
                sortDir={ranking.sortDir}
                onToggle={(col) => {
                  if (ranking.sortKey === col.key) {
                    ranking.setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
                  } else {
                    ranking.setSortKey(col.key)
                    ranking.setSortDir(col.defaultDir)
                  }
                }}
              />
            </thead>
            <tbody>
              {ranking.sorted.map((r) => (
                <ExpandableRow row={r} features={featuresBySymbol.get(r.symbol)} buyBar={buyBar} showStatus key={r.instrument_id} />
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  )
}
