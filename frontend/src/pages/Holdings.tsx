import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../api/client'
import type { DetailedPosition } from '../api/types'
import Stat from '../components/Stat'
import { ErrorBox, Loading } from '../components/Loading'
import StockDetailModal, { type StockDetail } from '../components/StockDetailModal'
import { PositionsTable } from './Positions'
import RealReport from './RealReport'
import { formatCurrency, formatSignedPercent } from '../lib/format'

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
  const [view, setView] = useState<'shares' | 'report'>('shares')

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

  const attention = useMemo(
    () => rows.filter((p) => p.action_code === 'exit' || p.action_code === 'alert'),
    [rows],
  )

  // How many Zerodha holdings aren't tracked yet. Surfaced as a count on the
  // Import button rather than a second table: it's the only thing that list
  // was really telling you, and a number on the button you'd press anyway
  // says it without costing a section.
  const untrackedCount = useMemo(() => {
    const trackedSymbols = new Set(rows.map((p) => p.symbol))
    return (holdings.data ?? []).filter((h) => h.quantity > 0 && !trackedSymbols.has(h.symbol))
      .length
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
        <div>
          <h1 style={{ marginBottom: '0.15rem' }}>My Holdings</h1>
          <div className="muted" style={{ fontSize: '0.82rem' }}>
            Your real Zerodha shares, read by the model each day. Nothing here places or cancels
            an order.
          </div>
        </div>
        {view === 'shares' && (
          <button onClick={() => importHoldings.mutate()} disabled={importHoldings.isPending}>
            {importHoldings.isPending
              ? 'Importing…'
              : untrackedCount > 0
                ? `Import ${untrackedCount} new from Zerodha`
                : 'Import from Zerodha'}
          </button>
        )}
      </div>

      <div className="row" style={{ gap: '0.4rem', marginBottom: '0.75rem' }}>
        <button className={view === 'shares' ? 'primary' : ''} onClick={() => setView('shares')}>
          My shares
        </button>
        <button className={view === 'report' ? 'primary' : ''} onClick={() => setView('report')}>
          Buy &amp; sell report
        </button>
      </div>

      {view === 'report' ? (
        <RealReport />
      ) : (
        <>

      {importHoldings.isError && <ErrorBox error={importHoldings.error} />}

      {importHoldings.isSuccess && importHoldings.data && (
        <div className="banner banner-ok">
          Imported {importHoldings.data.filter((r) => r.status === 'imported').length} · already
          tracked {importHoldings.data.filter((r) => r.status === 'already_tracked').length} ·
          skipped {importHoldings.data.filter((r) => r.status === 'skipped').length}
        </div>
      )}

      {rows.length > 0 && (
        <div className="grid">
          <Stat label="Invested" value={formatCurrency(totals.invested)} sub={`${rows.length} stocks`} />
          <Stat label="Current value" value={formatCurrency(totals.current)} />
          <Stat
            label="Overall P&L"
            value={formatCurrency(totals.pnl)}
            tone={totals.pnl > 0 ? 'pos' : totals.pnl < 0 ? 'neg' : 'flat'}
            sub={formatSignedPercent(totals.pct)}
          />
          <Stat
            label="Needs attention"
            value={String(totals.needsAction)}
            tone={totals.needsAction > 0 ? 'neg' : 'flat'}
            sub={totals.needsAction > 0 ? 'exit or alert signalled' : 'nothing urgent'}
          />
        </div>
      )}

      {/* The rows the model wants you to look at, lifted out of the table so
          they are not something you have to scan a column to find. */}
      {attention.length > 0 && (
        <div className="banner banner-warn">
          <strong>{attention.map((p) => p.symbol).join(', ')}</strong>
          {attention.length === 1 ? ' has ' : ' have '}
          an exit or alert signal — open the stock for the full read.
        </div>
      )}

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

        </>
      )}

      {detail && <StockDetailModal detail={detail} onClose={() => setDetail(null)} />}
    </div>
  )
}
