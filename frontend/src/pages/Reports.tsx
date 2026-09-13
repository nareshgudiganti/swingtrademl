import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Bar, BarChart, CartesianGrid, Cell, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

import { api } from '../api/client'
import type { Trade } from '../api/types'
import Stat from '../components/Stat'
import { Empty, ErrorBox, Loading } from '../components/Loading'
import { formatCompact, formatCurrency, formatDate, formatPercent, formatSignedPercent, pnlClass } from '../lib/format'

type Period = 'month' | 'quarter' | 'year'

// Coloured from OUR perspective, not the stock's: if the price rose after we
// sold, that's money left on the table (shown as a loss); if it fell, the
// exit was vindicated (shown as a win). Inverted from the usual pnlClass.
function sinceExitClass(returnPct: number | null): string {
  if (returnPct === null) return 'muted'
  return pnlClass(-returnPct)
}

interface PeriodRow {
  key: string
  label: string
  trades: number
  wins: number
  gross: number
  charges: number
  net: number
}

// Closed trades only — this is what's actually booked. Open positions'
// unrealised P&L isn't attributable to a single past period, so it belongs
// on the Portfolio page, not a report of what already happened.
function groupTrades(rows: Trade[], period: Period): PeriodRow[] {
  const byPeriod = new Map<string, PeriodRow>()
  for (const t of rows) {
    const d = new Date(t.exit_at)
    const year = d.getFullYear()
    let key: string
    let label: string
    if (period === 'year') {
      key = `${year}`
      label = `${year}`
    } else if (period === 'quarter') {
      const q = Math.floor(d.getMonth() / 3) + 1
      key = `${year}-Q${q}`
      label = `Q${q} ${year}`
    } else {
      key = `${year}-${String(d.getMonth() + 1).padStart(2, '0')}`
      label = d.toLocaleDateString('en-IN', { month: 'short', year: 'numeric' })
    }
    const row = byPeriod.get(key) ?? { key, label, trades: 0, wins: 0, gross: 0, charges: 0, net: 0 }
    row.trades += 1
    row.wins += t.is_win ? 1 : 0
    row.gross += t.gross_pnl
    row.charges += t.charges
    row.net += t.net_pnl
    byPeriod.set(key, row)
  }
  return [...byPeriod.values()].sort((a, b) => b.key.localeCompare(a.key))
}

const PERIODS: { key: Period; label: string }[] = [
  { key: 'month', label: 'Monthly' },
  { key: 'quarter', label: 'Quarterly' },
  { key: 'year', label: 'Yearly' },
]

