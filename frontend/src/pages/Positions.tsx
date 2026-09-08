import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../api/client'
import type { DetailedPosition } from '../api/types'
import Stat from '../components/Stat'
import { Empty, ErrorBox, Loading } from '../components/Loading'
import StockDetailModal, { type StockDetail } from '../components/StockDetailModal'
import { formatCurrency, formatDate, formatPercent, formatSignedPercent, pnlClass } from '../lib/format'

const DAYS_TO_WATCH = 14

function sinceExitClass(returnPct: number | null): string {
  if (returnPct === null) return 'muted'
  return pnlClass(-returnPct)
}

function daysSince(iso: string): number {
  return Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000)
}

type SortKey = 'unrealized_pnl' | 'unrealized_pnl_pct' | 'day_pnl'
type SortDir = 'asc' | 'desc'

// day_pnl is always "current price vs. the previous trading day's close",
// where "current" means the market's IST calendar date — not the viewer's
// local one — so the label under it must be pinned to IST too.
const todayIst = () =>
  new Date().toLocaleDateString('en-IN', { day: '2-digit', month: 'short', timeZone: 'Asia/Kolkata' })

// day_pnl is an absolute rupee amount, not a %, so "yesterday's value" is
// backed out as current minus today's move — there's no previous-close price
// on this type to divide by directly.
function dayChangePct(p: DetailedPosition): number | null {
  if (p.day_pnl == null) return null
  const prevValue = p.current_value - p.day_pnl
  if (!prevValue) return null
  return p.day_pnl / prevValue
}

// Escalation by the model's CURRENT confidence, not by elapsed time: green
// means it's still bullish today, grey is unremarkable/early, amber is
// fading toward the exit floor, red is a real exit signal or an alert
// already sent — matches the badge classes already used elsewhere.
const ACTION_BADGE: Record<DetailedPosition['action_code'], string> = {
  exit: 'badge-sell',
  alert: 'badge-sell',
  weak: 'badge-recommend',
  dip: 'badge-hold',
  hold: 'badge-hold',
  bullish: 'badge-buy',
}

// Raw action_code values ("bullish", "dip") read as debug labels in a badge
// — this is the short human word for each, the detail sentence lives below
// it in the row instead of being crammed into the pill itself.
const ACTION_LABEL_TEXT: Record<DetailedPosition['action_code'], string> = {
  exit: 'Exit signal',
  alert: 'Alert sent',
  weak: 'Weakening',
  dip: 'Confidence dip',
  hold: 'Hold',
  bullish: 'Bullish',
}

const ACTION_TONE: Record<DetailedPosition['action_code'], StockDetail['tone']> = {
  exit: 'sell',
  alert: 'sell',
  weak: 'watch',
  dip: 'watch',
  hold: 'hold',
  bullish: 'buy',
}

