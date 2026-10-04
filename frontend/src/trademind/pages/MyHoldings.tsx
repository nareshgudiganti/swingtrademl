import { useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../../api/client'
import type { DetailedPosition, RealReport } from '../../api/types'
import { Confirm } from '../Confirm'
import { Card, PageHead, Tabs, Tag, inr, signed, toneClass } from '../ui'

const TABS = ['My holdings', 'Straight from Zerodha', 'Real-money report'] as const
type TabId = (typeof TABS)[number]

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

const rupees = (n: number) => `₹${inr(n)}`
const signedRupees = (n: number) => `${n > 0 ? '+' : n < 0 ? '−' : ''}₹${inr(Math.abs(n))}`
const day = (s: string) =>
  new Date(s).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })
const dayTime = (s: string) =>
  new Date(s).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
const pct = (n: number, digits = 0) => `${(n * 100).toFixed(digits)}%`

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

function exportReport(report: RealReport, label: string) {
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

// One plain line per bot verdict (same meaning as the old page).
const VERDICT: Record<DetailedPosition['action_code'], { head: string; tone: 'red' | 'amber' | 'green' | 'blue' }> = {
  exit: { head: 'The bot would sell this one.', tone: 'red' },
  alert: { head: 'An alert has already been sent about this one.', tone: 'red' },
  weak: { head: 'Losing steam, but not a sell signal yet.', tone: 'amber' },
  dip: { head: 'Confidence has dipped since you bought it.', tone: 'amber' },
  hold: { head: 'Steady, no change.', tone: 'blue' },
  bullish: { head: 'Still looking good.', tone: 'green' },
}

const confidenceText = (p: DetailedPosition) =>
  p.entry_confidence != null || p.last_confidence != null
    ? `${p.entry_confidence != null ? pct(p.entry_confidence) : '—'} → ${p.last_confidence != null ? pct(p.last_confidence) : '—'}`
    : '—'

function stopText(p: DetailedPosition) {
  if (p.stop_loss == null) return '—'
  const gap = p.current_price > 0 ? (p.current_price - p.stop_loss) / p.current_price : null
  if (gap == null) return rupees(p.stop_loss)
  return `${rupees(p.stop_loss)} (${pct(Math.abs(gap), 1)} ${gap < 0 ? 'below, passed' : 'away'})`
}

/** Asks for the price you sold at, then records it. Never places an order. */
function SoldDialog({
  position,
  onSubmit,
  onClose,
}: {
  position: DetailedPosition
  onSubmit: (id: number, price: number) => Promise<unknown>
  onClose: () => void
}) {
  const [price, setPrice] = useState(String(position.current_price))
  return (
    <Confirm
      title={`Mark ${position.symbol} as sold`}
      confirmLabel="Save as sold"
      onClose={onClose}
      onConfirm={async () => {
        const value = Number(price)
        if (!price.trim() || !Number.isFinite(value) || value <= 0) {
          throw new Error('Please type the price you sold at, per share. It must be more than zero.')
        }
        await onSubmit(position.id, value)
      }}
    >
      <p style={{ margin: '0 0 0.6rem' }}>
        Use this only for shares you have <strong>already sold in Zerodha</strong>. It only updates your
        record here. It does <strong>not</strong> place any order.
      </p>
      <label style={{ display: 'block' }}>
        <span className="tm-dim" style={{ fontSize: '0.75rem' }}>
          The price you sold at, per share (₹)
        </span>
        <input
          className="tm-input"
          style={{ width: '100%', marginTop: 4 }}
          type="number"
          inputMode="decimal"
          min="0"
          step="any"
          required
          value={price}
          onChange={(e) => setPrice(e.target.value)}
        />
      </label>
    </Confirm>
  )
}

function HoldingsTab() {
  const queryClient = useQueryClient()
  const [sold, setSold] = useState<DetailedPosition | null>(null)
  const [askImport, setAskImport] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)

  // Zerodha's own list, used only to count what isn't tracked here yet.
  const holdings = useQuery({ queryKey: ['holdings'], queryFn: api.holdings, retry: false })
  // Not gated on the strategy existing: importing creates it on demand.
  const tracked = useQuery({ queryKey: ['realPositions'], queryFn: api.realPositions })

  const importHoldings = useMutation({
    mutationFn: () => api.importRealHoldings(),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['realPositions'] })
      queryClient.invalidateQueries({ queryKey: ['strategies'] })
      queryClient.invalidateQueries({ queryKey: ['holdings'] })
      const n = (s: string) => data.filter((r) => r.status === s).length
      setNotice(`Copied ${n('imported')} new · already in the list ${n('already_tracked')} · skipped ${n('skipped')}`)
    },
  })

  const manualClose = useMutation({
    mutationFn: ({ id, exitPrice }: { id: number; exitPrice: number }) => api.manualClosePosition(id, exitPrice),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['realPositions'] })
      queryClient.invalidateQueries({ queryKey: ['trades'] })
      queryClient.invalidateQueries({ queryKey: ['realReport'] })
      setNotice('Saved as sold. No order was placed.')
    },
  })

  const rows = tracked.data ?? []
  const totals = useMemo(() => {
    const invested = rows.reduce((s, p) => s + p.invested, 0)
    const current = rows.reduce((s, p) => s + p.current_value, 0)
    return { invested, current, pnl: current - invested }
  }, [rows])
  const attention = useMemo(() => rows.filter((p) => p.action_code === 'exit' || p.action_code === 'alert'), [rows])
  const untracked = useMemo(() => {
    const have = new Set(rows.map((p) => p.symbol))
    return (holdings.data ?? []).filter((h) => h.quantity > 0 && !have.has(h.symbol)).length
  }, [holdings.data, rows])

  return (
    <>
      <Card
        title="Shares you bought yourself"
        sub="Your real Zerodha shares, read by the bot each day. Nothing here buys or sells anything."
        action={
          <button className="tm-btn" onClick={() => setAskImport(true)} disabled={importHoldings.isPending}>
            {untracked > 0 ? `Import ${untracked} new from Zerodha` : 'Import from Zerodha'}
          </button>
        }
      >
        {notice && <div className="tm-callout" style={{ marginBottom: '0.6rem' }}>{notice}</div>}
        {tracked.isLoading && <p className="tm-dim">Loading your shares…</p>}
        {tracked.isError && (
          <p className="tm-neg">Could not load your shares: {(tracked.error as Error).message}</p>
        )}
        {holdings.isError && (
          <p className="tm-dim">
            Could not reach Zerodha just now ({(holdings.error as Error).message}), so the count of new shares may be off.
          </p>
        )}
        {tracked.data && rows.length === 0 && (
          <p className="tm-dim">Nothing in this list yet. Press “Import from Zerodha” to copy your shares here.</p>
        )}
        {rows.length > 0 && (
          <div className="tm-rows">
            <div className="tm-row">
              <span className="tm-dim">You put in</span>
              <span className="tm-strong">{rupees(totals.invested)}</span>
            </div>
            <div className="tm-row">
              <span className="tm-dim">Worth now</span>
              <span className="tm-strong">{rupees(totals.current)}</span>
            </div>
            <div className="tm-row">
              <span className="tm-dim">Gain or loss</span>
              <span className={`tm-strong ${toneClass(totals.pnl)}`}>
                {signedRupees(totals.pnl)}
                {totals.invested > 0 ? ` (${signed((totals.pnl / totals.invested) * 100)})` : ''}
              </span>
            </div>
          </div>
        )}
      </Card>

      {attention.length > 0 && (
        <Card
          title={`Needs your attention (${attention.length})`}
          sub="The bot cannot sell these for you, because you bought them by hand."
        >
          <div className="tm-grid">
            {attention.map((p) => (
              <div key={p.id} className="tm-callout">
                <div className="tm-flex tm-wrap" style={{ justifyContent: 'space-between', gap: '0.5rem' }}>
                  <span className="tm-strong">{p.symbol}</span>
                  <Tag tone={VERDICT[p.action_code].tone}>{p.action_code === 'exit' ? 'Sell' : 'Review'}</Tag>
                </div>
                <div className="tm-strong" style={{ marginTop: '0.3rem' }}>{VERDICT[p.action_code].head}</div>
                <div className="tm-dim" style={{ marginTop: '0.2rem', overflowWrap: 'anywhere' }}>{p.action_label}</div>
                <div className="tm-dim" style={{ marginTop: '0.4rem' }}>
                  {p.quantity} shares · paid {rupees(p.entry_price)} · now {rupees(p.current_price)} ·{' '}
                  <span className={toneClass(p.unrealized_pnl)}>{signedRupees(p.unrealized_pnl)}</span>
                  <br />
                  Stop-loss: {stopText(p)}
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {rows.length > 0 && (
        <Card
          title="Every share you hold"
          sub="Confidence is how sure the bot was when you bought, then how sure it is now."
        >
          <div className="tm-table-wrap">
            <table className="tm-table">
              <thead>
                <tr>
                  <th>Stock</th>
                  <th className="tm-right">Shares</th>
                  <th className="tm-right">You paid</th>
                  <th className="tm-right">Price now</th>
                  <th className="tm-right">Gain or loss</th>
                  <th className="tm-right">Stop-loss</th>
                  <th className="tm-right">Target</th>
                  <th className="tm-right">Confidence</th>
                  <th>The bot says</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rows.map((p) => (
                  <tr key={p.id}>
                    <td className="tm-strong">{p.symbol}</td>
                    <td className="tm-right">{p.quantity}</td>
                    <td className="tm-right">{rupees(p.entry_price)}</td>
                    <td className="tm-right">{rupees(p.current_price)}</td>
                    <td className={`tm-right ${toneClass(p.unrealized_pnl)}`}>
                      {signedRupees(p.unrealized_pnl)} ({signed(p.unrealized_pnl_pct * 100)})
                    </td>
                    <td className="tm-right">{p.stop_loss != null ? rupees(p.stop_loss) : '—'}</td>
                    <td className="tm-right">{p.take_profit != null ? rupees(p.take_profit) : '—'}</td>
                    <td className="tm-right">{confidenceText(p)}</td>
                    <td className="tm-wrap">
                      <Tag tone={VERDICT[p.action_code].tone}>{VERDICT[p.action_code].head}</Tag>
                    </td>
                    <td>
                      <button className="tm-btn tm-btn-ghost" onClick={() => setSold(p)} disabled={manualClose.isPending}>
                        I sold this
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {askImport && (
        <Confirm
          title="Import from Zerodha"
          confirmLabel="Copy my shares"
          onClose={() => setAskImport(false)}
          onConfirm={async () => {
            await importHoldings.mutateAsync()
          }}
        >
          This copies the shares you hold in Zerodha into this list so the bot can keep an eye on them. It does
          not buy or sell anything.
        </Confirm>
      )}
      {sold && (
        <SoldDialog
          position={sold}
          onClose={() => setSold(null)}
          onSubmit={(id, exitPrice) => manualClose.mutateAsync({ id, exitPrice })}
        />
      )}
    </>
  )
}

function ReportTab() {
  const queryClient = useQueryClient()
  const fileInput = useRef<HTMLInputElement>(null)
  const [period, setPeriod] = useState<PeriodKey>('30d')
  const [askSync, setAskSync] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const range = useMemo(() => rangeFor(period), [period])

  const report = useQuery({ queryKey: ['realReport', range], queryFn: () => api.realReport(range), retry: false })

  const refreshed = () => queryClient.invalidateQueries({ queryKey: ['realReport'] })
  const sync = useMutation({ mutationFn: api.syncRealTrades, onSuccess: refreshed })
  const upload = useMutation({ mutationFn: (f: File) => api.importTradebook(f), onSuccess: refreshed })

  const controls = (
    <div className="tm-flex tm-wrap" style={{ gap: '0.5rem' }}>
      <button className="tm-btn" onClick={() => setAskSync(true)}>Sync my trades from Zerodha</button>
      <button className="tm-btn" onClick={() => fileInput.current?.click()}>Import tradebook</button>
    </div>
  )

  if (report.isLoading) return <p className="tm-dim">Loading your report…</p>
  if (report.isError) return <p className="tm-neg">Could not load the report: {(report.error as Error).message}</p>
  const data = report.data!
  const s = data.summary
  const noHistory = data.records.total_fills === 0
  const salesCount = s.winning_sales + s.losing_sales
  const periodLabel = PERIODS.find((p) => p.key === period)!.label.toLowerCase().replace(/ /g, '-')

  return (
    <>
      <input
        ref={fileInput}
        type="file"
        accept=".csv,text/csv"
        hidden
        onChange={(e) => {
          const f = e.target.files?.[0]
          if (f) setFile(f)
          e.target.value = ''
        }}
      />
      <Card title="Buy and sell report" sub="Your real Zerodha account. Read-only: nothing here places or changes an order.">
        <div className="tm-flex tm-wrap" style={{ gap: '0.4rem', marginBottom: '0.6rem' }}>
          {PERIODS.map((p) => (
            <button key={p.key} className={`tm-btn ${period === p.key ? '' : 'tm-btn-ghost'}`} onClick={() => setPeriod(p.key)}>
              {p.label}
            </button>
          ))}
        </div>
        {notice && <div className="tm-callout" style={{ marginBottom: '0.6rem' }}>{notice}</div>}
        {data.holdings_note && (
          <p className="tm-warn">Shares you still hold are not shown: {data.holdings_note}</p>
        )}
        {noHistory ? (
          <>
            <div className="tm-strong">No buys or sells saved yet</div>
            <p className="tm-dim">
              Zerodha only shares the trades you made today, so this report starts empty and fills up on its own.
              The app saves your trades every weekday after the market closes.
            </p>
            <p className="tm-dim">
              To see what you bought and sold before now, download your tradebook from Zerodha (Console, then
              Reports, then Tradebook, then Equity, then Download CSV) and add it here. Buys and sells already
              saved are never counted twice.
            </p>
            {controls}
          </>
        ) : (
          <div className="tm-rows">
            <div className="tm-row">
              <span className="tm-dim">Profit from shares you sold</span>
              <span className={`tm-strong ${toneClass(s.realized_pnl)}`}>{signedRupees(s.realized_pnl)}</span>
            </div>
            <div className="tm-row">
              <span className="tm-dim">{salesCount ? 'Before charges, minus charges' : 'Sales in this period'}</span>
              <span className="tm-strong">
                {salesCount ? `${rupees(s.gross_pnl)} − ${rupees(s.charges)}` : 'None'}
              </span>
            </div>
            <div className="tm-row">
              <span className="tm-dim">Sales that made money</span>
              <span className="tm-strong">{salesCount ? `${s.winning_sales} of ${salesCount}` : '—'}</span>
            </div>
            {s.average_holding_days !== null && (
              <div className="tm-row">
                <span className="tm-dim">Held for, on average</span>
                <span className="tm-strong">{Math.round(s.average_holding_days)} days</span>
              </div>
            )}
            <div className="tm-row">
              <span className="tm-dim">Bought ({s.buy_count})</span>
              <span className="tm-strong">{rupees(s.bought_value)}</span>
            </div>
            <div className="tm-row">
              <span className="tm-dim">Sold ({s.sell_count})</span>
              <span className="tm-strong">{rupees(s.sold_value)}</span>
            </div>
            {s.open_pnl !== null && (
              <div className="tm-row">
                <span className="tm-dim">
                  Shares you still hold, right now{s.open_value != null ? ` (worth ${rupees(s.open_value)})` : ''}
                </span>
                <span className={`tm-strong ${toneClass(s.open_pnl)}`}>{signedRupees(s.open_pnl)}</span>
              </div>
            )}
            {s.best_stock && (
              <div className="tm-row">
                <span className="tm-dim">Best stock</span>
                <span className="tm-strong">{s.best_stock.symbol} {signedRupees(s.best_stock.pnl)}</span>
              </div>
            )}
            {s.worst_stock && (
              <div className="tm-row">
                <span className="tm-dim">Worst stock</span>
                <span className="tm-strong">{s.worst_stock.symbol} {signedRupees(s.worst_stock.pnl)}</span>
              </div>
            )}
          </div>
        )}
      </Card>

      {!noHistory && (
        <>
          {data.unmatched_sales.length > 0 && (
            <p className="tm-warn">
              {data.unmatched_sales.length} sale{data.unmatched_sales.length === 1 ? '' : 's'} (
              {[...new Set(data.unmatched_sales.map((u) => u.symbol))].join(', ')}) have no buy on record, so their
              profit cannot be worked out and is left out. Adding your Zerodha tradebook file fixes this.
            </p>
          )}

          <Card title="By stock">
            {data.by_stock.length === 0 ? (
              <p className="tm-dim">Nothing bought or sold in this period.</p>
            ) : (
              <div className="tm-table-wrap">
                <table className="tm-table">
                  <thead>
                    <tr>
                      <th>Stock</th>
                      <th className="tm-right">Bought</th>
                      <th className="tm-right">Sold</th>
                      <th className="tm-right">Profit from sales</th>
                      <th className="tm-right">Still holding</th>
                      <th className="tm-right">Profit on those (not booked)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.by_stock.map((r) => (
                      <tr key={r.symbol}>
                        <td className="tm-strong">{r.symbol}</td>
                        <td className="tm-right">{r.bought_qty ? `${r.bought_qty} · ${rupees(r.bought_value)}` : '—'}</td>
                        <td className="tm-right">{r.sold_qty ? `${r.sold_qty} · ${rupees(r.sold_value)}` : '—'}</td>
                        <td className={`tm-right ${r.sold_qty ? toneClass(r.realized_pnl) : ''}`}>
                          {r.sold_qty ? signedRupees(r.realized_pnl) : '—'}
                        </td>
                        <td className="tm-right">{r.open_qty ? `${r.open_qty} @ ${rupees(r.open_avg_price ?? 0)}` : '—'}</td>
                        <td className={`tm-right ${r.open_pnl !== null ? toneClass(r.open_pnl) : ''}`}>
                          {r.open_pnl !== null && r.open_qty ? signedRupees(r.open_pnl) : '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          <Card
            title="Shares you sold, and what each sale earned"
            sub="Profit is after Zerodha and exchange charges. Sales are matched to your oldest shares first, the same way Zerodha does."
          >
            {data.closed.length === 0 ? (
              <p className="tm-dim">No sales in this period.</p>
            ) : (
              <div className="tm-table-wrap">
                <table className="tm-table">
                  <thead>
                    <tr>
                      <th>Stock</th>
                      <th>Bought on</th>
                      <th>Sold on</th>
                      <th className="tm-right">Shares</th>
                      <th className="tm-right">Bought at</th>
                      <th className="tm-right">Sold at</th>
                      <th className="tm-right">Profit</th>
                      <th className="tm-right">Days held</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.closed.map((c, i) => (
                      <tr key={`${c.symbol}-${c.sell_date}-${i}`}>
                        <td className="tm-strong">{c.symbol}</td>
                        <td>{day(c.buy_date)}</td>
                        <td>{day(c.sell_date)}</td>
                        <td className="tm-right">{c.quantity}</td>
                        <td className="tm-right">{rupees(c.buy_price)}</td>
                        <td className="tm-right">{rupees(c.sell_price)}</td>
                        <td className={`tm-right ${toneClass(c.net_pnl)}`}>
                          {signedRupees(c.net_pnl)} <span className="tm-dim">({signed(c.pnl_pct)})</span>
                        </td>
                        <td className="tm-right">{c.holding_days}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          <Card title="Every buy and sell">
            {data.fills.length === 0 ? (
              <p className="tm-dim">Nothing bought or sold in this period.</p>
            ) : (
              <div className="tm-table-wrap">
                <table className="tm-table">
                  <thead>
                    <tr>
                      <th>When</th>
                      <th>Type</th>
                      <th>Stock</th>
                      <th className="tm-right">Shares</th>
                      <th className="tm-right">Price</th>
                      <th className="tm-right">Amount</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.fills.map((f) => (
                      <tr key={f.id}>
                        <td>{dayTime(f.executed_at)}</td>
                        <td>
                          <Tag tone={f.side === 'BUY' ? 'green' : 'red'}>{f.side === 'BUY' ? 'Bought' : 'Sold'}</Tag>
                        </td>
                        <td className="tm-strong">{f.symbol}</td>
                        <td className="tm-right">{f.quantity}</td>
                        <td className="tm-right">{rupees(f.price)}</td>
                        <td className="tm-right">{rupees(f.value)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          <Card title="Your saved trades">
            <p className="tm-dim">
              Saved trades go back to {data.records.first_at ? day(data.records.first_at) : '—'} (
              {data.records.total_fills} in total). New trades are saved automatically every weekday after the market
              closes. For anything older, import your Zerodha tradebook: in Zerodha Console go to Reports, then
              Tradebook, then Equity, and download the CSV.
            </p>
            <div className="tm-flex tm-wrap" style={{ gap: '0.5rem' }}>
              {controls}
              <button className="tm-btn tm-btn-ghost" onClick={() => exportReport(data, periodLabel)}>
                Download as spreadsheet
              </button>
            </div>
          </Card>
        </>
      )}

      {askSync && (
        <Confirm
          title="Sync my trades from Zerodha"
          confirmLabel="Sync now"
          onClose={() => setAskSync(false)}
          onConfirm={async () => {
            const r = await sync.mutateAsync()
            setNotice(`${r.message} ${(r as { detail?: string }).detail ?? ''}`.trim())
          }}
        >
          This only reads today’s trades from Zerodha and saves them here. It does not buy or sell anything.
        </Confirm>
      )}
      {file && (
        <Confirm
          title="Import tradebook"
          confirmLabel="Import file"
          onClose={() => setFile(null)}
          onConfirm={async () => {
            const r = await upload.mutateAsync(file)
            setNotice(`${r.message} ${(r as { detail?: string }).detail ?? ''}`.trim())
          }}
        >
          This reads the file “{file.name}” and adds its buys and sells to your report. Trades already saved are
          never counted twice. It does not buy or sell anything.
        </Confirm>
      )}
    </>
  )
}

function ZerodhaTab() {
  const holdings = useQuery({ queryKey: ['holdings'], queryFn: api.holdings, retry: false })
  return (
    <Card
      title="Straight from Zerodha"
      sub="This is exactly what Zerodha reports for your account right now, unchanged by the bot. Read-only."
    >
      {holdings.isLoading && <p className="tm-dim">Loading from Zerodha…</p>}
      {holdings.isError && (
        <p className="tm-neg">
          Could not reach Zerodha: {((holdings.error as Error).message || 'log in to Zerodha and try again').replace(/\.$/, '')}.
        </p>
      )}
      {holdings.data && holdings.data.length === 0 && (
        <p className="tm-dim">No shares in the connected Zerodha account.</p>
      )}
      {holdings.data && holdings.data.length > 0 && (
        <div className="tm-table-wrap">
          <table className="tm-table">
            <thead>
              <tr>
                <th>Stock</th>
                <th className="tm-right">Shares</th>
                <th className="tm-right">You paid (average)</th>
                <th className="tm-right">Price now</th>
                <th className="tm-right">Worth now</th>
                <th className="tm-right">Gain or loss</th>
                <th className="tm-right">Today</th>
              </tr>
            </thead>
            <tbody>
              {holdings.data.map((h) => (
                <tr key={`${h.exchange}:${h.symbol}`}>
                  <td className="tm-strong">{h.symbol}</td>
                  <td className="tm-right">{h.quantity}</td>
                  <td className="tm-right">{rupees(h.average_price)}</td>
                  <td className="tm-right">{rupees(h.last_price)}</td>
                  <td className="tm-right">{rupees(h.last_price * h.quantity)}</td>
                  <td className={`tm-right ${toneClass(h.pnl)}`}>{signedRupees(h.pnl)}</td>
                  <td className={`tm-right ${h.day_change_percentage != null ? toneClass(h.day_change_percentage) : 'tm-dim'}`}>
                    {h.day_change_percentage != null ? signed(h.day_change_percentage) : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}

export default function MyHoldings() {
  const [tab, setTab] = useState<TabId>('My holdings')
  return (
    <div className="tm-page tm-grid">
      <PageHead
        title="My Holdings"
        sub="The shares you bought yourself in Zerodha, kept apart from the bot’s practice trades."
      />
      <Tabs tabs={TABS} active={tab} onChange={setTab} />
      {tab === 'My holdings' ? <HoldingsTab /> : tab === 'Straight from Zerodha' ? <ZerodhaTab /> : <ReportTab />}
    </div>
  )
}
