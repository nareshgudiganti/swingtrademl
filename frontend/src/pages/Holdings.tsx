import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../api/client'
import type { DetailedPosition } from '../api/types'
import Stat from '../components/Stat'
import { ErrorBox, Loading } from '../components/Loading'
import StockDetailModal, { type StockDetail } from '../components/StockDetailModal'
import { PositionsTable } from './Positions'
import { formatCurrency, formatPercent, pnlClass } from '../lib/format'

/**
 * My Holdings — the real money book.
 *
 * Deliberately separate from Portfolio, which is the bot's paper testing:
 * these are shares bought by hand in Zerodha, and nothing on this page ever
 * places or cancels an order. They are tracked under the advisory
 * `real_trading` strategy so they get the same daily model read — current
 * confidence, stop, target, exit verdict — that paper positions get, while
 * every actual buy and sell stays the operator's own decision.
 *
 * The stop and target on an imported holding are anchored to the price on
 * the day it was imported, not to the original purchase price: a stock
 * bought at 100 and now at 150 needs a stop that protects 150.
 */
export default function Holdings() {
  const queryClient = useQueryClient()
  const [detail, setDetail] = useState<StockDetail | null>(null)

  // Raw Zerodha holdings — the broker's own view, independent of whether
  // this app has started tracking them. Failure here is almost always "not
  // logged into Kite"; shown inline so the tracked book below still renders.
  const holdings = useQuery({ queryKey: ['holdings'], queryFn: api.holdings, retry: false })

  // Tracked positions. Not gated on the strategy existing — importing
  // creates it on demand, so gating would leave a new install permanently
  // empty with no way out.
  const tracked = useQuery({ queryKey: ['realPositions'], queryFn: api.realPositions })

  const importHoldings = useMutation({
    mutationFn: () => api.importRealHoldings(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['realPositions'] })
      queryClient.invalidateQueries({ queryKey: ['strategies'] })
    },
  })

  const manualClose = useMutation({
    mutationFn: ({ id, exitPrice }: { id: number; exitPrice: number }) =>
      api.manualClosePosition(id, exitPrice),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['realPositions'] })
      queryClient.invalidateQueries({ queryKey: ['trades'] })
    },
  })

  const rows = tracked.data ?? []

  const totals = useMemo(() => {
    const invested = rows.reduce((sum, p) => sum + p.invested, 0)
    const current = rows.reduce((sum, p) => sum + p.current_value, 0)
    const pnl = current - invested
    const needsAction = rows.filter(
      (p) => p.action_code === 'exit' || p.action_code === 'alert',
    ).length
    return { invested, current, pnl, pct: invested > 0 ? pnl / invested : 0, needsAction }
  }, [rows])

  // Holdings Zerodha reports that this app isn't tracking yet — the reason
  // to press Import, made visible instead of left for the user to work out
  // by comparing two tables.
  const untracked = useMemo(() => {
    const trackedSymbols = new Set(rows.map((p) => p.symbol))
    return (holdings.data ?? []).filter((h) => h.quantity > 0 && !trackedSymbols.has(h.symbol))
  }, [holdings.data, rows])

  /** Record a sale you already made in Zerodha. Never places an order — it
   * asks for the price you actually got, because the app has no way to know
   * what a manual fill went through at. */
  const onRecordSale = (p: DetailedPosition) => {
    const entered = window.prompt(
      `Record the sale of ${p.symbol}.\n\nWhat price did you actually get per share?`,
      String(p.current_price),
    )
    if (entered == null) return
    const exitPrice = Number(entered)
    if (!Number.isFinite(exitPrice) || exitPrice <= 0) {
      window.alert('That does not look like a valid price.')
      return
    }
    manualClose.mutate({ id: p.id, exitPrice })
  }

  return (
    <div>
      <div className="page-head">
        <h1>My Holdings</h1>
        <button onClick={() => importHoldings.mutate()} disabled={importHoldings.isPending}>
          {importHoldings.isPending ? 'Importing…' : 'Import from Zerodha'}
        </button>
      </div>

      <p className="muted">
        Real shares you bought yourself, tracked with the model's daily read. Nothing here places
        or cancels an order — every buy and sell stays yours. The Portfolio tab is the bot's paper
        testing, kept separate on purpose.
      </p>

      {importHoldings.isError && <ErrorBox error={importHoldings.error} />}

      {importHoldings.isSuccess && importHoldings.data && (
        <div className="banner banner-ok">
          Imported {importHoldings.data.filter((r) => r.status === 'imported').length} ·
          already tracked {importHoldings.data.filter((r) => r.status === 'already_tracked').length} ·
          skipped {importHoldings.data.filter((r) => r.status === 'skipped').length}
        </div>
      )}

      {rows.length > 0 && (
        <div className="grid">
          <Stat label="Invested" value={formatCurrency(totals.invested)} />
          <Stat label="Current value" value={formatCurrency(totals.current)} />
          <Stat
            label="Overall P&L"
            value={formatCurrency(totals.pnl)}
            tone={totals.pnl > 0 ? 'pos' : totals.pnl < 0 ? 'neg' : 'flat'}
            sub={formatPercent(totals.pct)}
          />
          <Stat
            label="Needs attention"
            value={String(totals.needsAction)}
            sub={totals.needsAction > 0 ? 'exit or alert' : 'nothing urgent'}
          />
        </div>
      )}

      <h2>Tracked</h2>
      {tracked.isLoading ? (
        <Loading />
      ) : tracked.isError ? (
        <ErrorBox error={tracked.error} />
      ) : (
        <PositionsTable
          rows={rows}
          onSelectDetail={setDetail}
          onSell={onRecordSale}
          sellBusy={manualClose.isPending}
          sellLabel="Record sale"
          emptyLabel="Nothing tracked yet — press Import from Zerodha above."
        />
      )}

      {/* Only rendered when there is actually something to act on. When every
          holding is tracked this section is pure noise, and an "everything is
          fine" panel earns no permanent space on the page. It reappears by
          itself the next time you buy something in Zerodha. */}
      {untracked.length > 0 && (
        <>
          <h2>In Zerodha, not tracked yet</h2>
          <p className="muted">
            Bought outside this app. Press Import above to start tracking them.
          </p>
          <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Stock</th>
                <th className="num">Qty</th>
                <th className="num">Avg cost</th>
                <th className="num">LTP</th>
                <th className="num">P&L</th>
              </tr>
            </thead>
            <tbody>
              {untracked.map((h) => (
                <tr key={`${h.exchange}:${h.symbol}`}>
                  <td className="sticky-col">{h.symbol}</td>
                  <td className="num">{h.quantity}</td>
                  <td className="num">{formatCurrency(h.average_price)}</td>
                  <td className="num">{formatCurrency(h.last_price)}</td>
                  <td className={`num ${pnlClass(h.pnl)}`}>{formatCurrency(h.pnl)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        </>
      )}

      {detail && <StockDetailModal detail={detail} onClose={() => setDetail(null)} />}
    </div>
  )
}
