// My Holdings (real money): the results of every share you sold. Built from the sales saved for your real book
// ("Saved as sold" and real sells placed here), so it is kept apart from the Portfolio page's practice trades.
// How many sold, profit or loss, how many days each was held, and what the stock did after you sold it.
// Display only: nothing here places or changes an order.

import { useQuery } from '@tanstack/react-query'
import type { ReactNode } from 'react'

import { api } from '../../api/client'
import type { Trade } from '../../api/types'
import { PageState, QueryNotice } from '../PageState'
import { SortTh, useSort } from '../sort'
import StockLink from '../StockLink'
import { Card, inr, signed, toneClass } from '../ui'
import { closedSummary } from './portfolioViews'

const rupees = (n: number) => `₹${inr(Math.abs(n), 0)}`
const signedRupees = (n: number) => `${n > 0 ? '+' : n < 0 ? '−' : ''}${rupees(n)}`
const day = (s: string) => new Date(s).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })

type Key = 'symbol' | 'bought' | 'sold' | 'days' | 'profit' | 'pct'

function Stat({ label, value, note, tone }: { label: string; value: ReactNode; note?: string; tone?: string }) {
  return (
    <div>
      <div className="tm-stat-label">{label}</div>
      <div className={`tm-stat-value ${tone ?? ''}`}>{value}</div>
      {note && <div className="tm-dim">{note}</div>}
    </div>
  )
}

function downloadCsv(trades: Trade[]) {
  const header = ['Stock', 'Shares', 'Bought on', 'Sold on', 'Days held', 'Buy price', 'Sell price', 'Profit before charges', 'Charges', 'Profit', 'Profit %', 'Why sold']
  const rows = trades.map((t) => [
    t.symbol, t.quantity, t.entry_at.slice(0, 10), t.exit_at.slice(0, 10), t.holding_days, t.entry_price, t.exit_price,
    t.gross_pnl, t.charges, t.net_pnl, (t.return_pct * 100).toFixed(2), t.exit_reason_label ?? t.exit_reason ?? '',
  ])
  const esc = (v: string | number) => `"${String(v).replace(/"/g, '""')}"`
  const text = [header, ...rows].map((r) => r.map(esc).join(',')).join('\n')
  const url = URL.createObjectURL(new Blob([text], { type: 'text/csv;charset=utf-8' }))
  const a = document.createElement('a')
  a.href = url
  a.download = 'my-holdings-sold-shares.csv'
  a.click()
  URL.revokeObjectURL(url)
}