export default function Positions() {
  const queryClient = useQueryClient()
  const positions = useQuery({ queryKey: ['positions'], queryFn: api.positions })
  const trades = useQuery({ queryKey: ['trades', 50], queryFn: () => api.trades(50) })
  const buyList = useQuery({ queryKey: ['buyList'], queryFn: api.buyList })
  const buySymbols = useMemo(() => new Set((buyList.data ?? []).map((r) => r.symbol)), [buyList.data])
  const recentlySold = useMemo(
    () => (trades.data ?? []).filter((t) => daysSince(t.exit_at) <= DAYS_TO_WATCH),
    [trades.data],
  )

  const close = useMutation({
    mutationFn: (id: number) => api.closePosition(id),
    onSuccess: () => {
      // A close writes a Trade and moves cash, so the summary and trade list
      // are stale too — not just the position list.
      queryClient.invalidateQueries({ queryKey: ['positions'] })
      queryClient.invalidateQueries({ queryKey: ['summary'] })
      queryClient.invalidateQueries({ queryKey: ['trades'] })
    },
  })

  const [sortKey, setSortKey] = useState<SortKey | null>(null)
  const [sortDir, setSortDir] = useState<SortDir>('desc')
  const [selectedDetail, setSelectedDetail] = useState<StockDetail | null>(null)

  const unsorted = positions.data ?? []
  // Missing day_pnl (no previous close yet) sorts last regardless of
  // direction — it isn't "zero", it's just not comparable yet.
  const rows = useMemo(() => {
    if (!sortKey) return unsorted
    const data = [...unsorted]
    data.sort((a, b) => {
      const av = a[sortKey]
      const bv = b[sortKey]
      if (av == null && bv == null) return 0
      if (av == null) return 1
      if (bv == null) return -1
      return (av - bv) * (sortDir === 'asc' ? 1 : -1)
    })
    return data
  }, [unsorted, sortKey, sortDir])

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortDir('desc')
    }
  }

  if (positions.isLoading) return <Loading />
  if (positions.error) return <ErrorBox error={positions.error} />

  const totalPnl = unsorted.reduce((sum, p) => sum + p.unrealized_pnl, 0)
  const dayPnl = unsorted.reduce((sum, p) => sum + (p.day_pnl ?? 0), 0)
  const invested = unsorted.reduce((sum, p) => sum + p.invested, 0)
  const currentValue = unsorted.reduce((sum, p) => sum + p.current_value, 0)
  const absoluteReturnPct = invested ? totalPnl / invested : 0

  const bySizeOfReturn = [...unsorted].sort((a, b) => b.unrealized_pnl_pct - a.unrealized_pnl_pct)
  const maxGainer = bySizeOfReturn[0]
  const maxLoser = bySizeOfReturn[bySizeOfReturn.length - 1]

  return (
    <>
      <div className="page-head">
        <h1>Portfolio</h1>
      </div>

      {close.error && <ErrorBox error={close.error} />}

      {rows.length > 0 && (
        <div className="grid">
          <Stat label="Amount invested" value={formatCurrency(invested)} />
          <Stat label="Current value" value={formatCurrency(currentValue)} />
          <Stat
            label="Day's gain"
            value={formatCurrency(dayPnl)}
            sub={todayIst()}
            tone={pnlClass(dayPnl) as 'pos' | 'neg' | 'flat'}
          />
          <Stat
            label="Absolute return"
            value={formatSignedPercent(absoluteReturnPct)}
            sub={formatCurrency(totalPnl)}
            tone={pnlClass(totalPnl) as 'pos' | 'neg' | 'flat'}
          />
          {maxGainer && maxGainer.unrealized_pnl_pct > 0 && (
            <Stat
              label="Max gainer"
              value={maxGainer.symbol}
              sub={`${formatCurrency(maxGainer.current_price)}  (${formatSignedPercent(maxGainer.unrealized_pnl_pct)})`}
              tone="pos"
            />
          )}
          {maxLoser && maxLoser.unrealized_pnl_pct < 0 && (
            <Stat
              label="Max loser"
              value={maxLoser.symbol}
              sub={`${formatCurrency(maxLoser.current_price)}  (${formatSignedPercent(maxLoser.unrealized_pnl_pct)})`}
              tone="neg"
            />
          )}
        </div>
      )}

      <div className="table-wrap">
        {!rows.length ? (
          <Empty label="No open positions." />
        ) : (
          <table>
            <thead>
              <tr>
                <th className="sticky-col">Stock</th>
                <th className="num">Qty</th>
                <th className="num">Avg cost</th>
                <th className="num">CMP</th>
                <th className="num">% chg</th>
                <th className="num">Value at cost</th>
                <th className="num">Value at CMP</th>
                <th
                  className="num sortable"
                  onClick={() => toggleSort('day_pnl')}
                  aria-sort={sortKey === 'day_pnl' ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'}
                >
                  Day&apos;s P&amp;L
                  <span className="sort-arrow">
                    {sortKey === 'day_pnl' ? (sortDir === 'asc' ? ' ▲' : ' ▼') : ''}
                  </span>
                </th>
                <th
                  className="num sortable"
                  onClick={() => toggleSort('unrealized_pnl')}
                  aria-sort={
                    sortKey === 'unrealized_pnl' ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'
                  }
                >
                  Overall P&amp;L
                  <span className="sort-arrow">
                    {sortKey === 'unrealized_pnl' ? (sortDir === 'asc' ? ' ▲' : ' ▼') : ''}
                  </span>
                </th>
                <th
                  className="num sortable"
                  onClick={() => toggleSort('unrealized_pnl_pct')}
                  aria-sort={
                    sortKey === 'unrealized_pnl_pct'
                      ? sortDir === 'asc'
                        ? 'ascending'
                        : 'descending'
                      : 'none'
                  }
                >
                  P&amp;L %
                  <span className="sort-arrow">
                    {sortKey === 'unrealized_pnl_pct' ? (sortDir === 'asc' ? ' ▲' : ' ▼') : ''}
                  </span>
                </th>
                <th>Model says</th>
                <th className="num">Stop</th>
                <th className="num">Target</th>
                <th className="num">Confidence</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => {
                const chg = dayChangePct(p)
                return (
                <tr key={p.id}>
                  <td className="sticky-col">
                    <button
                      className="symbol-button"
                      onClick={() =>
                        setSelectedDetail({
                          symbol: p.symbol,
                          tone: ACTION_TONE[p.action_code],
                          actionLabel: ACTION_LABEL_TEXT[p.action_code],
                          price: p.current_price,
                          entryPrice: p.entry_price,
                          stopLoss: p.stop_loss,
                          takeProfit: p.take_profit,
                          confidence: p.last_confidence ?? p.entry_confidence,
                          note: p.action_label,
                        })
                      }
                    >
                      {p.symbol}
                    </button>
                    <div className="muted" style={{ fontSize: '0.75rem' }}>
                      Since {formatDate(p.entry_at)}
                    </div>
                  </td>
                  <td className="num">{p.quantity}</td>
                  <td className="num">{formatCurrency(p.entry_price)}</td>
                  <td className="num">{formatCurrency(p.current_price)}</td>
                  <td className={`num ${chg == null ? 'muted' : pnlClass(chg)}`}>
                    {chg == null ? '—' : formatSignedPercent(chg)}
                  </td>
                  <td className="num">{formatCurrency(p.invested)}</td>
                  <td className="num">{formatCurrency(p.current_value)}</td>
                  <td className={`num ${p.day_pnl == null ? 'muted' : pnlClass(p.day_pnl)}`}>
                    {p.day_pnl == null ? '—' : formatCurrency(p.day_pnl)}
                  </td>
                  <td className={`num ${pnlClass(p.unrealized_pnl)}`}>
                    {formatCurrency(p.unrealized_pnl)}
                  </td>
                  <td className={`num ${pnlClass(p.unrealized_pnl)}`}>
                    {formatSignedPercent(p.unrealized_pnl_pct)}
                  </td>
                  <td>
                    {/* Full reason is one click away (the symbol button
                        opens the detail popup) — a second wrapped line here
                        was just making every row taller for no new info. */}
                    <span className={`badge ${ACTION_BADGE[p.action_code]}`} title={p.action_label}>
                      {ACTION_LABEL_TEXT[p.action_code]}
                    </span>
                  </td>
                  <td className="num muted">
                    {p.stop_loss ? formatCurrency(p.stop_loss) : '—'}
                  </td>
                  <td className="num muted">
                    {p.take_profit ? formatCurrency(p.take_profit) : '—'}
                  </td>
                  <td className="num">
                    {p.entry_confidence == null ? (
                      <span className="muted">—</span>
                    ) : (
                      <span
                        className={
                          p.last_confidence != null && p.last_confidence < p.entry_confidence - 0.1
                            ? 'neg'
                            : undefined
                        }
                        title="Entry confidence → most recently seen confidence"
                      >
                        {formatPercent(p.entry_confidence, 0)}
                        {p.last_confidence != null && ` → ${formatPercent(p.last_confidence, 0)}`}
                      </span>
                    )}
                  </td>
                  <td>
                    <button
                      className="danger"
                      disabled={close.isPending}
                      onClick={() => {
                        if (confirm(`Close ${p.quantity} × ${p.symbol} at market?`)) {
                          close.mutate(p.id)
                        }
                      }}
                    >
                      Sell
                    </button>
                  </td>
                </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>

      <h2>Recently sold — still watching</h2>
      <span className="muted" style={{ display: 'block', marginBottom: '0.75rem' }}>
        Anything sold in the last {DAYS_TO_WATCH} days, so you can see whether the exit held up —
        and whether the model would buy it back today.
      </span>
      {trades.isLoading ? (
        <Loading />
      ) : trades.error ? (
        <ErrorBox error={trades.error} />
      ) : !recentlySold.length ? (
        <Empty label={`No sales in the last ${DAYS_TO_WATCH} days.`} />
      ) : (
        <div>
          {recentlySold.map((t) => {
            // Headline whichever checkpoint has actually arrived — 15
            // sessions once there's been time, 5 in the meantime, otherwise
            // there's nothing to show yet ("still tracking").
            const primaryReturn = t.return_15d_after_exit ?? t.return_5d_after_exit ?? null
            const primaryLabel =
              t.return_15d_after_exit !== null ? '15 sessions since' : '5 sessions since'
            const wouldBuyBack = buySymbols.has(t.symbol)
            const sinceSoldNote =
              primaryReturn !== null
                ? `${primaryLabel} you sold: ${formatSignedPercent(primaryReturn)}.`
                : 'Still tracking — check back in a few days.'
            return (
              <button
                key={t.id}
                className="action-card"
                style={{ width: '100%', textAlign: 'left', display: 'block' }}
                onClick={() =>
                  setSelectedDetail({
                    symbol: t.symbol,
                    tone: wouldBuyBack ? 'buy' : 'hold',
                    actionLabel: wouldBuyBack ? 'WOULD BUY BACK' : 'NOT A BUY SIGNAL',
                    price: t.exit_price,
                    entryPrice: t.entry_price,
                    stopLoss: t.stop_loss,
                    takeProfit: t.take_profit,
                    confidence: t.last_confidence ?? t.entry_confidence,
                    note: `Sold ${formatDate(t.exit_at)} (${daysSince(t.exit_at)}d ago) — ${t.exit_reason_label ?? t.exit_reason ?? '—'}. ${sinceSoldNote}`,
                  })
                }
              >
                <div className="action-card-head">
                  <div className="action-card-left">
                    <span className="action-card-symbol">{t.symbol}</span>
                    <span className="muted" style={{ fontSize: '0.78rem' }}>
                      {t.exit_reason_label ?? t.exit_reason ?? '—'}
                    </span>
                  </div>
                  <span className={`pill-action ${wouldBuyBack ? 'buy' : 'neutral'}`}>
                    {wouldBuyBack ? 'WOULD BUY BACK' : 'NOT A BUY SIGNAL'}
                  </span>
                </div>
                <div className="action-card-reason">
                  Sold {formatDate(t.exit_at)} ({daysSince(t.exit_at)}d ago) at {formatCurrency(t.exit_price)}
                  {' · '}
                  {primaryReturn !== null ? (
                    <span className={sinceExitClass(primaryReturn)} style={{ fontWeight: 650 }}>
                      {primaryLabel} {formatSignedPercent(primaryReturn)}
                    </span>
                  ) : (
                    'still tracking'
                  )}
                </div>
              </button>
            )
          })}
        </div>
      )}

      {selectedDetail && (
        <StockDetailModal detail={selectedDetail} onClose={() => setSelectedDetail(null)} />
      )}
    </>
  )
}
