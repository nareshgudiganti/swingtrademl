import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../api/client'
import type { DetailedPosition, Trade } from '../api/types'
import Stat from '../components/Stat'
import { Empty, ErrorBox, Loading } from '../components/Loading'
import StockDetailModal, { type StockDetail } from '../components/StockDetailModal'
import { formatCurrency, formatSignedPercent, pnlClass } from '../lib/format'
import { PositionsTable } from './Positions'

type CapTier = 'large' | 'midcap' | 'smallcap'
type Tab = 'portfolio' | 'list' | 'reports'

const CAP_LABEL: Record<CapTier, string> = {
  large: 'Large',
  midcap: 'Mid',
  smallcap: 'Small',
}

const todayIst = () =>
  new Date().toLocaleDateString('en-IN', { day: '2-digit', month: 'short', timeZone: 'Asia/Kolkata' })

type Period = 'day' | 'week' | 'month'

function periodKey(exitAt: string, period: Period): string {
  const d = new Date(exitAt)
  if (period === 'month') {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
  }
  if (period === 'week') {
    const start = new Date(d)
    start.setDate(d.getDate() - d.getDay())
    return start.toISOString().slice(0, 10)
  }
  return exitAt.slice(0, 10)
}

function ReportsPanel({ trades }: { trades: Trade[] }) {
  const [period, setPeriod] = useState<Period>('day')
  const rows = useMemo(() => {
    const m = new Map<string, { key: string; trades: number; wins: number; net: number }>()
    for (const t of trades) {
      const key = periodKey(t.exit_at, period)
      const r = m.get(key) ?? { key, trades: 0, wins: 0, net: 0 }
      r.trades += 1
      r.wins += t.is_win ? 1 : 0
      r.net += t.net_pnl
      m.set(key, r)
    }
    return [...m.values()].sort((a, b) => b.key.localeCompare(a.key))
  }, [trades, period])

  return (
    <div>
      <div className="toolbar" style={{ marginBottom: '1rem' }}>
        {(['day', 'week', 'month'] as Period[]).map((p) => (
          <button
            key={p}
            type="button"
            className={period === p ? 'btn primary' : 'btn'}
            onClick={() => setPeriod(p)}
          >
            {p === 'day' ? 'Daily' : p === 'week' ? 'Weekly' : 'Monthly'}
          </button>
        ))}
      </div>
      {!rows.length ? (
        <Empty label="No closed paper test trades yet." />
      ) : (
        <table>
          <thead>
            <tr>
              <th>Period</th>
              <th className="num">Trades</th>
              <th className="num">Wins</th>
              <th className="num">Net P&amp;L</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.key}>
                <td>{r.key}</td>
                <td className="num">{r.trades}</td>
                <td className="num">{r.wins}</td>
                <td className={`num ${pnlClass(r.net)}`}>{formatCurrency(r.net)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

function BuyPanel() {
  const queryClient = useQueryClient()
  const watchlist = useQuery({ queryKey: ['watchlist'], queryFn: api.watchlist })
  const [symbol, setSymbol] = useState('')
  const [qty, setQty] = useState('1')
  const [capTier, setCapTier] = useState<CapTier>('large')

  const buy = useMutation({
    mutationFn: () =>
      api.testerPaperBuy({
        symbol: symbol.trim().toUpperCase(),
        quantity: Number(qty),
        cap_tier: capTier,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['testerSummary'] })
      queryClient.invalidateQueries({ queryKey: ['testerPositions'] })
      queryClient.invalidateQueries({ queryKey: ['testerTrades'] })
      setSymbol('')
    },
  })

  const symbols = watchlist.data ?? []

  return (
    <div className="card" style={{ marginBottom: '1.25rem' }}>
      <h2>Paper buy</h2>
      <p className="muted" style={{ fontSize: '0.85rem' }}>
        Pick a stock from your watchlist or type a symbol. This only affects the manual paper-testing book —
        not the bot portfolio.
      </p>
      {buy.error && <ErrorBox error={buy.error} />}
      <div className="grid" style={{ marginTop: '0.75rem' }}>
        <label>
          <span className="stat-label">Symbol</span>
          <input
            list="paper-tester-symbols"
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            placeholder="e.g. TCS"
          />
          <datalist id="paper-tester-symbols">
            {symbols.map((i) => (
              <option key={i.tradingsymbol} value={i.tradingsymbol} />
            ))}
          </datalist>
        </label>
        <label>
          <span className="stat-label">Quantity</span>
          <input
            type="number"
            min={1}
            value={qty}
            onChange={(e) => setQty(e.target.value)}
          />
        </label>
        <label>
          <span className="stat-label">Company size (your label)</span>
          <select value={capTier} onChange={(e) => setCapTier(e.target.value as CapTier)}>
            <option value="large">Large</option>
            <option value="midcap">Mid</option>
            <option value="smallcap">Small</option>
          </select>
        </label>
      </div>
      <button
        type="button"
        className="btn primary"
        style={{ marginTop: '0.75rem' }}
        disabled={!symbol.trim() || !Number(qty) || buy.isPending}
        onClick={() => buy.mutate()}
      >
        {buy.isPending ? 'Buying…' : 'Paper buy'}
      </button>

      {symbols.length > 0 && (
        <>
          <h3 style={{ marginTop: '1.25rem', fontSize: '1rem' }}>Watchlist shortcuts</h3>
          <div className="toolbar" style={{ flexWrap: 'wrap' }}>
            {symbols.map((i) => (
              <button
                key={i.tradingsymbol}
                type="button"
                className="btn"
                onClick={() => setSymbol(i.tradingsymbol)}
              >
                {i.tradingsymbol}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  )
}

function SectorBreakdown({ rows }: { rows: DetailedPosition[] }) {
  const sectors = useMemo(() => {
    const m = new Map<string, { value: number; symbols: string[] }>()
    for (const p of rows) {
      const sec = (p as DetailedPosition & { sector?: string }).sector ?? 'Unclassified'
      const cur = m.get(sec) ?? { value: 0, symbols: [] }
      cur.value += p.current_value
      cur.symbols.push(p.symbol)
      m.set(sec, cur)
    }
    const total = rows.reduce((s, p) => s + p.current_value, 0)
    return [...m.entries()]
      .map(([name, { value, symbols }]) => ({
        name,
        value,
        pct: total > 0 ? value / total : 0,
        symbols,
      }))
      .sort((a, b) => b.value - a.value)
  }, [rows])

  if (!rows.length) return null

  return (
    <div className="card" style={{ marginTop: '1.25rem' }}>
      <h2>By sector</h2>
      <ul style={{ margin: 0, paddingLeft: '1.1rem' }}>
        {sectors.map((s) => (
          <li key={s.name} style={{ marginBottom: '0.35rem' }}>
            <strong>{s.name}</strong> — {formatCurrency(s.value)} ({(s.pct * 100).toFixed(0)}%):{' '}
            {s.symbols.join(', ')}
          </li>
        ))}
      </ul>
    </div>
  )
}

export default function PaperTesting() {
  const queryClient = useQueryClient()
  const [tab, setTab] = useState<Tab>('portfolio')
  const [selectedDetail, setSelectedDetail] = useState<StockDetail | null>(null)

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
  const money = summary.data

  const totalPnl = rows.reduce((sum, p) => sum + p.unrealized_pnl, 0)
  const dayPnl = rows.reduce((sum, p) => sum + (p.day_pnl ?? 0), 0)
  const invested = rows.reduce((sum, p) => sum + p.invested, 0)
  const currentValue = rows.reduce((sum, p) => sum + p.current_value, 0)
  const byReturn = [...rows].sort((a, b) => b.unrealized_pnl_pct - a.unrealized_pnl_pct)
  const maxGainer = byReturn[0]
  const maxLoser = byReturn[byReturn.length - 1]

  if (positions.isLoading && tab === 'portfolio') return <Loading />

  return (
    <>
      <div className="page-head">
        <div>
          <h1 style={{ marginBottom: '0.15rem' }}>Paper testing</h1>
          <div className="muted" style={{ fontSize: '0.82rem' }}>
            Manual practice trades only. The bot and brain portfolios are separate — automatic buys show under{' '}
            <strong>Portfolio</strong>, not here.
          </div>
        </div>
        <span className="badge badge-paper">MANUAL PAPER</span>
      </div>

      <div className="toolbar" style={{ marginBottom: '1rem' }}>
        {(
          [
            ['portfolio', 'Portfolio'],
            ['list', 'Buy from list'],
            ['reports', 'Reports'],
          ] as [Tab, string][]
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            className={tab === id ? 'btn primary' : 'btn'}
            onClick={() => setTab(id)}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === 'list' && <BuyPanel />}

      {tab === 'reports' && (
        trades.isLoading ? (
          <Loading />
        ) : trades.error ? (
          <ErrorBox error={trades.error} />
        ) : (
          <ReportsPanel trades={trades.data ?? []} />
        )
      )}

      {tab === 'portfolio' && (
        <>
          {summary.error && <ErrorBox error={summary.error} />}
          {money && (
            <div className="grid">
              <Stat
                label="Paper test account value"
                value={formatCurrency(money.total_value)}
                sub={`Started with ${formatCurrency(money.starting_capital)}`}
                tone={pnlClass(money.total_value - money.starting_capital) as 'pos' | 'neg' | 'flat'}
              />
              <Stat label="Cash left" value={formatCurrency(money.cash)} sub="For manual paper buys" />
              <Stat
                label="Held in stocks"
                value={formatCurrency(currentValue)}
                sub={`${rows.length} stocks · ${formatCurrency(invested)} cost`}
              />
              <Stat
                label="Profit banked"
                value={formatCurrency(money.realized_pnl)}
                sub={`${money.total_trades} closed trade${money.total_trades === 1 ? '' : 's'}`}
                tone={pnlClass(money.realized_pnl) as 'pos' | 'neg' | 'flat'}
              />
            </div>
          )}

          {rows.length > 0 && (
            <div className="grid">
              <Stat
                label="Today's change"
                value={formatCurrency(dayPnl)}
                sub={todayIst()}
                tone={pnlClass(dayPnl) as 'pos' | 'neg' | 'flat'}
              />
              <Stat
                label="Open P&amp;L"
                value={formatCurrency(totalPnl)}
                sub={formatSignedPercent(invested ? totalPnl / invested : 0)}
                tone={pnlClass(totalPnl) as 'pos' | 'neg' | 'flat'}
              />
              {maxGainer && maxGainer.unrealized_pnl_pct > 0 && (
                <Stat
                  label="Best open"
                  value={maxGainer.symbol}
                  sub={`${CAP_LABEL[maxGainer.cap_tier as CapTier] ?? maxGainer.cap_tier ?? '—'} · ${formatSignedPercent(maxGainer.unrealized_pnl_pct)}`}
                  tone="pos"
                />
              )}
              {maxLoser && maxLoser.unrealized_pnl_pct < 0 && (
                <Stat
                  label="Worst open"
                  value={maxLoser.symbol}
                  sub={`${CAP_LABEL[maxLoser.cap_tier as CapTier] ?? maxLoser.cap_tier ?? '—'} · ${formatSignedPercent(maxLoser.unrealized_pnl_pct)}`}
                  tone="neg"
                />
              )}
            </div>
          )}

          <SectorBreakdown rows={rows} />

          <h2 style={{ marginTop: '1.5rem' }}>Open positions</h2>
          {close.error && <ErrorBox error={close.error} />}
          <div className="table-wrap">
            <PositionsTable
              rows={rows}
              onSelectDetail={setSelectedDetail}
              onSell={(p) => {
                if (confirm(`Paper sell all ${p.quantity} × ${p.symbol} at market?`)) {
                  close.mutate(p.id)
                }
              }}
              sellBusy={close.isPending}
              sellLabel="Paper sell"
              emptyLabel="No manual paper positions yet — use Buy from list."
            />
          </div>
        </>
      )}

      {selectedDetail && (
        <StockDetailModal detail={selectedDetail} onClose={() => setSelectedDetail(null)} />
      )}
    </>
  )
}
