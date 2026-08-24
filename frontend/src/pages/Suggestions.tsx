import { useEffect, useMemo, useState } from 'react'
import type { CSSProperties } from 'react'
import { useQuery } from '@tanstack/react-query'

import { api } from '../api/client'
import type { DetailedPosition, StrategySignal } from '../api/types'
import { Empty, ErrorBox, Loading } from '../components/Loading'
import Modal from '../components/Modal'
import { LayersIcon, WarningIcon } from '../components/icons'
import { TIERS } from '../lib/tiers'
import {
  formatCurrency,
  formatDate,
  formatDateTime,
  formatNumber,
  formatPercent,
  formatSignedPercent,
  pnlClass,
} from '../lib/format'

/** How close a confidence reading is to actually mattering — the visual
 * scale runs from the exit floor to the buy bar so a page full of HOLD
 * calls is scannable without opening every row. */
function confidenceTier(confidence: number | null): 'far' | 'near' | 'at' {
  if (confidence == null) return 'far'
  if (confidence >= BUY_THRESHOLD) return 'at'
  if (confidence >= BUY_THRESHOLD - WATCH_GAP) return 'near'
  return 'far'
}

function ConfidenceBar({ confidence }: { confidence: number | null }) {
  if (confidence == null) return null
  const pct = Math.max(
    0,
    Math.min(100, ((confidence - EXIT_THRESHOLD) / (BUY_THRESHOLD - EXIT_THRESHOLD)) * 100),
  )
  return (
    <span className={`conf-bar conf-${confidenceTier(confidence)}`}>
      <span style={{ width: `${pct}%` }} />
    </span>
  )
}

/** The real live win-rate once evaluated predictions exist — never a
 * fabricated number. Shows a muted dashed ring in the "not enough data yet"
 * state instead of inventing a percentage. */
function AccuracyRing({ accuracy, sampleSize }: { accuracy: number | null; sampleSize: number }) {
  const r = 22
  const circumference = 2 * Math.PI * r
  if (accuracy == null || sampleSize === 0) {
    return (
      <div className="ring-wrap">
        <svg width="52" height="52" viewBox="0 0 52 52">
          <circle
            cx="26"
            cy="26"
            r={r}
            fill="none"
            stroke="var(--border)"
            strokeWidth="4"
            strokeDasharray="4 6"
            strokeLinecap="round"
          />
        </svg>
        <div className="ring-note">tracking live</div>
      </div>
    )
  }
  const offset = circumference * (1 - accuracy)
  return (
    <div className="ring-wrap">
      <svg width="52" height="52" viewBox="0 0 52 52">
        <circle className="ring-track" cx="26" cy="26" r={r} fill="none" strokeWidth="4" />
        <circle
          cx="26"
          cy="26"
          r={r}
          fill="none"
          stroke="var(--pos)"
          strokeWidth="4"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
        />
      </svg>
      <div className="ring-note" style={{ color: 'var(--pos)', fontSize: '0.85rem' }}>
        {formatPercent(accuracy, 0)}
      </div>
    </div>
  )
}

const BUY_THRESHOLD = 0.7 // settings.ML_MIN_CONFIDENCE (0.6) + bear-market boost (0.1) — see ml_swing.py
const EXIT_THRESHOLD = 0.35 // strategy's exit_confidence default — the floor the confidence bar below reads from
const WATCH_GAP = 0.1 // how far below the buy bar still counts as "near" rather than "far"

type Call = 'BUY' | 'SELL' | 'HOLD'

interface SuggestionRow {
  key: string
  symbol: string
  call: Call
  confidence: number | null
  date: string
  price: number
  stopLoss: number | null
  takeProfit: number | null
  reason: string | null
  held: boolean
  entryPrice: number | null
  currentPrice: number | null
  pnlPct: number | null
  holdingDays: number | null
  horizonDays: number | null
}

// A held position's own daily re-read (action_code) is the call, since that
// reflects today's fresh confidence — not whatever it was bought at.
function callFromActionCode(code: DetailedPosition['action_code']): Call {
  if (code === 'bullish') return 'BUY'
  if (code === 'hold') return 'HOLD'
  return 'SELL' // exit, alert, weak, dip — all "losing conviction" in one direction
}

