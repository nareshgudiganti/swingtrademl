// The new look's History page: every buy and sell, why it happened and how it ended, plus "Step 8 · What the brain
// learned". Display only: reads stored trades, open positions, the owner's cancelled approvals and the learning
// report; changes nothing.
//
// These are version 1's records (the bot's paper book and, for the real-account owner only, their own Zerodha
// trades): not the brain's sealed trial. A brain trade from the trial would show "Sealed", never a result.
// Paper and Real are labelled on every row and never added together. The classic Records page (totals by month,
// strategy results, version 1's picks) stays one tap away.

import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import { api, BASE_URL, getPreviewPlan, getToken } from '../../api/client'
import type { Trade } from '../../api/types'
import { usePlan } from '../../lib/plan'
import { useLearning, useMarketSession, useProposals } from '../live'
import { QueryNotice } from '../PageState'
import { istToday } from '../pricesAge'
import { SortTh, useSort } from '../sort'
import StockLink from '../StockLink'
import { inr } from '../ui'
import {
  cancelledRow,
  inPeriod,
  inTab,
  KIND_LABEL,
  learnedLine,
  openRow,
  pctText,
  RESULTS_OPEN_TEXT,
  shortDate,
  sortRows,
  tradeRow,
  type HistoryPeriod,
  type HistoryRow,
  type HistoryTab,
} from '../wave3Rules'
import Records from './Records'
import '../newlook-w3.css'

/** GET /portfolio/trades?book=real — the server refuses it to anyone not in REAL_ACCOUNT_USERS. */
async function realTrades(): Promise<Trade[]> {
  const token = getToken()
  const preview = getPreviewPlan()
  const r = await fetch(`${BASE_URL}/portfolio/trades?limit=1000&book=real`, {
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(preview ? { 'X-Preview-Plan': preview } : {}),
    },
  })
  if (!r.ok) throw new Error(r.statusText || 'Could not load your own trades')
  return r.json() as Promise<Trade[]>
}

const PERIODS: { id: HistoryPeriod; label: string }[] = [
  { id: 'all', label: 'Everything' },
  { id: 'month', label: 'This month' },
  { id: '3m', label: 'Last 3 months' },
]

