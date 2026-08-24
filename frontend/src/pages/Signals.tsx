import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { api } from '../api/client'
import type { LatestSignal } from '../api/types'
import { Empty, ErrorBox, Loading } from '../components/Loading'
import { formatCurrency, formatDateTime, formatPercent } from '../lib/format'

type SortKey = 'generated_at' | 'symbol' | 'signal' | 'price' | 'quantity' | 'confidence' | 'stop_loss' | 'take_profit'
type SortDir = 'asc' | 'desc'

const COLUMNS: { key: SortKey; label: string; num?: boolean; defaultDir: SortDir }[] = [
  { key: 'generated_at', label: 'Time', defaultDir: 'desc' },
  { key: 'symbol', label: 'Symbol', defaultDir: 'asc' },
  { key: 'signal', label: 'Signal', defaultDir: 'asc' },
  { key: 'price', label: 'Price', num: true, defaultDir: 'desc' },
  { key: 'quantity', label: 'Qty', num: true, defaultDir: 'desc' },
  { key: 'confidence', label: 'Confidence', num: true, defaultDir: 'desc' },
  { key: 'stop_loss', label: 'Stop', num: true, defaultDir: 'desc' },
  { key: 'take_profit', label: 'Target', num: true, defaultDir: 'desc' },
]

// nulls always sort last, regardless of direction — a missing stop/target/qty
// isn't "low", it's not comparable, and burying it at the bottom either way
// keeps the click behavior predictable.
function compare(a: LatestSignal, b: LatestSignal, key: SortKey): number {
  const av = a[key]
  const bv = b[key]
  if (av == null && bv == null) return 0
  if (av == null) return 1
  if (bv == null) return -1
  if (typeof av === 'string' && typeof bv === 'string') return av.localeCompare(bv)
  if (typeof av === 'number' && typeof bv === 'number') return av - bv
  return 0
}

export default function Signals() {
  const signals = useQuery({ queryKey: ['signals', 100], queryFn: () => api.latestSignals(100) })
  const [sortKey, setSortKey] = useState<SortKey>('generated_at')
  const [sortDir, setSortDir] = useState<SortDir>('desc')

  const rows = useMemo(() => {
    const data = [...(signals.data ?? [])]
    data.sort((a, b) => compare(a, b, sortKey) * (sortDir === 'asc' ? 1 : -1))
    return data
  }, [signals.data, sortKey, sortDir])

  if (signals.isLoading) return <Loading />
  if (signals.error) return <ErrorBox error={signals.error} />

  function toggleSort(col: (typeof COLUMNS)[number]) {
    if (sortKey === col.key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(col.key)
      setSortDir(col.defaultDir)
    }
  }

  return (
    <>
      <div className="page-head">
        <h1>Signals</h1>
        <span className="muted">{rows.length} most recent actionable signals — click a column to sort</span>
      </div>

      <div className="banner banner-info">
        Rejected signals are shown too. A signal the risk engine blocked is as much a part of the
        strategy&apos;s record as one it took — the rejection reason explains why.
      </div>

      <div className="table-wrap">
        {!rows.length ? (
          <Empty label="No signals yet. Activate a strategy, then run a scan." />
        ) : (
          <table>
            <thead>
              <tr>
                {COLUMNS.map((col, i) => (
                  <th
                    key={col.key}
                    className={`sortable${col.num ? ' num' : ''}${i === 0 ? ' sticky-col' : ''}`}
                    onClick={() => toggleSort(col)}
                    aria-sort={sortKey === col.key ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'}
                  >
                    {col.label}
                    <span className="sort-arrow">
                      {sortKey === col.key ? (sortDir === 'asc' ? ' ▲' : ' ▼') : ''}
                    </span>
                  </th>
                ))}
                <th>Status</th>
                <th>Reason</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((s) => (
                <tr key={s.id}>
                  <td className="muted sticky-col">{formatDateTime(s.generated_at)}</td>
                  <td>
                    <strong>{s.symbol}</strong>
                  </td>
                  <td>
                    <span className={`badge badge-${s.signal.toLowerCase()}`}>{s.signal}</span>
                  </td>
                  <td className="num">{formatCurrency(s.price)}</td>
                  <td className="num">{s.quantity ?? '—'}</td>
                  <td className="num">
                    {s.confidence !== null ? formatPercent(s.confidence, 1) : '—'}
                  </td>
                  <td className="num muted">{s.stop_loss ? formatCurrency(s.stop_loss) : '—'}</td>
                  <td className="num muted">
                    {s.take_profit ? formatCurrency(s.take_profit) : '—'}
                  </td>
                  <td>
                    {s.executed ? (
                      <span className="badge badge-on">executed</span>
                    ) : s.advisory_only ? (
                      <span className="badge badge-recommend" title="Recommended — not auto-executed. Record the fill via POST /portfolio/positions/manual once taken.">
                        recommended
                      </span>
                    ) : (
                      <span className="badge badge-off">not taken</span>
                    )}
                  </td>
                  <td className="reason muted" title={s.rejection_reason ?? s.reason ?? ''}>
                    {s.rejection_reason ?? s.reason ?? '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  )
}