function buildRows(
  strategyId: number | undefined,
  signals: StrategySignal[] | undefined,
  positions: DetailedPosition[],
): SuggestionRow[] {
  const held = positions
    .filter((p) => p.strategy_id === strategyId)
    .map(
      (p): SuggestionRow => ({
        key: `pos-${p.id}`,
        symbol: p.symbol,
        call: callFromActionCode(p.action_code),
        confidence: p.last_confidence,
        date: p.entry_at,
        price: p.current_price,
        stopLoss: p.stop_loss,
        takeProfit: p.take_profit,
        reason: p.action_label,
        held: true,
        entryPrice: p.entry_price,
        currentPrice: p.current_price,
        pnlPct: p.unrealized_pnl_pct,
        holdingDays: p.holding_days,
        horizonDays: p.horizon_days,
      }),
    )

  const heldSymbols = new Set(held.map((r) => r.symbol))
  const watch = (signals ?? [])
    .filter((s) => s.signal_type === 'HOLD' && !heldSymbols.has(s.tradingsymbol) && (s.confidence ?? 0) > 0)
    .sort((a, b) => (b.confidence ?? 0) - (a.confidence ?? 0))
    .slice(0, 10)
    .map(
      (s): SuggestionRow => ({
        key: `sig-${s.id}`,
        symbol: s.tradingsymbol,
        call: 'HOLD',
        confidence: s.confidence,
        date: s.generated_at,
        price: s.price,
        stopLoss: null,
        takeProfit: null,
        reason: s.reason,
        held: false,
        entryPrice: null,
        currentPrice: null,
        pnlPct: null,
        holdingDays: null,
        horizonDays: null,
      }),
    )

  return [...held, ...watch]
}

const callBadgeClass: Record<Call, string> = { BUY: 'badge-buy', SELL: 'badge-sell', HOLD: 'badge-hold' }

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
      {features.probability != null && (
        <TechField label="Raw probability" value={formatPercent(features.probability, 1)} />
      )}
      {features.threshold != null && (
        <TechField label="Effective threshold" value={formatPercent(features.threshold, 0)} />
      )}
      {features.atr_14 != null && <TechField label="ATR (14)" value={formatCurrency(features.atr_14)} />}
      {features.daily_volatility_20 != null && (
        <TechField label="Daily volatility (20)" value={formatPercent(features.daily_volatility_20, 2)} />
      )}
      {features.avg_volume_20 != null && (
        <TechField label="Avg. volume (20)" value={formatNumber(features.avg_volume_20)} />
      )}
      {features.return_5d != null && (
        <TechField label="5-day return" value={formatSignedPercent(features.return_5d, 1)} />
      )}
      {features.bear_market != null && (
        <TechField label="Regime" value={features.bear_market ? 'NIFTY downtrend' : 'neutral / up'} />
      )}
    </div>
  )
}

/** Rendered inside the popup a row click opens — full width there, not
 * squeezed into a table cell, so the technical grid actually has room to
 * lay out in multiple columns. */
function DetailPanel({ row, features }: { row: SuggestionRow; features: StrategySignal['features'] }) {
  return (
    <div className="detail-panel">
      <div className="detail-head">
        <div>
          <h2 className="detail-symbol">{row.symbol}</h2>
          <div className="detail-sub">
            {row.held ? 'Currently held' : 'Not held'} · scored {formatDateTime(row.date)}
          </div>
        </div>
        <span className={`badge badge-lg ${callBadgeClass[row.call]}`}>{row.call}</span>
      </div>

      {row.held ? (
        <>
          <div className="detail-stat-row">
            <div className="detail-stat">
              <div className="tech-label">Entry</div>
              <div className="detail-stat-value">{formatCurrency(row.entryPrice!)}</div>
            </div>
            <div className="detail-stat">
              <div className="tech-label">Now</div>
              <div className={`detail-stat-value ${pnlClass(row.pnlPct ?? 0)}`}>
                {formatCurrency(row.currentPrice!)}
              </div>
            </div>
            <div className="detail-stat">
              <div className="tech-label">P&amp;L</div>
              <div className={`detail-stat-value ${pnlClass(row.pnlPct ?? 0)}`}>
                {formatSignedPercent(row.pnlPct ?? 0)}
              </div>
            </div>
          </div>
          {row.stopLoss != null && row.takeProfit != null && (
            <div className="detail-stat-row">
              <div className="detail-stat">
                <div className="tech-label">Stop-loss</div>
                <div className="detail-stat-value neg">{formatCurrency(row.stopLoss)}</div>
              </div>
              <div className="detail-stat">
                <div className="tech-label">Target</div>
                <div className="detail-stat-value pos">{formatCurrency(row.takeProfit)}</div>
              </div>
              <div className="detail-stat">
                <div className="tech-label">Day</div>
                <div className="detail-stat-value">
                  {row.holdingDays} of {row.horizonDays ?? '—'}
                </div>
              </div>
            </div>
          )}
          {row.horizonDays != null && (row.holdingDays ?? 0) > row.horizonDays && (
            <p className="sig-detail-note muted">
              Original {row.horizonDays}-day call has passed — the model re-reads confidence daily regardless.
            </p>
          )}
        </>
      ) : (
        <div className="detail-stat-row">
          <div className="detail-stat">
            <div className="tech-label">Price</div>
            <div className="detail-stat-value">{formatCurrency(row.price)}</div>
          </div>
          <div className="detail-stat">
            <div className="tech-label">Confidence</div>
            <div className="detail-stat-value">
              {row.confidence != null ? formatPercent(row.confidence, 1) : '—'}
            </div>
          </div>
          <div className="detail-stat">
            <div className="tech-label">Buy bar</div>
            <div className="detail-stat-value">{formatPercent(BUY_THRESHOLD, 0)}</div>
          </div>
        </div>
      )}

      <p className="detail-reason">{row.reason}</p>

      <div className="section-label">Technical readout</div>
      <TechnicalGrid features={features} />
    </div>
  )
}