export default function Reports() {
  const [period, setPeriod] = useState<Period>('month')
  // Reports need the full trade history, not the ~100-200 a list page
  // paginates to — 1000 is the API's own ceiling (see portfolio.py's
  // list_trades), well past what this account will produce for years.
  const trades = useQuery({ queryKey: ['trades', 1000], queryFn: () => api.trades(1000) })

  const rows = useMemo(() => groupTrades(trades.data ?? [], period), [trades.data, period])
  const chartData = useMemo(() => [...rows].reverse(), [rows])

  if (trades.isLoading) return <Loading />
  if (trades.error) return <ErrorBox error={trades.error} />

  const all = trades.data ?? []
  const totalNet = all.reduce((sum, t) => sum + t.net_pnl, 0)
  const totalGross = all.reduce((sum, t) => sum + t.gross_pnl, 0)
  const totalCharges = all.reduce((sum, t) => sum + t.charges, 0)
  const winRate = all.length ? all.filter((t) => t.is_win).length / all.length : 0
  const bestPeriod = rows.length ? rows.reduce((a, b) => (b.net > a.net ? b : a)) : null
  const worstPeriod = rows.length ? rows.reduce((a, b) => (b.net < a.net ? b : a)) : null
  // A trade that made money before costs but not after is worth flagging —
  // charges (brokerage, taxes, DP charge on the sell) quietly ate the profit.
  const chargesAteProfit = all.filter((t) => t.gross_pnl > 0 && t.net_pnl <= 0)
  // Ran hard in the direction we'd already sold — a candidate for "we may
  // have exited too early", worth a second look rather than a definite miss.
  const ranAfterExit = all.filter((t) => (t.return_15d_after_exit ?? t.return_5d_after_exit ?? 0) >= 0.05)

  return (
    <>
      <div className="page-head">
        <h1>Reports</h1>
        <div className="row" style={{ gap: '0.4rem' }}>
          {PERIODS.map((p) => (
            <button
              key={p.key}
              className={period === p.key ? 'primary' : ''}
              onClick={() => setPeriod(p.key)}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {!all.length ? (
        <Empty label="No closed trades yet — reports fill in as positions close." />
      ) : (
        <>
          {chargesAteProfit.length > 0 && (
            <div className="banner banner-warn">
              ⚠️ {chargesAteProfit.length} trade{chargesAteProfit.length === 1 ? '' : 's'} made money
              before costs but not after — charges ate the entire profit. Marked with ⚠️ in the
              trade log below.
            </div>
          )}

          {ranAfterExit.length > 0 && (
            <div className="banner banner-warn">
              📈 {ranAfterExit.length} stock{ranAfterExit.length === 1 ? '' : 's'} rose 5%+ in the
              weeks after we sold — worth checking whether the exit was too early. See "since sold"
              columns in the trade log below.
            </div>
          )}

          <div className="grid">
            <Stat
              label="Total realised P&L"
              value={formatCurrency(totalNet)}
              sub={`${formatCurrency(totalGross)} gross − ${formatCurrency(totalCharges)} charges`}
              tone={pnlClass(totalNet) as 'pos' | 'neg' | 'flat'}
            />
            <Stat label="Closed trades" value={all.length} sub={`Win rate ${formatPercent(winRate, 1)}`} />
            <Stat
              label="Broker charges"
              value={formatCurrency(totalCharges)}
              sub={totalGross ? `${formatPercent(totalCharges / Math.abs(totalGross), 1)} of gross` : undefined}
              tone="neg"
            />
            {bestPeriod && (
              <Stat
                label={`Best ${period}`}
                value={bestPeriod.label}
                sub={formatCurrency(bestPeriod.net)}
                tone="pos"
              />
            )}
            {worstPeriod && worstPeriod.net < 0 && (
              <Stat
                label={`Worst ${period}`}
                value={worstPeriod.label}
                sub={formatCurrency(worstPeriod.net)}
                tone="neg"
              />
            )}
          </div>

          <div className="card" style={{ height: 300, marginBottom: '1.5rem' }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chartData} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
                <CartesianGrid stroke="#263352" strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="label" stroke="#8b9bb4" fontSize={11} tickMargin={8} />
                <YAxis
                  stroke="#8b9bb4"
                  fontSize={11}
                  width={70}
                  tickFormatter={(v: number) => formatCompact(v)}
                />
                <Tooltip
                  contentStyle={{ background: '#131c31', border: '1px solid #263352', borderRadius: 10 }}
                  formatter={(v: number, name: string) => [formatCurrency(v), name]}
                />
                <Legend wrapperStyle={{ fontSize: 12 }} formatter={(value) => value} />
                <Bar dataKey="gross" name="Gross P&L" fill="var(--accent)" radius={[4, 4, 0, 0]} fillOpacity={0.45} />
                <Bar dataKey="charges" name="Broker charges" fill="var(--warn)" radius={[4, 4, 0, 0]} />
                <Bar dataKey="net" name="Net P&L" radius={[4, 4, 0, 0]}>
                  {chartData.map((row) => (
                    <Cell key={row.key} fill={row.net >= 0 ? 'var(--pos)' : 'var(--neg)'} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>

          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th className="sticky-col">{PERIODS.find((p) => p.key === period)!.label.replace('ly', '')}</th>
                  <th className="num">Trades</th>
                  <th className="num">Win rate</th>
                  <th className="num">Gross</th>
                  <th className="num">Charges</th>
                  <th className="num">Net P&amp;L</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.key}>
                    <td className="sticky-col">
                      <strong>{r.label}</strong>
                    </td>
                    <td className="num">{r.trades}</td>
                    <td className="num">{formatPercent(r.wins / r.trades, 0)}</td>
                    <td className={`num ${pnlClass(r.gross)}`}>{formatCurrency(r.gross)}</td>
                    <td className="num muted">{formatCurrency(r.charges)}</td>
                    <td className={`num ${pnlClass(r.net)}`}>{formatCurrency(r.net)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <h2>Every trade</h2>
          <div className="table-wrap">
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
                  <th className="num" title="Price move vs. our exit price, 5 trading days later">
                    +5d since sold
                  </th>
                  <th className="num" title="Price move vs. our exit price, 15 trading days later">
                    +15d since sold
                  </th>
                </tr>
              </thead>
              <tbody>
                {all.map((t) => {
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
                      <td className={`num ${pnlClass(t.net_pnl)}`}>{formatSignedPercent(t.return_pct)}</td>
                      <td className="num">{t.holding_days}</td>
                      <td className="muted" title={t.exit_reason ?? ''}>
                        {t.exit_reason_label ?? t.exit_reason ?? '—'}
                      </td>
                      <td className={`num ${sinceExitClass(t.return_5d_after_exit)}`}>
                        {t.return_5d_after_exit !== null ? formatSignedPercent(t.return_5d_after_exit) : '—'}
                      </td>
                      <td className={`num ${sinceExitClass(t.return_15d_after_exit)}`}>
                        {t.return_15d_after_exit !== null ? formatSignedPercent(t.return_15d_after_exit) : '—'}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </>
  )
}