export default function HistoryNew({ owner = false }: { owner?: boolean }) {
  const { canSeeRealAccount } = usePlan()
  const real = owner && canSeeRealAccount
  const [tab, setTab] = useState<HistoryTab>('all')
  const [period, setPeriod] = useState<HistoryPeriod>('all')
  const market = useMarketSession()
  const today = market.data?.today ?? istToday(new Date())

  const status = useQuery({ queryKey: ['status'], queryFn: api.status, enabled: owner, retry: false })
  const trades = useQuery({ queryKey: ['trades', 1000], queryFn: () => api.trades(1000) })
  const positions = useQuery({ queryKey: ['positions'], queryFn: api.positions })
  const ownTrades = useQuery({ queryKey: ['trades', 'real', 1000], queryFn: realTrades, enabled: real, retry: false })
  const ownPositions = useQuery({ queryKey: ['realPositions'], queryFn: api.realPositions, enabled: real, retry: false })
  // Ideas the owner was asked to approve that were not bought (rejected or ran out of time). Owner-only on the server.
  const approvals = useQuery({ queryKey: ['brainApprovals'], queryFn: api.brainApprovals, enabled: owner, retry: false })

  // The bot's open positions are paper unless the server says otherwise (a non-owner cannot read /status; the bot
  // book is paper for everyone while TRADING_MODE is paper, which the sidebar states).
  const botPaper = status.data ? status.data.trading_mode === 'paper' : true

  const rows = useMemo(() => {
    const out: HistoryRow[] = []
    for (const t of trades.data ?? []) out.push(tradeRow(t, false))
    for (const p of positions.data ?? []) out.push(openRow(p, false, botPaper))
    for (const t of ownTrades.data ?? []) out.push(tradeRow(t, true))
    for (const p of ownPositions.data ?? []) out.push(openRow(p, true, false))
    for (const a of approvals.data ?? []) if (a.status === 'expired' || a.status === 'rejected') out.push(cancelledRow(a))
    return sortRows(out)
  }, [trades.data, positions.data, ownTrades.data, ownPositions.data, approvals.data, botPaper])

  const tabs: { id: HistoryTab; label: string }[] = [
    { id: 'all', label: 'All' },
    { id: 'bot', label: 'Bot buys' },
    ...(real ? [{ id: 'own' as const, label: 'My own trades' }] : []),
    ...(owner ? [{ id: 'cancelled' as const, label: 'Cancelled' }] : []),
  ]
  const { sorted: shown, sorter } = useSort(rows.filter((r) => inTab(r, tab) && inPeriod(r, period, today)), {
    date: (r: HistoryRow) => r.date,
    stock: (r: HistoryRow) => r.symbol,
    type: (r: HistoryRow) => KIND_LABEL[r.kind],
    price: (r: HistoryRow) => (r.kind === 'cancelled' ? null : r.price),
    ended: (r: HistoryRow) => r.ended,
    // A sealed result must not leak through the order of the rows, so it sorts as "no result".
    result: (r: HistoryRow) => (r.sealed ? null : r.resultPct),
  }, { key: null }, { stock: 'asc', type: 'asc', ended: 'asc' })
  const loading = trades.isLoading || positions.isLoading

  return (
    <div className="tm-page tmw3" data-page="history-new">
      <div className="tmw3-head">
        <h2 className="tmw3-h1">Trading History</h2>
        <p className="tm-dim">Every buy and sell, why it happened, and how it ended.</p>
      </div>

      <div className="tmw3-filters">
        <div className="tmw3-tabs" role="tablist" aria-label="Which trades">
          {tabs.map((t) => (
            <button
              key={t.id}
              type="button"
              role="tab"
              aria-selected={tab === t.id}
              className={`tmw3-tab ${tab === t.id ? 'on' : ''}`}
              onClick={() => setTab(t.id)}
              data-testid={`history-tab-${t.id}`}
            >
              {t.label}
            </button>
          ))}
        </div>
        <label className="tmn-small tm-dim tmw3-period">
          Period
          <select className="tm-select" value={period} onChange={(e) => setPeriod(e.target.value as HistoryPeriod)}>
            {PERIODS.map((p) => (
              <option key={p.id} value={p.id}>
                {p.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      <Learned />

      <section className="tmn-card tmw3-tablecard" aria-label="Trades" data-testid="history-table">
        <QueryNotice q={trades} what="the trade history" />
        {loading ? (
          <p className="tm-dim">Loading…</p>
        ) : shown.length === 0 ? (
          <p className="tm-dim">{rows.length === 0 ? 'No trades recorded yet.' : 'Nothing here for this choice.'}</p>
        ) : (
          <div className="tmw3-tablebox" tabIndex={0} role="region" aria-label="Trades, scroll sideways to see more">
            <table className="tmw3-table">
              <thead>
                <tr>
                  <SortTh sorter={sorter} k="date">Date</SortTh>
                  <SortTh sorter={sorter} k="stock">Stock</SortTh>
                  <SortTh sorter={sorter} k="type">Type</SortTh>
                  <SortTh sorter={sorter} k="price" right>Bought at</SortTh>
                  <th>Why it was bought</th>
                  <SortTh sorter={sorter} k="ended">How it ended</SortTh>
                  <SortTh sorter={sorter} k="result" right>Result</SortTh>
                </tr>
              </thead>
              <tbody>
                {shown.map((r) => (
                  <tr key={r.key}>
                    <td className="tm-dim">{shortDate(r.date)}</td>
                    <td>
                      <StockLink symbol={r.symbol} />
                    </td>
                    <td>
                      <span className={`tmw3-kind tmw3-kind-${r.kind}`}>{KIND_LABEL[r.kind]}</span>
                    </td>
                    <td className="tm-right">{r.price != null && r.kind !== 'cancelled' ? `₹${inr(r.price)}` : '—'}</td>
                    <td className="tmw3-why">{r.why}</td>
                    <td>
                      <span className="tmw3-end">
                        <span className={`tmw3-dot tmw3-dot-${r.endedTone}`} aria-hidden="true" />
                        {r.ended}
                      </span>
                    </td>
                    <td className="tm-right">
                      {r.sealed ? (
                        <span className="tmw3-pill tmw3-pill-violet" title={`Sealed until ${RESULTS_OPEN_TEXT}: the brain's trial shows counts only.`}>
                          Sealed
                        </span>
                      ) : r.resultPct == null ? (
                        <span className="tm-dim">—</span>
                      ) : (
                        <b className={r.resultPct > 0 ? 'tm-pos' : r.resultPct < 0 ? 'tm-neg' : 'tm-dim'}>{pctText(r.resultPct)}</b>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <p className="tmn-small tm-dim">
        These are version 1&apos;s records, not the brain&apos;s sealed trial. Paper buys use practice money; rows
        marked Real are real money and are never added to paper. Results are after charges and shown only for
        finished trades.
        {!owner && ' Trades only the owner can see are not listed.'}
      </p>

      <details className="tmn-more">
        <summary>More detail: totals by month, each strategy&apos;s results and version 1&apos;s picks</summary>
        <Records />
      </details>
    </div>
  )
}

/** Step 8: counts and the sealed state only (never a hit rate during the trial). */
function Learned() {
  const learning = useLearning()
  const proposals = useProposals()
  if (!learning.data && !proposals.data) return null
  return (
    <section className="tmn-card tmw3-learned" aria-label="What the brain learned" data-testid="learned-card">
      <span className="tmw3-icon tmw3-icon-violet" aria-hidden="true">
        <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <path d="M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2z" />
          <path d="M19 19v2H6" />
        </svg>
      </span>
      <div>
        <b>Step 8 · What the brain learned</b>
        <p className="tm-dim">{learnedLine(learning.data, proposals.data)}</p>
        <Link className="tm-link tmn-small" to="/trademind/learn">
          See the evidence →
        </Link>
      </div>
    </section>
  )
}