export default function Suggestions() {
  const strategies = useQuery({ queryKey: ['strategies'], queryFn: api.strategies })
  const positions = useQuery({ queryKey: ['positions'], queryFn: api.positions })
  const regime = useQuery({ queryKey: ['marketRegime'], queryFn: api.marketRegime })
  const models = useQuery({ queryKey: ['models'], queryFn: api.models })

  const [activeTierIdx, setActiveTierIdx] = useState(0)
  const [selectedKey, setSelectedKey] = useState<string | null>(null)

  const tierStrategies = useMemo(() => {
    const list = strategies.data ?? []
    return TIERS.map((tier) => ({
      tier,
      strategy: list.find((s) => s.name === tier.match),
    }))
  }, [strategies.data])

  // Large-cap is the only strategy with enough live history to judge —
  // matches the copy the "Accuracy tracking" card already carried before
  // this had a real number behind it (see the ring below).
  const largeCapModel = models.data?.find(
    (m) => m.status === 'ACTIVE' && m.name === 'swing_classifier',
  )
  const accuracy = useQuery({
    queryKey: ['predictionAccuracy', largeCapModel?.id],
    queryFn: () => api.predictionAccuracy(largeCapModel!.id),
    enabled: !!largeCapModel,
  })

  // One signals query per tier, each gated on that tier's strategy existing
  // and sized to its own universe so the newest scan batch is exactly what
  // comes back (see api.strategySignals — ordering makes this safe).
  const largeSignals = useQuery({
    queryKey: ['strategySignals', tierStrategies[0]?.strategy?.id],
    queryFn: () => api.strategySignals(tierStrategies[0]!.strategy!.id, tierStrategies[0]!.strategy!.symbols.length || 60),
    enabled: !!tierStrategies[0]?.strategy,
  })
  const midSignals = useQuery({
    queryKey: ['strategySignals', tierStrategies[1]?.strategy?.id],
    queryFn: () => api.strategySignals(tierStrategies[1]!.strategy!.id, tierStrategies[1]!.strategy!.symbols.length || 40),
    enabled: !!tierStrategies[1]?.strategy,
  })
  const smallSignals = useQuery({
    queryKey: ['strategySignals', tierStrategies[2]?.strategy?.id],
    queryFn: () => api.strategySignals(tierStrategies[2]!.strategy!.id, tierStrategies[2]!.strategy!.symbols.length || 40),
    enabled: !!tierStrategies[2]?.strategy,
  })
  const signalsByTier = [largeSignals, midSignals, smallSignals]

  const activeSignals = signalsByTier[activeTierIdx]?.data
  const activeStrategy = tierStrategies[activeTierIdx]?.strategy
  const rows = useMemo(
    () => buildRows(activeStrategy?.id, activeSignals, positions.data ?? []),
    [activeStrategy, activeSignals, positions.data],
  )
  const featuresBySymbol = useMemo(
    () => new Map((activeSignals ?? []).map((s) => [s.tradingsymbol, s.features])),
    [activeSignals],
  )

  // Switching tabs closes any open modal — its row belongs to the tier you
  // just left, and reopening it against the new tier's data would be showing
  // the wrong stock's detail under a stale selection.
  useEffect(() => {
    setSelectedKey(null)
  }, [activeTierIdx])

  if (strategies.isLoading || positions.isLoading) return <Loading />
  if (strategies.error) return <ErrorBox error={strategies.error} />
  if (positions.error) return <ErrorBox error={positions.error} />

  const missingTiers = tierStrategies.filter((t) => !t.strategy)
  const bearMarket = regime.data?.regime === 'bearish'
  const selectedRow = rows.find((r) => r.key === selectedKey)

  return (
    <>
      <div className="page-head">
        <h1>Suggestions</h1>
        <span className="muted">Pick a tier — click a row only if you want the full technical detail</span>
      </div>

      {missingTiers.length > 0 && (
        <div className="banner banner-warn">
          {missingTiers.map((t) => t.tier.label).join(', ')} strategy not found — expected a strategy named{' '}
          {missingTiers.map((t) => `"${t.tier.match}"`).join(' / ')}.
        </div>
      )}

      <div className="grid">
        <div className="card card-with-icon">
          <div>
            <div className="stat-label">Market regime</div>
            <div className="stat-value">
              <span className={`badge ${bearMarket ? 'badge-recommend' : 'badge-on'}`}>
                {bearMarket ? 'NIFTY downtrend' : 'neutral / up'}
              </span>
            </div>
            {bearMarket && (
              <div className="stat-sub">Buy threshold raised system-wide (60% → 70%) until this clears</div>
            )}
          </div>
          <div className={`icon-chip ${bearMarket ? 'chip-warn' : 'chip-accent'}`}>
            <WarningIcon />
          </div>
        </div>
        <div className="card card-with-icon">
          <div>
            <div className="stat-label">Open positions</div>
            <div className="stat-value">{positions.data?.length ?? 0}</div>
            <div className="stat-sub">
              {tierStrategies
                .map((t) => `${(positions.data ?? []).filter((p) => p.strategy_id === t.strategy?.id).length} ${t.tier.label.toLowerCase()}`)
                .join(' · ')}
            </div>
          </div>
          <div className="icon-chip chip-accent">
            <LayersIcon />
          </div>
        </div>
        <div className="card card-with-icon">
          <div>
            <div className="stat-label">Accuracy tracking</div>
            <div className="stat-value" style={{ fontSize: '0.95rem' }}>
              Large-cap only
            </div>
            <div className="stat-sub">
              {accuracy.data && accuracy.data.evaluated_predictions > 0
                ? `${accuracy.data.correct} of ${accuracy.data.evaluated_predictions} evaluated calls correct`
                : 'Mid/small-cap run on their training backtest only — no live win-rate yet'}
            </div>
          </div>
          <AccuracyRing
            accuracy={accuracy.data?.accuracy ?? null}
            sampleSize={accuracy.data?.evaluated_predictions ?? 0}
          />
        </div>
      </div>

      <div className="tier-tabs">
        {tierStrategies.map(({ tier, strategy }, i) => {
          const count = signalsByTier[i]?.data
            ? buildRows(strategy?.id, signalsByTier[i]?.data, positions.data ?? []).length
            : null
          return (
            <button
              key={tier.match}
              className={`tier-tab ${i === activeTierIdx ? 'active' : ''}`}
              onClick={() => setActiveTierIdx(i)}
              style={{ '--tier-color': tier.color } as CSSProperties}
            >
              <span className="tier-tab-icon">
                <tier.Icon />
              </span>
              {tier.label}
              {count != null && <span className="tier-tab-count">{count}</span>}
            </button>
          )
        })}
      </div>

      {rows.length === 0 ? (
        <Empty label="Nothing to show — no positions and nothing close to a buy signal in this tier." />
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Call</th>
                <th className="num">Confidence</th>
                <th className="num">Price</th>
                <th>Date</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.key} className="sig-row" onClick={() => setSelectedKey(row.key)}>
                  <td>
                    <span className="sym">
                      {row.symbol}
                      {row.held && <span className="held-tag">held</span>}
                    </span>
                  </td>
                  <td>
                    <span className={`badge ${callBadgeClass[row.call]}`}>{row.call}</span>
                  </td>
                  <td className="num">
                    <span className="conf-cell">
                      <span className="mono">{row.confidence != null ? formatPercent(row.confidence, 0) : '—'}</span>
                      <ConfidenceBar confidence={row.confidence} />
                    </span>
                  </td>
                  <td className="num mono">{formatCurrency(row.price)}</td>
                  <td className="muted">{formatDate(row.date)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {selectedRow && (
        <Modal onClose={() => setSelectedKey(null)}>
          <DetailPanel row={selectedRow} features={featuresBySymbol.get(selectedRow.symbol) ?? null} />
        </Modal>
      )}
    </>
  )
}
