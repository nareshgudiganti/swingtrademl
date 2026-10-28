import { Fragment, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../../api/client'
import type { DetailedPosition } from '../../api/types'
import { CapFlag } from '../cap'
import { DayCell, ScoreToday, SuggestionTag, scoreNow, suggestionRank } from '../HeldRead'
import ScoreTrail from '../ScoreTrail'
import { SortTh, useSort } from '../sort'
import { Card, inr, signed, toneClass } from '../ui'
import StockLink from '../StockLink'
import { PageState, StaleNotice } from '../PageState'
import { pickState } from '../stateRules'

type Period = 'day' | 'week' | 'month'

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

  // "Buy more" adds a second lot of a stock already held, in the same practice book.
  const [buyingId, setBuyingId] = useState<number | null>(null)
  const [buyQty, setBuyQty] = useState('1')
  const buyMore = useMutation({
    mutationFn: (p: DetailedPosition) =>
      api.testerPaperBuy({ symbol: p.symbol, quantity: Number(buyQty), cap_tier: p.cap_tier ?? 'large' }),
    onSuccess: () => {
      setBuyingId(null)
      queryClient.invalidateQueries({ queryKey: ['testerSummary'] })
      queryClient.invalidateQueries({ queryKey: ['testerPositions'] })
    },
  })

  const rows = positions.data ?? []
  const positionsState = pickState(positions, rows.length === 0)
  const tradesState = pickState(trades)
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
        <StaleNotice q={positions} />
        {positionsState !== 'ready' && positionsState !== 'empty' && (
          <PageState kind={positionsState} what="your test positions" error={positions.error} onRetry={positions.refetch} />
        )}
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

      <Card
        title="Open positions"
        sub="Buy new stocks on Portfolio → Manual test. Buy more or sell here. Click a column name to sort, click a stock to see its score day by day."
      >
        {close.isError && <p className="tm-dim">Could not sell that position.</p>}
        {positionsState === 'empty' && (
          <PageState kind="empty" reason="Nothing held yet. Make a practice buy on Portfolio → Manual test." />
        )}
        {rows.length > 0 && (
          <OpenTable
            rows={rows}
            selling={close.isPending}
            onSell={(p) => {
              if (confirm(`Paper sell all ${p.quantity} × ${p.symbol}?`)) close.mutate(p.id)
            }}
            buy={{
              openId: buyingId,
              qty: buyQty,
              pending: buyMore.isPending,
              error: buyMore.isError ? (buyMore.error as Error).message : null,
              toggle: (p) => {
                setBuyingId(buyingId === p.id ? null : p.id)
                setBuyQty('1')
                buyMore.reset()
              },
              setQty: setBuyQty,
              confirm: (p) => buyMore.mutate(p),
            }}
          />
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
        {tradesState === 'ready' ? (
          <StaleNotice q={trades} />
        ) : (
          <PageState kind={tradesState} what="your closed trades" error={trades.error} onRetry={trades.refetch} />
        )}
        {tradesState === 'ready' && reportRows.length === 0 && (
          <PageState kind="empty" reason="No closed paper trades yet. A trade shows here once you sell it." />
        )}
        {reportRows.length > 0 && <PeriodTable rows={reportRows} />}
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

type OpenKey = 'symbol' | 'sector' | 'day' | 'bought' | 'score' | 'suggestion' | 'value' | 'pnl'

type BuyMore = {
  openId: number | null
  qty: string
  pending: boolean
  error: string | null
  toggle: (p: DetailedPosition) => void
  setQty: (v: string) => void
  confirm: (p: DetailedPosition) => void
}

function OpenTable({
  rows,
  selling,
  onSell,
  buy,
}: {
  rows: DetailedPosition[]
  selling: boolean
  onSell: (p: DetailedPosition) => void
  buy: BuyMore
}) {
  const [open, setOpen] = useState<number | null>(null)
  const { sorted, sorter } = useSort<DetailedPosition, OpenKey>(
    rows,
    {
      symbol: (p) => p.symbol,
      sector: (p) => p.sector ?? null,
      day: (p) => p.day_number ?? null,
      bought: (p) => p.entry_at,
      score: (p) => scoreNow(p),
      suggestion: suggestionRank,
      value: (p) => p.current_value,
      pnl: (p) => p.unrealized_pnl_pct,
    },
    { key: 'suggestion', dir: 'asc' },
    { symbol: 'asc', sector: 'asc', suggestion: 'asc' },
  )
  return (
    <div className="tm-table-wrap" tabIndex={0} role="region" aria-label="Table, scroll sideways to see more">
      <table className="tm-table">
        <thead>
          <tr>
            <SortTh sorter={sorter} k="symbol">Stock</SortTh>
            <SortTh sorter={sorter} k="suggestion" title="What to do today: Sell, Sell half, Watch or Hold">
              Suggestion
            </SortTh>
            <SortTh sorter={sorter} k="score" right>Score today</SortTh>
            <SortTh sorter={sorter} k="day">Day</SortTh>
            <SortTh sorter={sorter} k="bought">Bought on</SortTh>
            <SortTh sorter={sorter} k="sector">Sector</SortTh>
            <th className="tm-right">Qty</th>
            <th className="tm-right">Avg</th>
            <SortTh sorter={sorter} k="value" right>Value</SortTh>
            <SortTh sorter={sorter} k="pnl" right>P&amp;L</SortTh>
            <th />
          </tr>
        </thead>
        <tbody>
          {sorted.map((p) => (
            <Fragment key={p.id}>
              <tr className="tm-clickable" onClick={() => setOpen(open === p.id ? null : p.id)}>
                <td className="tm-strong">
                  <StockLink symbol={p.symbol} withScore={false} />
                  <CapFlag tier={p.cap_tier} gap />
                </td>
                <td>
                  <SuggestionTag p={p} />
                </td>
                <td className="tm-right">
                  <ScoreToday p={p} />
                </td>
                <td>
                  <DayCell p={p} />
                </td>
                <td className="tm-dim">{shortDay(p.entry_at)}</td>
                <td className="tm-dim">{p.sector || '—'}</td>
                <td className="tm-right tm-num">{p.quantity}</td>
                <td className="tm-right tm-num">₹{inr(p.entry_price)}</td>
                <td className="tm-right tm-num">₹{inr(p.current_value, 0)}</td>
                <td className={`tm-right tm-num ${toneClass(p.unrealized_pnl)}`}>{signed(p.unrealized_pnl_pct * 100)}</td>
                <td>
                  <div className="tm-flex tm-wrap" style={{ gap: '0.4rem' }}>
                    <button
                      type="button"
                      className="tm-btn"
                      onClick={(e) => {
                        e.stopPropagation()
                        buy.toggle(p)
                      }}
                    >
                      {buy.openId === p.id ? 'Close' : 'Buy more'}
                    </button>
                    <button
                      type="button"
                      className="tm-btn tm-btn-danger"
                      disabled={selling}
                      onClick={(e) => {
                        e.stopPropagation()
                        onSell(p)
                      }}
                    >
                      Paper sell
                    </button>
                  </div>
                </td>
              </tr>
              {buy.openId === p.id && (
                <tr>
                  <td colSpan={11}>
                    <form
                      className="tm-flex tm-wrap"
                      style={{ gap: '0.5rem', alignItems: 'center', padding: '0.35rem 0' }}
                      onSubmit={(e) => {
                        e.preventDefault()
                        buy.confirm(p)
                      }}
                    >
                      <span className="tm-strong">Paper buy more {p.symbol}</span>
                      <input
                        className="tm-input"
                        type="number"
                        min={1}
                        value={buy.qty}
                        onChange={(e) => buy.setQty(e.target.value)}
                        aria-label="Quantity"
                        style={{ width: 90 }}
                      />
                      <button className="tm-btn" type="submit" disabled={!Number(buy.qty) || buy.pending}>
                        {buy.pending ? 'Buying…' : 'Paper buy'}
                      </button>
                      <span className="tm-dim">Added as a separate lot at today's price.</span>
                      {buy.error && <span className="tm-neg">{buy.error}</span>}
                    </form>
                  </td>
                </tr>
              )}
              {open === p.id && (
                <tr>
                  <td colSpan={11} className="tm-wrap">
                    {p.suggestion_reason && <p style={{ margin: '0 0 0.5rem' }}>{p.suggestion_reason}</p>}
                    <ScoreTrail p={p} />
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  )
}

type PeriodRow = { key: string; trades: number; wins: number; net: number }

function PeriodTable({ rows }: { rows: PeriodRow[] }) {
  const { sorted, sorter } = useSort<PeriodRow, 'key' | 'trades' | 'wins' | 'net'>(
    rows,
    { key: (r) => r.key, trades: (r) => r.trades, wins: (r) => r.wins, net: (r) => r.net },
    { key: 'key', dir: 'desc' },
  )
  return (
    <table className="tm-table">
      <thead>
        <tr>
          <SortTh sorter={sorter} k="key">Period</SortTh>
          <SortTh sorter={sorter} k="trades" right>Trades</SortTh>
          <SortTh sorter={sorter} k="wins" right>Wins</SortTh>
          <SortTh sorter={sorter} k="net" right>Net</SortTh>
        </tr>
      </thead>
      <tbody>
        {sorted.map((r) => (
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
  )
}

function shortDay(isoTime: string) {
  return new Date(isoTime).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })
}
