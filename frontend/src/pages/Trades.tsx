import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'

import { api } from '../api/client'
import type { Trade } from '../api/types'
import { Empty, ErrorBox, Loading } from '../components/Loading'
import { formatCurrency, formatDate, formatSignedPercent, pnlClass } from '../lib/format'

interface MonthRow {
  key: string
  label: string
  trades: number
  wins: number
  gross: number
  charges: number
  net: number
}

function monthlyBreakdown(rows: Trade[]): MonthRow[] {
  const byMonth = new Map<string, MonthRow>()
  for (const t of rows) {
    const d = new Date(t.exit_at)
    const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
    const label = d.toLocaleDateString('en-IN', { month: 'short', year: 'numeric' })
    const m = byMonth.get(key) ?? { key, label, trades: 0, wins: 0, gross: 0, charges: 0, net: 0 }
    m.trades += 1
    m.wins += t.is_win ? 1 : 0
    m.gross += t.gross_pnl
    m.charges += t.charges
    m.net += t.net_pnl
    byMonth.set(key, m)
  }
  return [...byMonth.values()].sort((a, b) => b.key.localeCompare(a.key))
}

export default function Trades() {
  const trades = useQuery({ queryKey: ['trades'], queryFn: () => api.trades(200) })

  const months = useMemo(() => monthlyBreakdown(trades.data ?? []), [trades.data])

  if (trades.isLoading) return <Loading />
  if (trades.error) return <ErrorBox error={trades.error} />

  const rows = trades.data ?? []
  const net = rows.reduce((sum, t) => sum + t.net_pnl, 0)
  const charges = rows.reduce((sum, t) => sum + t.charges, 0)
  // A trade that made money before costs but not after is the exact case
  // this page exists to catch — charges quietly ate a real profit.
  const chargesAteProfit = rows.filter((t) => t.gross_pnl > 0 && t.net_pnl <= 0)

  return (
    <>
      <div className="page-head">
        <h1>Closed trades</h1>
        <div className="row">
          <span className="muted">Net</span>
          <strong className={pnlClass(net)}>{formatCurrency(net)}</strong>
          <span className="muted">after {formatCurrency(charges)} in charges</span>
        </div>
      </div>

      {chargesAteProfit.length > 0 && (
        <div className="banner banner-warn">
          ⚠️ {chargesAteProfit.length} trade{chargesAteProfit.length === 1 ? '' : 's'} made money
          before costs but not after — charges (brokerage, taxes, DP charge on the sell) ate the
          entire profit. Marked with ⚠️ below.
        </div>
      )}

      {months.length > 0 && (
        <>
          <h2>By month</h2>
          <div className="table-wrap" style={{ marginBottom: '1.5rem' }}>
            <table>
              <thead>
                <tr>
                  <th>Month</th>
                  <th className="num">Trades</th>
                  <th className="num">Win rate</th>
                  <th className="num">Gross</th>
                  <th className="num">Charges</th>
                  <th className="num">Net P&L</th>
                </tr>
              </thead>
              <tbody>
                {months.map((m) => (
                  <tr key={m.key}>
                    <td>
                      <strong>{m.label}</strong>
                    </td>
                    <td className="num">{m.trades}</td>
                    <td className="num">{((m.wins / m.trades) * 100).toFixed(0)}%</td>
                    <td className={`num ${pnlClass(m.gross)}`}>{formatCurrency(m.gross)}</td>
                    <td className="num muted">{formatCurrency(m.charges)}</td>
                    <td className={`num ${pnlClass(m.net)}`}>{formatCurrency(m.net)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      <h2>Every trade</h2>
      <div className="table-wrap">
        {!rows.length ? (
          <Empty label="No closed trades yet." />
        ) : (
          <table>
            <thead>
              <tr>
                <th className="sticky-col">Symbol</th>
                <th className="num">Qty</th>
                <th className="num">Invested</th>
                <th className="num">Entry</th>
                <th className="num">Exit</th>
                <th className="num">Gross</th>
                <th className="num">Charges</th>
                <th className="num">Net P&L</th>
                <th className="num">Return</th>
                <th className="num">Days</th>
                <th>Exit reason</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((t) => {
                const chargesAteThis = t.gross_pnl > 0 && t.net_pnl <= 0
                return (
                <tr key={t.id}>
                  <td className="sticky-col">
                    <strong>{t.symbol}</strong>
                    {chargesAteThis && <span title="Gross profit, but charges ate it all">⚠️</span>}
                    <div className="muted" style={{ fontSize: '0.75rem' }}>
                      {formatDate(t.entry_at)} → {formatDate(t.exit_at)}
                    </div>
                  </td>
                  <td className="num">{t.quantity}</td>
                  <td className="num muted">{formatCurrency(t.entry_price * t.quantity)}</td>
                  <td className="num">{formatCurrency(t.entry_price)}</td>
                  <td className="num">{formatCurrency(t.exit_price)}</td>
                  <td className={`num ${pnlClass(t.gross_pnl)}`}>{formatCurrency(t.gross_pnl)}</td>
                  <td className="num muted">{formatCurrency(t.charges)}</td>
                  <td className={`num ${pnlClass(t.net_pnl)}`}>{formatCurrency(t.net_pnl)}</td>
                  <td className={`num ${pnlClass(t.net_pnl)}`}>
                    {formatSignedPercent(t.return_pct)}
                  </td>
                  <td className="num">{t.holding_days}</td>
                  <td className="muted">{t.exit_reason ?? '—'}</td>
                </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>
    </>
  )
}
