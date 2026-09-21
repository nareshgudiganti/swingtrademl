import { useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../api/client'
import type { RealReport as Report } from '../api/types'
import Stat from '../components/Stat'
import { ErrorBox, Loading } from '../components/Loading'
import { formatCurrency, formatDate, formatDateTime, formatPercent, pnlClass } from '../lib/format'

type PeriodKey = 'month' | '30d' | 'fy' | 'all'

const PERIODS: { key: PeriodKey; label: string }[] = [
  { key: 'month', label: 'This month' },
  { key: '30d', label: 'Last 30 days' },
  { key: 'fy', label: 'This financial year' },
  { key: 'all', label: 'All time' },
]

const iso = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`

function rangeFor(key: PeriodKey): { start?: string; end?: string } {
  const now = new Date()
  if (key === 'month') return { start: iso(new Date(now.getFullYear(), now.getMonth(), 1)) }
  if (key === '30d') return { start: iso(new Date(now.getTime() - 30 * 86_400_000)) }
  if (key === 'fy') {
    // Indian financial year: 1 April to 31 March.
    const year = now.getMonth() >= 3 ? now.getFullYear() : now.getFullYear() - 1
    return { start: iso(new Date(year, 3, 1)) }
  }
  return {}
}

const signed = (value: number) => `${value > 0 ? '+' : ''}${formatCurrency(value)}`

function downloadCsv(name: string, header: string[], rows: (string | number)[][]) {
  const escape = (v: string | number) => `"${String(v).replace(/"/g, '""')}"`
  const text = [header, ...rows].map((r) => r.map(escape).join(',')).join('\n')
  const url = URL.createObjectURL(new Blob([text], { type: 'text/csv;charset=utf-8' }))
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  URL.revokeObjectURL(url)
}

function exportReport(report: Report, label: string) {
  downloadCsv(
    `sales-${label}.csv`,
    ['Stock', 'Quantity', 'Bought on', 'Sold on', 'Buy price', 'Sell price', 'Profit before charges', 'Charges', 'Profit', 'Profit %', 'Days held'],
    report.closed.map((c) => [
      c.symbol, c.quantity, c.buy_date.slice(0, 10), c.sell_date.slice(0, 10), c.buy_price,
      c.sell_price, c.gross_pnl, c.charges, c.net_pnl, c.pnl_pct, c.holding_days,
    ]),
  )
  downloadCsv(
    `buys-and-sells-${label}.csv`,
    ['Date', 'Type', 'Stock', 'Quantity', 'Price', 'Amount'],
    report.fills.map((f) => [f.executed_at.slice(0, 19).replace('T', ' '), f.side, f.symbol, f.quantity, f.price, f.value]),
  )
}

/**
 * Buy & sell report for the real Zerodha account. Read-only — nothing here
 * places or changes an order.
 *
 * Profit is "first bought, first sold" and is shown after charges. Zerodha's
 * API only shares today's trades, so history builds up from when the app
 * started saving them; the tradebook file fills in anything older.
 */
