import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../api/client'
import type { DetailedPosition } from '../api/types'
import { Empty, ErrorBox, Loading } from '../components/Loading'
import { formatCurrency, formatDate, formatPercent, formatSignedPercent, pnlClass } from '../lib/format'

type SortKey = 'unrealized_pnl' | 'unrealized_pnl_pct' | 'day_pnl'
type SortDir = 'asc' | 'desc'

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

export default function Positions() {
  const queryClient = useQueryClient()
  const positions = useQuery({ queryKey: ['positions'], queryFn: api.positions })

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

  return (
    <>
      <div className="page-head">
        <h1>Open positions</h1>
        <div className="row" style={{ gap: '1.5rem' }}>
          <span className="row" style={{ gap: '0.4rem' }}>
            <span className="muted">Total unrealised</span>
            <strong className={pnlClass(totalPnl)}>{formatCurrency(totalPnl)}</strong>
          </span>
          <span className="row" style={{ gap: '0.4rem' }}>
            <span className="muted">Today</span>
            <strong className={pnlClass(dayPnl)}>{formatCurrency(dayPnl)}</strong>
          </span>
        </div>
      </div>

      {close.error && <ErrorBox error={close.error} />}

      <div className="table-wrap">
        {!rows.length ? (
          <Empty label="No open positions." />
        ) : (
          <table>
            <thead>
              <tr>
                <th className="sticky-col">Symbol</th>
                <th>Action</th>
                <th className="num">Qty</th>
                <th className="num">Entry</th>
                <th className="num">Current</th>
                <th className="num">Invested</th>
                <th
                  className="num sortable"
                  onClick={() => toggleSort('unrealized_pnl')}
                  aria-sort={
                    sortKey === 'unrealized_pnl' ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'
                  }
                >
                  P&L
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
                  Return
                  <span className="sort-arrow">
                    {sortKey === 'unrealized_pnl_pct' ? (sortDir === 'asc' ? ' ▲' : ' ▼') : ''}
                  </span>
                </th>
                <th
                  className="num sortable"
                  onClick={() => toggleSort('day_pnl')}
                  aria-sort={sortKey === 'day_pnl' ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'}
                >
                  Today
                  <span className="sort-arrow">
                    {sortKey === 'day_pnl' ? (sortDir === 'asc' ? ' ▲' : ' ▼') : ''}
                  </span>
                </th>
                <th className="num">Stop</th>
                <th className="num">Target</th>
                <th className="num">Holding</th>
                <th className="num">Confidence</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => (
                <tr key={p.id}>
                  <td className="sticky-col">
                    <strong>{p.symbol}</strong>
                    <div className="muted" style={{ fontSize: '0.75rem' }}>
                      {formatDate(p.entry_at)}
                    </div>
                  </td>
                  <td>
                    <span className={`badge ${ACTION_BADGE[p.action_code]}`}>{p.action_code}</span>
                    <div className="muted" style={{ fontSize: '0.75rem', maxWidth: '16rem' }}>
                      {p.action_label}
                    </div>
                  </td>
                  <td className="num">{p.quantity}</td>
                  <td className="num">{formatCurrency(p.entry_price)}</td>
                  <td className="num">{formatCurrency(p.current_price)}</td>
                  <td className="num">{formatCurrency(p.invested)}</td>
                  <td className={`num ${pnlClass(p.unrealized_pnl)}`}>
                    {formatCurrency(p.unrealized_pnl)}
                  </td>
                  <td className={`num ${pnlClass(p.unrealized_pnl)}`}>
                    {formatSignedPercent(p.unrealized_pnl_pct)}
                  </td>
                  <td className={`num ${p.day_pnl == null ? 'muted' : pnlClass(p.day_pnl)}`}>
                    {p.day_pnl == null ? '—' : formatCurrency(p.day_pnl)}
                  </td>
                  <td className="num muted">
                    {p.stop_loss ? formatCurrency(p.stop_loss) : '—'}
                  </td>
                  <td className="num muted">
                    {p.take_profit ? formatCurrency(p.take_profit) : '—'}
                  </td>
                  <td className="num">
                    {p.horizon_days ? `${p.holding_days} / ${p.horizon_days}` : p.holding_days}
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
                      Close
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  )
}
