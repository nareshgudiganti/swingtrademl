import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../../api/client'
import type { DetailedPosition } from '../../api/types'
import { CapFlag } from '../cap'
import { SellList } from '../HeldRead'
import { SortTh, useSort } from '../sort'
import { Card, inr, signed, StockLogo, toneClass } from '../ui'
import StockLink from '../StockLink'
import { PageState, StaleNotice } from '../PageState'
import { pickState } from '../stateRules'
import { ActToday, DetailPanel, LevelTag, PositionBar, levelOf, retPct } from './PositionParts'
import type { LevelState } from './positionLevels'
import { AllocationCard, ClosedScoreboard } from './PortfolioInsights'

const SECTOR_COLORS = ['#3f55d6', '#1f9d6b', '#e0a72b', '#d9486a', '#7a4fd6', '#17a2b8', '#e8702a', '#5a6b8c']

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
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [filter, setFilter] = useState<Filter>('all')
  const [query, setQuery] = useState('')
  const [trailOpen, setTrailOpen] = useState(false)
  const actCount = rows.filter((p) => levelOf(p).act).length
  const watchCount = rows.filter((p) => levelOf(p).state === 'watch').length
  const visibleRows = rows.filter(
    (p) =>
      (filter === 'all' || (filter === 'act' ? levelOf(p).act : levelOf(p).state === 'watch')) &&
      (!query.trim() || `${p.symbol} ${p.name ?? ''}`.toLowerCase().includes(query.trim().toLowerCase())),
  )
  // The most urgent stock is selected until the owner picks one.
  const selected =
    rows.find((p) => p.id === selectedId) ??
    [...rows].sort((a, b) => STATE_RANK[levelOf(a).state] - STATE_RANK[levelOf(b).state])[0]
  const positionsState = pickState(positions, rows.length === 0)
  const tradesState = pickState(trades)
  const moneyRow = summary.data
  const invested = rows.reduce((s, p) => s + p.invested, 0)
  const currentValue = rows.reduce((s, p) => s + p.current_value, 0)
  const openPnl = rows.reduce((s, p) => s + p.unrealized_pnl, 0)
  const dayPnl = rows.reduce((s, p) => s + (p.day_pnl ?? 0), 0)
  // Total = open + banked profit, measured against everything put into trades (open and closed).
  const totalPnl = openPnl + (moneyRow?.realized_pnl ?? 0)
  const totalCost = invested + (trades.data ?? []).reduce((s, t) => s + t.quantity * t.entry_price, 0)
  const byReturn = [...rows].sort((a, b) => b.unrealized_pnl_pct - a.unrealized_pnl_pct)
  const best = byReturn[0]
  const worst = byReturn[byReturn.length - 1]
  const dayPct = (p: DetailedPosition) => {
    const before = p.current_value - (p.day_pnl ?? 0)
    return before > 0 ? ((p.day_pnl ?? 0) / before) * 100 : 0
  }
  const dayPctTotal = currentValue - dayPnl > 0 ? (dayPnl / (currentValue - dayPnl)) * 100 : undefined
  const byDay = [...rows].sort((a, b) => dayPct(b) - dayPct(a))
  const bestDay = byDay[0]
  const worstDay = byDay[byDay.length - 1]

  const sectors = useMemo(() => {
    const m = new Map<string, { value: number; cost: number; pnl: number; stocks: { symbol: string; pct: number }[] }>()
    for (const p of rows) {
      const name = p.sector || 'Unclassified'
      const cur = m.get(name) ?? { value: 0, cost: 0, pnl: 0, stocks: [] }
      cur.value += p.current_value
      cur.cost += p.invested
      cur.pnl += p.unrealized_pnl
      cur.stocks.push({ symbol: p.symbol, pct: p.unrealized_pnl_pct * 100 })
      m.set(name, cur)
    }
    const total = rows.reduce((s, p) => s + p.current_value, 0)
    return [...m.entries()]
      .map(([name, v]) => ({
        name,
        ...v,
        ret: v.cost > 0 ? (v.pnl / v.cost) * 100 : 0,
        pct: total > 0 ? v.value / total : 0,
      }))
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
      <Card glow title="Open positions" sub="Your manual paper trades.">
        <StaleNotice q={positions} />
        {positionsState !== 'ready' && positionsState !== 'empty' && (
          <PageState kind={positionsState} what="your test positions" error={positions.error} onRetry={positions.refetch} />
        )}
        {moneyRow && (
          <div className="tm-grid tm-cols-3">
            <Stat label="Invested" value={money(currentValue)} note={`${rows.length} open positions`} />
            <Stat
              label="Today's profit / loss"
              value={`${dayPnl < 0 ? '−' : ''}${money(dayPnl)}${dayPctTotal === undefined ? '' : ` (${signed(dayPctTotal)})`}`}
              tone={toneClass(dayPnl)}
            />
            <Stat
              label="Total profit / loss"
              value={`${totalPnl < 0 ? '−' : ''}${money(totalPnl)}${totalCost > 0 ? ` (${signed((totalPnl / totalCost) * 100)})` : ''}`}
              tone={toneClass(totalPnl)}
              note={`banked ${moneyRow.realized_pnl < 0 ? '−' : ''}${money(moneyRow.realized_pnl)} + open`}
            />
          </div>
        )}
      </Card>

      {rows.length > 0 && (
        <div className="tm-grid tm-cols-4">
          <Card>
            <Stat
              label="Open profit / loss"
              value={`${openPnl < 0 ? '−' : ''}${money(openPnl)}`}
              tone={toneClass(openPnl)}
              note={invested > 0 ? signed((openPnl / invested) * 100) : undefined}
            />
          </Card>
          {bestDay && (
            <Card>
              <Stat label="Best today" value={bestDay.symbol} tone={toneClass(dayPct(bestDay))} note={signed(dayPct(bestDay))} />
            </Card>
          )}
          {worstDay && (
            <Card>
              <Stat label="Worst today" value={worstDay.symbol} tone={toneClass(dayPct(worstDay))} note={signed(dayPct(worstDay))} />
            </Card>
          )}
          {best && (
            <Card>
              <Stat label="Best overall (open)" value={best.symbol} tone={toneClass(best.unrealized_pnl_pct)} note={signed(best.unrealized_pnl_pct * 100)} />
            </Card>
          )}
          {worst && (
            <Card>
              <Stat label="Worst overall (open)" value={worst.symbol} tone={toneClass(worst.unrealized_pnl_pct)} note={signed(worst.unrealized_pnl_pct * 100)} />
            </Card>
          )}
        </div>
      )}

      {rows.length > 0 && <ActToday rows={rows} onPick={(id) => { setSelectedId(id); setFilter('all') }} />}

      <div className="op-main">
        <Card title={`Your positions (${rows.length})`}>
          {close.isError && <p className="tm-dim">Could not sell that position.</p>}
          {positionsState === 'empty' && (
            <>
              <PageState kind="empty" reason="Nothing held yet. Make a practice buy on Portfolio → Manual test." />
              <Link className="tm-btn" to="/trademind/manual-test">
                + Add practice position
              </Link>
            </>
          )}
          {rows.length > 0 && (
            <>
              <div className="op-toolbar">
                <Link className="tm-btn" to="/trademind/manual-test">
                  + Add practice position
                </Link>
                {(['all', 'act', 'watch'] as Filter[]).map((f) => (
                  <button key={f} type="button" className="tm-btn op-chip" aria-pressed={filter === f} onClick={() => setFilter(f)}>
                    {f === 'all' ? `All (${rows.length})` : f === 'act' ? `Act today (${actCount})` : `Watch (${watchCount})`}
                  </button>
                ))}
                <input
                  className="tm-input"
                  type="search"
                  placeholder="Search stock…"
                  aria-label="Search stock"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                />
              </div>
              <OpenTable
                rows={visibleRows}
                selectedId={selected?.id ?? null}
                onSelect={(id) => {
                  setSelectedId(id)
                  setTrailOpen(false)
                  setBuyingId(null)
                }}
              />
              {visibleRows.length === 0 && <p className="tm-dim">No stock matches this filter.</p>}
            </>
          )}
        </Card>
        {selected && (
          <DetailPanel p={selected} trailOpen={trailOpen} onTrail={() => setTrailOpen(!trailOpen)}>
            <div className="op-actions">
              <button
                type="button"
                className="tm-btn"
                onClick={() => {
                  setBuyingId(buyingId === selected.id ? null : selected.id)
                  setBuyQty('1')
                  buyMore.reset()
                }}
              >
                {buyingId === selected.id ? 'Close' : 'Buy more'}
              </button>
              <button
                type="button"
                className="tm-btn tm-btn-danger"
                disabled={close.isPending}
                onClick={() => {
                  if (confirm(`Paper sell all ${selected.quantity} × ${selected.symbol}?`)) close.mutate(selected.id)
                }}
              >
                Paper sell
              </button>
            </div>
            {buyingId === selected.id && (
              <form
                className="tm-flex tm-wrap"
                style={{ gap: '0.5rem', alignItems: 'center' }}
                onSubmit={(e) => {
                  e.preventDefault()
                  buyMore.mutate(selected)
                }}
              >
                <span className="tm-strong">Paper buy more {selected.symbol}</span>
                <input
                  className="tm-input"
                  type="number"
                  min={1}
                  value={buyQty}
                  onChange={(e) => setBuyQty(e.target.value)}
                  aria-label="Quantity"
                  style={{ width: 90 }}
                />
                <button className="tm-btn" type="submit" disabled={!Number(buyQty) || buyMore.isPending}>
                  {buyMore.isPending ? 'Buying…' : 'Paper buy'}
                </button>
                <span className="tm-dim">Added as a separate lot at today's price.</span>
                {buyMore.isError && <span className="tm-neg">{(buyMore.error as Error).message}</span>}
              </form>
            )}
          </DetailPanel>
        )}
      </div>


      <AllocationCard rows={rows} />

      {sectors.length > 0 && (
        <Card title="By sector">
          <div className="tm-sector-rail" role="region" aria-label="Sectors, scroll sideways to see more" tabIndex={0}>
            {sectors.map((s, i) => (
              <div key={s.name} className="tm-sector-card" style={{ ['--sec' as string]: SECTOR_COLORS[i % SECTOR_COLORS.length] }}>
                <div className="tm-sector-top">
                  <b>{s.name}</b>
                  <b>{(s.pct * 100).toFixed(0)}%</b>
                </div>
                <div className="tm-sector-bar">
                  <span style={{ width: `${Math.min(100, s.pct * 100)}%` }} />
                </div>
                <div className="tm-flex" style={{ justifyContent: 'space-between' }}>
                  <span className="tm-dim">{money(s.value)}</span>
                  <b className={`${toneClass(s.pnl)} tm-num`}>{signed(s.ret)}</b>
                </div>
                <div className="tm-sector-stocks" style={{ flexDirection: 'column', alignItems: 'stretch', gap: '0.4rem' }}>
                  {s.stocks.map((st) => (
                    <div key={st.symbol} className="tm-flex" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
                      <span className="tm-stock-cell">
                        <StockLogo symbol={st.symbol} />
                        {st.symbol}
                      </span>
                      <span className={`${toneClass(st.pct)} tm-num`}>{signed(st.pct)}</span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

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
        {tradesState === 'ready' && <ClosedScoreboard trades={trades.data ?? []} />}
        {tradesState === 'ready' && <SellList trades={trades.data ?? []} book="Testing" />}
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

type Filter = 'all' | 'act' | 'watch'
type OpenKey = 'symbol' | 'qty' | 'entry' | 'price' | 'pnlAbs' | 'pnl' | 'progress' | 'state'

const STATE_RANK: Record<LevelState, number> = {
  stop: 0,
  near_stop: 1,
  target: 2,
  near_target: 3,
  half: 4,
  near_half: 5,
  watch: 6,
  hold: 7,
}

function OpenTable({
  rows,
  selectedId,
  onSelect,
}: {
  rows: DetailedPosition[]
  selectedId: number | null
  onSelect: (id: number) => void
}) {
  const { sorted, sorter } = useSort<DetailedPosition, OpenKey>(
    rows,
    {
      symbol: (p) => p.symbol,
      qty: (p) => p.quantity,
      entry: (p) => p.entry_price,
      price: (p) => p.current_price,
      pnlAbs: (p) => p.unrealized_pnl,
      pnl: (p) => p.unrealized_pnl_pct,
      progress: (p) => p.unrealized_pnl_pct,
      state: (p) => STATE_RANK[levelOf(p).state],
    },
    { key: 'state', dir: 'asc' },
    { symbol: 'asc', state: 'asc' },
  )
  return (
    <div className="tm-table-wrap" tabIndex={0} role="region" aria-label="Table, scroll sideways to see more">
      <table className="tm-table">
        <thead>
          <tr>
            <SortTh sorter={sorter} k="symbol">Stock</SortTh>
            <SortTh sorter={sorter} k="qty" right>Qty</SortTh>
            <SortTh sorter={sorter} k="entry" right>Entry</SortTh>
            <SortTh sorter={sorter} k="price" right>Current</SortTh>
            <SortTh sorter={sorter} k="pnlAbs" right>P&amp;L (₹)</SortTh>
            <SortTh sorter={sorter} k="pnl" right>P&amp;L %</SortTh>
            <SortTh sorter={sorter} k="progress">Progress (−4% to +8%)</SortTh>
            <SortTh sorter={sorter} k="state" title="What to do today, from where the stock sits between stop, half-profit and target">
              Suggestion
            </SortTh>
          </tr>
        </thead>
        <tbody>
          {sorted.map((p) => (
            <tr key={p.id} className={`tm-clickable ${p.id === selectedId ? 'op-row-sel' : ''}`} onClick={() => onSelect(p.id)}>
              <td className="tm-strong">
                <span className="tm-stock-cell">
                  <StockLogo symbol={p.symbol} />
                  <span>
                    <StockLink symbol={p.symbol} withScore={false} />
                    <CapFlag tier={p.cap_tier} gap />
                    {p.name && (
                      <small className="tm-dim" style={{ display: 'block', fontWeight: 400 }}>
                        {p.name}
                      </small>
                    )}
                  </span>
                </span>
              </td>
              <td className="tm-right tm-num">{p.quantity}</td>
              <td className="tm-right tm-num">₹{inr(p.entry_price)}</td>
              <td className="tm-right tm-num">₹{inr(p.current_price)}</td>
              <td className={`tm-right tm-num ${toneClass(p.unrealized_pnl)}`}>
                {p.unrealized_pnl < 0 ? '−' : '+'}₹{inr(Math.abs(p.unrealized_pnl), 0)}
              </td>
              <td className="tm-right tm-num">
                <span className={`tm-pnl-pill ${toneClass(p.unrealized_pnl)}`}>{signed(retPct(p))}</span>
              </td>
              <td>
                <PositionBar pct={retPct(p)} />
              </td>
              <td>
                <LevelTag level={levelOf(p)} />
              </td>
            </tr>
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