export default function RealReport() {
  const queryClient = useQueryClient()
  const fileInput = useRef<HTMLInputElement>(null)
  const [period, setPeriod] = useState<PeriodKey>('30d')
  const range = useMemo(() => rangeFor(period), [period])

  const report = useQuery({
    queryKey: ['realReport', range],
    queryFn: () => api.realReport(range),
    retry: false,
  })

  const refreshed = () => queryClient.invalidateQueries({ queryKey: ['realReport'] })
  const sync = useMutation({ mutationFn: api.syncRealTrades, onSuccess: refreshed })
  const upload = useMutation({ mutationFn: (f: File) => api.importTradebook(f), onSuccess: refreshed })

  if (report.isLoading) return <Loading />
  if (report.isError) return <ErrorBox error={report.error} />
  const data = report.data!
  const s = data.summary
  const noHistory = data.records.total_fills === 0
  const salesCount = s.winning_sales + s.losing_sales
  const periodLabel = PERIODS.find((p) => p.key === period)!.label.toLowerCase().replace(/ /g, '-')

  const importControls = (
    <div className="row" style={{ gap: '0.5rem', flexWrap: 'wrap' }}>
      <button onClick={() => sync.mutate()} disabled={sync.isPending}>
        {sync.isPending ? 'Fetching…' : "Fetch today's trades"}
      </button>
      <button onClick={() => fileInput.current?.click()} disabled={upload.isPending}>
        {upload.isPending ? 'Reading file…' : 'Add Zerodha tradebook file'}
      </button>
      <input
        ref={fileInput}
        type="file"
        accept=".csv,text/csv"
        hidden
        onChange={(e) => {
          const f = e.target.files?.[0]
          if (f) upload.mutate(f)
          e.target.value = ''
        }}
      />
    </div>
  )

  return (
    <>
      <div className="row" style={{ gap: '0.4rem', flexWrap: 'wrap', margin: '0.5rem 0 1rem' }}>
        {PERIODS.map((p) => (
          <button key={p.key} className={period === p.key ? 'primary' : ''} onClick={() => setPeriod(p.key)}>
            {p.label}
          </button>
        ))}
      </div>

      {sync.isError && <ErrorBox error={sync.error} />}
      {upload.isError && <ErrorBox error={upload.error} />}
      {sync.isSuccess && (
        <div className="banner banner-ok">{sync.data.message} {sync.data.detail}</div>
      )}
      {upload.isSuccess && (
        <div className="banner banner-ok">{upload.data.message} {upload.data.detail}</div>
      )}
      {data.holdings_note && (
        <div className="banner banner-warn">
          Shares you still hold are not shown: {data.holdings_note}
        </div>
      )}

      {noHistory ? (
        <div className="card" style={{ marginBottom: '1rem' }}>
          <h3 style={{ marginTop: 0 }}>No buys or sells saved yet</h3>
          <p className="muted">
            Zerodha only shares the trades you made <em>today</em>, so this report starts empty and
            fills up on its own — the app saves your trades every weekday after the market closes.
          </p>
          <p className="muted">
            To see what you bought and sold <em>before</em> now, download your tradebook from Zerodha
            (Console → Reports → Tradebook → Equity → Download CSV) and add it here. Buys and sells
            already saved are never counted twice.
          </p>
          {importControls}
        </div>
      ) : (
        <>
          <div className="grid">
            <Stat
              label="Profit from shares you sold"
              value={signed(s.realized_pnl)}
              tone={pnlClass(s.realized_pnl) as 'pos' | 'neg' | 'flat'}
              sub={
                salesCount
                  ? `${formatCurrency(s.gross_pnl)} before charges − ${formatCurrency(s.charges)} charges`
                  : 'No sales in this period'
              }
            />
            <Stat
              label="Sales that made money"
              value={salesCount ? `${s.winning_sales} of ${salesCount}` : '—'}
              sub={
                s.average_holding_days !== null
                  ? `Held for ${Math.round(s.average_holding_days)} days on average`
                  : undefined
              }
            />
            <Stat
              label="Bought"
              value={formatCurrency(s.bought_value)}
              sub={`${s.buy_count} buy${s.buy_count === 1 ? '' : 's'}`}
            />
            <Stat
              label="Sold"
              value={formatCurrency(s.sold_value)}
              sub={`${s.sell_count} sale${s.sell_count === 1 ? '' : 's'}`}
            />
            {s.open_pnl !== null && (
              <Stat
                label="Shares you still hold, right now"
                value={signed(s.open_pnl)}
                tone={pnlClass(s.open_pnl) as 'pos' | 'neg' | 'flat'}
                sub={`Worth ${formatCurrency(s.open_value ?? 0)} — not booked until you sell`}
              />
            )}
            {s.best_stock && (
              <Stat label="Best stock" value={s.best_stock.symbol} sub={signed(s.best_stock.pnl)} tone="pos" />
            )}
            {s.worst_stock && (
              <Stat label="Worst stock" value={s.worst_stock.symbol} sub={signed(s.worst_stock.pnl)} tone="neg" />
            )}
          </div>

          {data.unmatched_sales.length > 0 && (
            <div className="banner banner-warn">
              {data.unmatched_sales.length} sale{data.unmatched_sales.length === 1 ? '' : 's'} (
              {[...new Set(data.unmatched_sales.map((u) => u.symbol))].join(', ')}) have no buy on
              record, so their profit can’t be worked out and is left out. Adding your Zerodha
              tradebook file fixes this.
            </div>
          )}

          <h3 style={{ marginTop: '1.5rem' }}>By stock</h3>
          {data.by_stock.length === 0 ? (
            <p className="muted">Nothing bought or sold in this period.</p>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th className="sticky-col">Stock</th>
                    <th className="num">Bought</th>
                    <th className="num">Sold</th>
                    <th className="num">Profit from sales</th>
                    <th className="num">Still holding</th>
                    <th className="num">Profit on those (not booked)</th>
                  </tr>
                </thead>
                <tbody>
                  {data.by_stock.map((r) => (
                    <tr key={r.symbol}>
                      <td className="sticky-col"><strong>{r.symbol}</strong></td>
                      <td className="num">{r.bought_qty ? `${r.bought_qty} · ${formatCurrency(r.bought_value)}` : '—'}</td>
                      <td className="num">{r.sold_qty ? `${r.sold_qty} · ${formatCurrency(r.sold_value)}` : '—'}</td>
                      <td className={`num ${r.sold_qty ? pnlClass(r.realized_pnl) : ''}`}>
                        {r.sold_qty ? signed(r.realized_pnl) : '—'}
                      </td>
                      <td className="num">
                        {r.open_qty ? `${r.open_qty} @ ${formatCurrency(r.open_avg_price ?? 0)}` : '—'}
                      </td>
                      <td className={`num ${r.open_pnl !== null ? pnlClass(r.open_pnl) : ''}`}>
                        {r.open_pnl !== null && r.open_qty ? signed(r.open_pnl) : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <h3 style={{ marginTop: '1.5rem' }}>Shares you sold, and what each sale earned</h3>
          {data.closed.length === 0 ? (
            <p className="muted">No sales in this period.</p>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th className="sticky-col">Stock</th>
                    <th>Bought on</th>
                    <th>Sold on</th>
                    <th className="num">Shares</th>
                    <th className="num">Bought at</th>
                    <th className="num">Sold at</th>
                    <th className="num">Profit</th>
                    <th className="num">Days held</th>
                  </tr>
                </thead>
                <tbody>
                  {data.closed.map((c, i) => (
                    <tr key={`${c.symbol}-${c.sell_date}-${i}`}>
                      <td className="sticky-col"><strong>{c.symbol}</strong></td>
                      <td>{formatDate(c.buy_date)}</td>
                      <td>{formatDate(c.sell_date)}</td>
                      <td className="num">{c.quantity}</td>
                      <td className="num">{formatCurrency(c.buy_price)}</td>
                      <td className="num">{formatCurrency(c.sell_price)}</td>
                      <td className={`num ${pnlClass(c.net_pnl)}`}>
                        {signed(c.net_pnl)}{' '}
                        <span className="muted">({formatPercent(c.pnl_pct / 100, 1)})</span>
                      </td>
                      <td className="num">{c.holding_days}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="muted" style={{ fontSize: '0.78rem', marginTop: '0.4rem' }}>
            Profit is after Zerodha and exchange charges. Sales are matched to your oldest shares
            first, the same way Zerodha does.
          </div>

          <h3 style={{ marginTop: '1.5rem' }}>Every buy and sell</h3>
          {data.fills.length === 0 ? (
            <p className="muted">Nothing bought or sold in this period.</p>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>When</th>
                    <th>Type</th>
                    <th className="sticky-col">Stock</th>
                    <th className="num">Shares</th>
                    <th className="num">Price</th>
                    <th className="num">Amount</th>
                  </tr>
                </thead>
                <tbody>
                  {data.fills.map((f) => (
                    <tr key={f.id}>
                      <td>{formatDateTime(f.executed_at)}</td>
                      <td>
                        <span className={`pill-action ${f.side === 'BUY' ? 'buy' : 'sell'}`}>
                          {f.side === 'BUY' ? 'BOUGHT' : 'SOLD'}
                        </span>
                      </td>
                      <td className="sticky-col"><strong>{f.symbol}</strong></td>
                      <td className="num">{f.quantity}</td>
                      <td className="num">{formatCurrency(f.price)}</td>
                      <td className="num">{formatCurrency(f.value)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <div className="card" style={{ marginTop: '1.5rem' }}>
            <div className="muted" style={{ marginBottom: '0.6rem', fontSize: '0.85rem' }}>
              Saved trades go back to{' '}
              <strong>{data.records.first_at ? formatDate(data.records.first_at) : '—'}</strong>{' '}
              ({data.records.total_fills} in total). New trades are saved automatically every
              weekday after the market closes. For anything older, add your Zerodha tradebook file.
            </div>
            <div className="row" style={{ gap: '0.5rem', flexWrap: 'wrap' }}>
              {importControls}
              <button onClick={() => exportReport(data, periodLabel)}>Download as spreadsheet</button>
            </div>
          </div>
        </>
      )}
    </>
  )
}
