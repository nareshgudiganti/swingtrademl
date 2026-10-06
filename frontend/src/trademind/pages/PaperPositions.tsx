import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../../api/client'
import { Card, inr, signed, toneClass } from '../ui'

type Period = 'day' | 'week' | 'month'

const CAP_LABEL: Record<string, string> = { large: 'Large', midcap: 'Mid', smallcap: 'Small' }

function periodKey(exitAt: string, period: Period): string {
  const d = new Date(exitAt)
  if (period === 'month') return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
  if (period === 'week') {
    const start = new Date(d)
    start.setDate(d.getDate() - d.getDay())
    return start.toISOString().slice(0, 10)
  }
  return exitAt.slice(0, 10)
}

function money(n: number) {
  return `₹${inr(Math.abs(n), 0)}`
}

export default function PaperPositions() {
  const queryClient = useQueryClient()
  const [period, setPeriod] = useState<Period>('day')
  const summary = useQuery({ queryKey: ['testerSummary'], queryFn: api.testerSummary })
  const positions = useQuery({ queryKey: ['testerPositions'], queryFn: api.testerPositions })
  const trades = useQuery({ queryKey: ['testerTrades', 500], queryFn: () => api.testerTrades(500) })

  const close = useMutation({
    mutationFn: (id: number) => api.closePosition(id, 'MANUAL'),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['testerSummary'] })
      queryClient.invalidateQueries({ queryKey: ['testerPositions'] })
      queryClient.invalidateQueries({ queryKey: ['testerTrades'] })
    },
  })

  const rows = positions.data ?? []
  const moneyRow = summary.data
  const invested = rows.reduce((s, p) => s + p.invested, 0)
  const currentValue = rows.reduce((s, p) => s + p.current_value, 0)
  const openPnl = rows.reduce((s, p) => s + p.unrealized_pnl, 0)
  const dayPnl = rows.reduce((s, p) => s + (p.day_pnl ?? 0), 0)
  const byReturn = [...rows].sort((a, b) => b.unrealized_pnl_pct - a.unrealized_pnl_pct)
  const best = byReturn[0]
  const worst = byReturn[byReturn.length - 1]

  const sectors = useMemo(() => {
    const m = new Map<string, { value: number; symbols: string[] }>()
    for (const p of rows) {
      const name = p.sector || 'Unclassified'
      const cur = m.get(name) ?? { value: 0, symbols: [] }
      cur.value += p.current_value
      cur.symbols.push(p.symbol)
      m.set(name, cur)
    }
    const total = rows.reduce((s, p) => s + p.current_value, 0)
    return [...m.entries()]
      .map(([name, v]) => ({ name, ...v, pct: total > 0 ? v.value / total : 0 }))
      .sort((a, b) => b.value - a.value)
  }, [rows])

  const reportRows = useMemo(() => {
    const m = new Map<string, { key: string; trades: number; wins: number; net: number }>()
    for (const t of trades.data ?? []) {
      const key = periodKey(t.exit_at, period)
      const r = m.get(key) ?? { key, trades: 0, wins: 0, net: 0 }
      r.trades += 1
      r.wins += t.is_win ? 1 : 0
      r.net += t.net_pnl
      m.set(key, r)
    }
    return [...m.values()].sort((a, b) => b.key.localeCompare(a.key))
  }, [trades.data, period])

  return (
    <div className="tm-page tm-grid">
      <Card glow title="Testing" sub="Manual paper trades. Your existing Positions tab is unchanged.">
        {positions.isLoading && <p className="tm-dim">Loading…</p>}
        {positions.isError && <p className="tm-dim">Could not load positions.</p>}
        {moneyRow && (
          <div className="tm-grid tm-cols-4">
            <Stat label="Account value" value={money(moneyRow.total_value)} />
            <Stat label="Cash left" value={money(moneyRow.cash)} />
            <Stat label="Held in stocks" value={money(currentValue)} note={`${rows.length} stocks`} />
            <Stat
              label="Profit banked"
              value={`${moneyRow.realized_pnl < 0 ? '−' : ''}${money(moneyRow.realized_pnl)}`}
              tone={toneClass(moneyRow.realized_pnl)}
              note={`${moneyRow.total_trades} closed`}
            />
          </div>
        )}
      </Card>

      {rows.length > 0 && (
        <div className="tm-grid tm-cols-4">
          <Card>
            <Stat label="Today" value={`${dayPnl < 0 ? '−' : ''}${money(dayPnl)}`} tone={toneClass(dayPnl)} />
          </Card>
          <Card>
            <Stat
              label="Open P&L"
              value={`${openPnl < 0 ? '−' : ''}${money(openPnl)}`}
              tone={toneClass(openPnl)}
              note={invested ? signed((openPnl / invested) * 100) : undefined}
            />
          </Card>
          {best && best.unrealized_pnl_pct > 0 && (
            <Card>
              <Stat label="Best" value={best.symbol} tone="tm-pos" note={signed(best.unrealized_pnl_pct * 100)} />
            </Card>
          )}
          {worst && worst.unrealized_pnl_pct < 0 && (
            <Card>
              <Stat label="Worst" value={worst.symbol} tone="tm-neg" note={signed(worst.unrealized_pnl_pct * 100)} />
            </Card>
          )}
        </div>
      )}

      {sectors.length > 0 && (
        <Card title="By sector">
          <div className="tm-rows">
            {sectors.map((s) => (
              <div key={s.name} className="tm-row">
                <span>
                  {s.name} <span className="tm-dim">{s.symbols.join(', ')}</span>
                </span>
                <span className="tm-strong">
                  {money(s.value)} · {(s.pct * 100).toFixed(0)}%
                </span>
              </div>
            ))}
          </div>
        </Card>
      )}

      <Card title="Open positions" sub="Buy from Discover → Watchlist. Sell here.">
        {close.isError && <p className="tm-dim">Could not sell that position.</p>}
        {rows.length === 0 && !positions.isLoading && (
          <p className="tm-dim">Nothing held yet. Open Discover → Watchlist and use Buy.</p>
        )}
        {rows.length > 0 && (
          <div className="tm-table-wrap">
            <table className="tm-table">
              <thead>
                <tr>
                  <th>Stock</th>
                  <th>Size</th>
                  <th>Sector</th>
                  <th className="tm-right">Qty</th>
                  <th className="tm-right">Avg</th>
                  <th className="tm-right">Value</th>
                  <th className="tm-right">P&amp;L</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rows.map((p) => (
                  <tr key={p.id}>
                    <td className="tm-strong">{p.symbol}</td>
                    <td>{CAP_LABEL[p.cap_tier ?? ''] ?? '—'}</td>
                    <td className="tm-dim">{p.sector || '—'}</td>
                    <td className="tm-right tm-num">{p.quantity}</td>
                    <td className="tm-right tm-num">₹{inr(p.entry_price)}</td>
                    <td className="tm-right tm-num">₹{inr(p.current_value, 0)}</td>
                    <td className={`tm-right tm-num ${toneClass(p.unrealized_pnl)}`}>
                      {signed(p.unrealized_pnl_pct * 100)}
                    </td>
                    <td>
                      <button
                        type="button"
                        className="tm-btn tm-btn-danger"
                        disabled={close.isPending}
                        onClick={() => {
                          if (confirm(`Paper sell all ${p.quantity} × ${p.symbol}?`)) close.mutate(p.id)
                        }}
                      >
                        Paper sell
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card title="Closed trades">
        <div className="tm-toolbar" style={{ marginBottom: '0.6rem' }}>
          {(['day', 'week', 'month'] as Period[]).map((p) => (
            <button key={p} type="button" className="tm-btn" onClick={() => setPeriod(p)}>
              {p === 'day' ? 'Daily' : p === 'week' ? 'Weekly' : 'Monthly'}
              {period === p ? ' · on' : ''}
            </button>
          ))}
        </div>
        {trades.isLoading && <p className="tm-dim">Loading…</p>}
        {!trades.isLoading && reportRows.length === 0 && <p className="tm-dim">No closed paper trades yet.</p>}
        {reportRows.length > 0 && (
          <table className="tm-table">
            <thead>
              <tr>
                <th>Period</th>
                <th className="tm-right">Trades</th>
                <th className="tm-right">Wins</th>
                <th className="tm-right">Net</th>
              </tr>
            </thead>
            <tbody>
              {reportRows.map((r) => (
                <tr key={r.key}>
                  <td>{r.key}</td>
                  <td className="tm-right tm-num">{r.trades}</td>
                  <td className="tm-right tm-num">{r.wins}</td>
                  <td className={`tm-right tm-num ${toneClass(r.net)}`}>
                    {r.net < 0 ? '−' : ''}₹{inr(Math.abs(r.net), 0)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  )
}

function Stat({
  label,
  value,
  note,
  tone,
}: {
  label: string
  value: string
  note?: string
  tone?: string
}) {
  return (
    <div>
      <div className="tm-stat-label">{label}</div>
      <div className={`tm-stat-value ${tone ?? ''}`}>{value}</div>
      {note && <div className="tm-dim">{note}</div>}
    </div>
  )
}
