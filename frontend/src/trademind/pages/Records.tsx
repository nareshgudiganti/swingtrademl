import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { api } from '../../api/client'
import type { Trade, TrackRecordSignal } from '../../api/types'
import { Card, PageHead, Tabs, Tag, inr, signed, toneClass } from '../ui'

const TABS = ['Trade history', "Version 1's picks", 'Strategy results'] as const
type TabName = (typeof TABS)[number]

// Plain one-liners for the strategies we know about. Anything else falls back
// to the code name with underscores removed — never an invented description.
const STRATEGY_PLAIN: Record<string, string> = {
  ml_swing_main: 'Large companies (model)',
  ml_swing_midcap: 'Mid-size companies (model)',
  ml_swing_smallcap: 'Small companies (model)',
  sma_crossover_benchmark: 'Simple yardstick (moving averages)',
  sma_crossover: 'Simple yardstick (moving averages)',
  brain: 'TradeMind brain (practice)',
  real_trading: 'Your own buys',
  long_term_value: 'Long-term picks',
}

const strategyPlain = (name: string | null) =>
  name ? (STRATEGY_PLAIN[name] ?? name.replace(/_/g, ' ')) : 'Unknown'

const money = (n: number) => `${n < 0 ? '−' : ''}₹${inr(Math.abs(n))}`
const day = (iso: string) =>
  new Date(iso).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })

function Loading() {
  return <p className="tm-dim">Loading…</p>
}

function Problem({ what }: { what: string }) {
  return <p className="tm-dim">Could not load {what} right now. Try again shortly.</p>
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div>
      <div className="tm-stat-label">{label}</div>
      <div className={`tm-stat-value ${tone ?? ''}`}>{value}</div>
    </div>
  )
}

// ---------------------------------------------------------- trade history --