export function SoldTable({ trades }: { trades: Trade[] }) {
  const { sorted, sorter } = useSort<Trade, Key>(
    trades,
    {
      symbol: (t) => t.symbol,
      bought: (t) => t.entry_at,
      sold: (t) => t.exit_at,
      days: (t) => t.holding_days,
      profit: (t) => t.net_pnl,
      pct: (t) => t.return_pct,
    },
    { key: 'sold', dir: 'desc' },
    { symbol: 'asc' },
  )
  return (
    <div className="tm-table-wrap" tabIndex={0} role="region" aria-label="Table, scroll sideways to see more" data-testid="real-sold-table">
      <table className="tm-table">
        <thead>
          <tr>
            <SortTh sorter={sorter} k="symbol">Stock</SortTh>
            <SortTh sorter={sorter} k="bought">Bought on</SortTh>
            <SortTh sorter={sorter} k="sold">Sold on</SortTh>
            <SortTh sorter={sorter} k="days" right>Days held</SortTh>
            <th className="tm-right">Shares</th>
            <th className="tm-right">Bought at</th>
            <th className="tm-right">Sold at</th>
            <SortTh sorter={sorter} k="profit" right>Profit or loss</SortTh>
            <SortTh sorter={sorter} k="pct" right>Return</SortTh>
            <th>Why sold</th>
            <th className="tm-right" title="How the stock moved in the 5 trading days after you sold it">5 days later</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((t) => (
            <tr key={t.id}>
              <td><StockLink symbol={t.symbol} withScore={false} /></td>
              <td>{day(t.entry_at)}</td>
              <td>{day(t.exit_at)}</td>
              <td className="tm-right">{t.holding_days}</td>
              <td className="tm-right">{t.quantity}</td>
              <td className="tm-right">{rupees(t.entry_price)}</td>
              <td className="tm-right">{rupees(t.exit_price)}</td>
              <td className={`tm-right ${toneClass(t.net_pnl)}`} title={`Before charges ${signedRupees(t.gross_pnl)}, charges ${rupees(t.charges)}`}>
                {signedRupees(t.net_pnl)}
              </td>
              <td className={`tm-right ${toneClass(t.net_pnl)}`}>{signed(t.return_pct * 100)}</td>
              <td>{t.exit_reason_label ?? t.exit_reason ?? '—'}</td>
              <td className="tm-right tm-dim">
                {t.return_5d_after_exit != null ? signed(t.return_5d_after_exit * 100) : '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** The numbers above the table. Exported so it can be tested without the network. */
export function SoldScoreboard({ trades }: { trades: Trade[] }) {
  const s = closedSummary(trades)
  const stocks = new Set(trades.map((t) => t.symbol)).size
  const days = trades.map((t) => t.holding_days)
  const avgDays = days.reduce((a, b) => a + b, 0) / days.length
  const longest = trades.reduce((a, b) => (b.holding_days > a.holding_days ? b : a))
  return (
    <div data-testid="real-sold-scoreboard" style={{ marginBottom: '0.8rem' }}>
      <div className="tm-grid tm-cols-4">
        <Stat label="Sales" value={String(s.count)} note={`${stocks} different stock${stocks === 1 ? '' : 's'}`} />
        <Stat label="Made money / lost money" value={`${s.wins} / ${s.losses}`} note={s.winRate === null ? undefined : `${s.winRate.toFixed(0)}% of sales made money`} />
        <Stat label="Total profit or loss" value={signedRupees(s.net)} tone={toneClass(s.net)} note="after charges" />
        <Stat label="Held for, on average" value={`${Math.round(avgDays)} days`} note={`longest ${longest.symbol}, ${longest.holding_days} days`} />
      </div>
      <div className="tm-grid tm-cols-4" style={{ marginTop: '0.6rem' }}>
        {s.best && <Stat label="Best sale" value={<StockLink symbol={s.best.symbol} withScore={false} />} tone={toneClass(s.best.net)} note={signedRupees(s.best.net)} />}
        {s.worst && <Stat label="Worst sale" value={<StockLink symbol={s.worst.symbol} withScore={false} />} tone={toneClass(s.worst.net)} note={signedRupees(s.worst.net)} />}
        <Stat label="Average win" value={s.avgWin === null ? '—' : signedRupees(s.avgWin)} tone={s.avgWin === null ? undefined : toneClass(s.avgWin)} />
        <Stat label="Average loss" value={s.avgLoss === null ? '—' : signedRupees(s.avgLoss)} tone={s.avgLoss === null ? undefined : toneClass(s.avgLoss)} />
      </div>
    </div>
  )
}

export default function RealSoldResults() {
  const q = useQuery({ queryKey: ['realTrades'], queryFn: () => api.realTrades(), retry: false })
  const trades = q.data ?? []
  return (
    <Card
      title="Shares you sold: results"
      sub="Every sale saved for your real shares, all time. Profit is after charges. This is kept apart from the Portfolio page, which is for practice trades."
      action={
        trades.length > 0 ? (
          <button className="tm-btn tm-btn-ghost" onClick={() => downloadCsv(trades)}>Download as spreadsheet</button>
        ) : undefined
      }
    >
      <QueryNotice q={q} what="your sold shares" />
      {q.data && trades.length === 0 && (
        <PageState kind="empty" reason="No sales saved yet. When you press “Sold” or sell for real on a share above, it is saved here with its profit or loss and how many days you held it." />
      )}
      {trades.length > 0 && (
        <>
          <SoldScoreboard trades={trades} />
          <SoldTable trades={trades} />
        </>
      )}
    </Card>
  )
}