function TradeHistory() {
  // Same call the old Reports page makes: the bot's own book, up to the
  // API's ceiling of 1000, newest first.
  const q = useQuery({ queryKey: ['trades', 1000], queryFn: () => api.trades(1000) })

  const rows = useMemo(
    () => [...(q.data ?? [])].sort((a, b) => new Date(b.exit_at).getTime() - new Date(a.exit_at).getTime()),
    [q.data],
  )
  const byStrategy = useMemo(() => {
    const m = new Map<string, { key: string; trades: number; wins: number; net: number }>()
    for (const t of rows) {
      const key = t.strategy_name ?? 'Unknown'
      const r = m.get(key) ?? { key, trades: 0, wins: 0, net: 0 }
      r.trades += 1
      r.wins += t.is_win ? 1 : 0
      r.net += t.net_pnl
      m.set(key, r)
    }
    return [...m.values()].sort((a, b) => b.net - a.net)
  }, [rows])

  if (q.isLoading) return <Loading />
  if (q.isError) return <Problem what="your trade history" />
  if (!rows.length) {
    return (
      <Card title="Trade history">
        <p className="tm-dim">No finished trades yet. Each trade will show up here once the bot has sold it.</p>
      </Card>
    )
  }

  const wins = rows.filter((t: Trade) => t.is_win).length
  const net = rows.reduce((s, t) => s + t.net_pnl, 0)
  const charges = rows.reduce((s, t) => s + t.charges, 0)

  return (
    <div className="tm-grid">
      <Card title="Overall" sub="Every finished trade, after all costs">
        <div className="tm-grid tm-cols-4">
          <Stat label="Finished trades" value={String(rows.length)} />
          <Stat label="Made money" value={String(wins)} tone="tm-pos" />
          <Stat label="Lost money" value={String(rows.length - wins)} tone={rows.length - wins > 0 ? 'tm-neg' : ''} />
          <Stat label="Total result" value={money(net)} tone={toneClass(net)} />
        </div>
        <p className="tm-dim" style={{ marginTop: '0.6rem' }}>
          Fees and taxes paid on these trades: {money(charges)}.
        </p>
      </Card>

      {byStrategy.length > 1 && (
        <Card title="Result by strategy" sub="Which approach is earning, and which is not">
          <div className="tm-table-wrap">
            <table className="tm-table">
              <thead>
                <tr>
                  <th>Strategy</th>
                  <th className="tm-right">Trades</th>
                  <th className="tm-right">Made money</th>
                  <th className="tm-right">Result</th>
                </tr>
              </thead>
              <tbody>
                {byStrategy.map((r) => (
                  <tr key={r.key}>
                    <td title={r.key}>{strategyPlain(r.key)}</td>
                    <td className="tm-right">{r.trades}</td>
                    <td className="tm-right">{r.wins}</td>
                    <td className={`tm-right ${toneClass(r.net)}`}>{money(r.net)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      <Card title="Every finished trade" sub="Newest first">
        <div className="tm-table-wrap">
          <table className="tm-table">
            <thead>
              <tr>
                <th>Stock</th>
                <th>Bought</th>
                <th>Sold</th>
                <th className="tm-right">Shares</th>
                <th className="tm-right">Bought at</th>
                <th className="tm-right">Sold at</th>
                <th className="tm-right">Result</th>
                <th className="tm-right">Result %</th>
                <th>Why it was sold</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((t) => (
                <tr key={t.id}>
                  <td title={t.strategy_name ?? ''}>
                    <strong>{t.symbol}</strong>
                  </td>
                  <td>{day(t.entry_at)}</td>
                  <td>{day(t.exit_at)}</td>
                  <td className="tm-right">{t.quantity}</td>
                  <td className="tm-right">₹{inr(t.entry_price)}</td>
                  <td className="tm-right">₹{inr(t.exit_price)}</td>
                  <td className={`tm-right ${toneClass(t.net_pnl)}`}>{money(t.net_pnl)}</td>
                  <td className={`tm-right ${toneClass(t.net_pnl)}`}>{signed(t.return_pct * 100)}</td>
                  <td className="tm-wrap" title={t.exit_reason ?? ''}>
                    {t.exit_reason_label ?? t.exit_reason ?? '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  )
}

// ------------------------------------------------------- version 1's picks --

const OUTCOME: Record<string, { label: string; tone: 'green' | 'red' | 'amber' }> = {
  TARGET_HIT: { label: 'Reached its goal', tone: 'green' },
  STOP_LOSS_HIT: { label: 'Fell to its safety price', tone: 'red' },
  EXPIRED_NO_HIT: { label: 'Time ran out', tone: 'amber' },
}

function ScanTable({ rows }: { rows: TrackRecordSignal[] }) {
  return (
    <div className="tm-table-wrap">
      <table className="tm-table">
        <thead>
          <tr>
            <th>Stock</th>
            <th>Picked on</th>
            <th className="tm-right">Price then</th>
            <th className="tm-right">Price now</th>
            <th className="tm-right">Safety price</th>
            <th className="tm-right">Goal price</th>
            <th>How it went</th>
            <th className="tm-right">Result</th>
            <th>Why it was picked</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const o = r.outcome ? OUTCOME[r.outcome] : null
            const pct = r.was_executed && r.trade_return_pct != null ? r.trade_return_pct : r.outcome_pct
            return (
              <tr key={r.signal_id}>
                <td title={r.strategy_name}>
                  <strong>{r.symbol}</strong>
                  {r.name && <div className="tm-dim">{r.name}</div>}
                </td>
                <td>
                  {day(r.generated_at)}
                  <div className="tm-dim">{r.age_days} days ago</div>
                </td>
                <td className="tm-right">₹{inr(r.price)}</td>
                <td className="tm-right">{r.current_price != null ? `₹${inr(r.current_price)}` : '—'}</td>
                <td className="tm-right">₹{inr(r.stop_loss)}</td>
                <td className="tm-right">₹{inr(r.take_profit)}</td>
                <td>{o ? <Tag tone={o.tone}>{o.label}</Tag> : <Tag tone="blue">Still open</Tag>}</td>
                <td className={`tm-right ${pct != null ? toneClass(pct) : 'tm-dim'}`}>
                  {pct != null ? signed(pct * 100) : '—'}
                </td>
                <td className="tm-wrap">{r.reason ?? '—'}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function Picks() {
  const buy = useQuery({ queryKey: ['buyList'], queryFn: api.buyList })
  const scan = useQuery({ queryKey: ['scanResults'], queryFn: api.scanResults })

  return (
    <div className="tm-grid">
      <p className="tm-dim">
        This is the original model's list (version 1). It is separate from the brain's ideas on the
        Opportunities page.
      </p>

      <Card title="Today's buy list" sub="Stocks the original model would buy right now">
        {buy.isLoading && <Loading />}
        {buy.isError && <Problem what="the buy list" />}
        {buy.data && buy.data.length === 0 && (
          <p className="tm-dim">Nothing on the buy list today. The model found no stock worth buying.</p>
        )}
        {buy.data && buy.data.length > 0 && (
          <div className="tm-table-wrap">
            <table className="tm-table">
              <thead>
                <tr>
                  <th>Stock</th>
                  <th className="tm-right">Price</th>
                  <th className="tm-right">Sell if it falls to</th>
                  <th className="tm-right">Goal price</th>
                  <th className="tm-right">Confidence</th>
                  <th>Why</th>
                </tr>
              </thead>
              <tbody>
                {buy.data.map((r) => (
                  <tr key={`${r.symbol}-${r.strategy_name}`}>
                    <td title={r.strategy_name}>
                      <strong>{r.symbol}</strong>
                      {r.name && <div className="tm-dim">{r.name}</div>}
                    </td>
                    <td className="tm-right">₹{inr(r.price)}</td>
                    <td className="tm-right">{r.stop_loss != null ? `₹${inr(r.stop_loss)}` : '—'}</td>
                    <td className="tm-right">{r.take_profit != null ? `₹${inr(r.take_profit)}` : '—'}</td>
                    <td className="tm-right">{r.confidence != null ? `${(r.confidence * 100).toFixed(0)}%` : '—'}</td>
                    <td className="tm-wrap">{r.reason ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card title="What the daily scan found" sub="Every pick so far, and how it turned out">
        {scan.isLoading && <Loading />}
        {scan.isError && <Problem what="the scan results" />}
        {scan.data && scan.data.length === 0 && (
          <p className="tm-dim">The daily scan has not made any picks yet.</p>
        )}
        {scan.data && scan.data.length > 0 && <ScanTable rows={scan.data} />}
      </Card>
    </div>
  )
}

// -------------------------------------------------------- strategy results --

function StrategyResults() {
  const q = useQuery({ queryKey: ['strategyPerformance'], queryFn: api.strategyPerformance })

  if (q.isLoading) return <Loading />
  if (q.isError) return <Problem what="the strategy results" />
  const list = q.data?.strategies ?? []
  if (!list.length) {
    return (
      <Card title="Strategy results">
        <p className="tm-dim">No strategies have any results yet.</p>
      </Card>
    )
  }

  return (
    <div className="tm-grid">
      <p className="tm-dim">
        A strategy is one way of picking stocks. Each is tried on its own so you can see which works best.
        This page is for reading only.
      </p>
      {list.map((s) => {
        const w = [
          { label: 'Last 30 days', v: s.windows.last_30d },
          { label: 'Last 90 days', v: s.windows.last_90d },
          { label: 'Since the start', v: s.windows.all_time },
        ]
        return (
          <Card
            key={s.id}
            title={<span title={s.name}>{strategyPlain(s.name)}</span>}
            sub={`Holding ${s.open_positions} now`}
            action={<Tag tone={s.is_active ? 'green' : 'amber'}>{s.is_active ? 'Running' : 'Paused'}</Tag>}
          >
            <div className="tm-table-wrap">
              <table className="tm-table">
                <thead>
                  <tr>
                    <th>Period</th>
                    <th className="tm-right">Finished trades</th>
                    <th className="tm-right">Made money</th>
                    <th className="tm-right">Result</th>
                  </tr>
                </thead>
                <tbody>
                  {w.map(({ label, v }) => (
                    <tr key={label}>
                      <td>{label}</td>
                      <td className="tm-right">{v.trades}</td>
                      <td className="tm-right">{v.trades ? `${(v.win_rate * 100).toFixed(0)}%` : '—'}</td>
                      <td className={`tm-right ${v.trades ? toneClass(v.net_pnl) : 'tm-dim'}`}>
                        {v.trades ? money(v.net_pnl) : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        )
      })}
    </div>
  )
}

export default function Records() {
  const [tab, setTab] = useState<TabName>('Trade history')
  return (
    <div className="tm-page tm-grid">
      <PageHead title="Records" sub="Everything that has already happened, for reading only" />
      <Tabs tabs={TABS} active={tab} onChange={setTab} />
      {tab === 'Trade history' && <TradeHistory />}
      {tab === "Version 1's picks" && <Picks />}
      {tab === 'Strategy results' && <StrategyResults />}
    </div>
  )
}
