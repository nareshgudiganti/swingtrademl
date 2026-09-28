import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { api } from '../api/client'
import { Empty, ErrorBox, Loading } from '../components/Loading'
import Modal from '../components/Modal'
import type { TrackRecordSignal } from '../api/types'
import { formatCurrency, formatDate } from '../lib/format'

const OUTCOME_LABEL: Record<string, { label: string; icon: string }> = {
  TARGET_HIT: { label: 'Hit Target', icon: '🟢' },
  STOP_LOSS_HIT: { label: 'Hit Stop', icon: '🔴' },
  EXPIRED_NO_HIT: { label: 'Expired, no hit', icon: '⚫' },
}

function statusFor(row: TrackRecordSignal): { label: string; icon: string } {
  if (row.outcome) return OUTCOME_LABEL[row.outcome] ?? { label: row.outcome, icon: '•' }
  return { label: 'Open', icon: '⚪' }
}

function resultPctFor(row: TrackRecordSignal): number | null {
  return row.was_executed && row.trade_return_pct != null ? row.trade_return_pct : row.outcome_pct
}

/** "Long-term" vs "Swing" is derived client-side from the strategy name
 * rather than a new backend field — see
 * docs/superpowers/plans/2026-09-12-long-term-stock-picks.md Task 5. */
function horizonTagFor(row: TrackRecordSignal): 'Swing' | 'Long-term' {
  return row.strategy_name.toLowerCase().includes('long_term') ? 'Long-term' : 'Swing'
}

/** Cap tier and status sort by a meaningful order — biggest company first,
 * still-open signals first — rather than alphabetically, which would read as
 * arbitrary. */
const CAP_RANK: Record<string, number> = { large: 3, midcap: 2, smallcap: 1 }
const STATUS_RANK: Record<string, number> = { TARGET_HIT: 3, STOP_LOSS_HIT: 2, EXPIRED_NO_HIT: 1 }

type SortKey =
  | 'symbol'
  | 'cap_tier'
  | 'horizon'
  | 'generated_at'
  | 'price'
  | 'stop_loss'
  | 'take_profit'
  | 'current_price'
  | 'confidence'
  | 'status'
  | 'result'
type SortDir = 'asc' | 'desc'

function sortValue(row: TrackRecordSignal, key: SortKey): string | number | null {
  switch (key) {
    case 'cap_tier':
      return CAP_RANK[row.cap_tier] ?? 0
    case 'horizon':
      return horizonTagFor(row)
    case 'generated_at':
      return Date.parse(row.generated_at)
    case 'status':
      // A signal with no outcome yet is still open; rank those above closed ones.
      return row.outcome ? (STATUS_RANK[row.outcome] ?? 0) : 4
    case 'result':
      return resultPctFor(row)
    default:
      return row[key]
  }
}

const COLUMNS: { key: SortKey; label: string; title?: string }[] = [
  { key: 'symbol', label: 'Stock' },
  { key: 'cap_tier', label: 'Cap tier' },
  { key: 'horizon', label: 'Horizon' },
  { key: 'generated_at', label: 'Called on' },
  { key: 'price', label: 'Entry' },
  { key: 'stop_loss', label: 'Stop' },
  { key: 'take_profit', label: 'Target' },
  { key: 'current_price', label: 'Current' },
  {
    key: 'confidence',
    label: 'Confidence',
    title:
      'How sure the model was when it made this call, 0-100%. Higher is not a guarantee — it ranks this call against the others.',
  },
  { key: 'status', label: 'Status' },
  { key: 'result', label: 'Result' },
]

export default function ScanResults() {
  const [selected, setSelected] = useState<TrackRecordSignal | null>(null)
  const [sortKey, setSortKey] = useState<SortKey | null>(null)
  const [sortDir, setSortDir] = useState<SortDir>('desc')
  const scanResults = useQuery({ queryKey: ['scanResults'], queryFn: api.scanResults })

  const rows = useMemo(() => scanResults.data ?? [], [scanResults.data])

  const sorted = useMemo(() => {
    if (!sortKey) return rows
    const data = [...rows]
    data.sort((a, b) => {
      const av = sortValue(a, sortKey)
      const bv = sortValue(b, sortKey)
      if (av == null && bv == null) return 0
      if (av == null) return 1
      if (bv == null) return -1
      const flip = sortDir === 'asc' ? 1 : -1
      if (typeof av === 'string' || typeof bv === 'string') {
        return String(av).localeCompare(String(bv)) * flip
      }
      return (av - bv) * flip
    })
    return data
  }, [rows, sortKey, sortDir])

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortDir('desc')
    }
  }

  return (
    <>
      <div className="page-head">
        <h1>Scan Results</h1>
      </div>

      {scanResults.isLoading && <Loading />}
      {scanResults.isError && <ErrorBox error={scanResults.error as Error} />}
      {!scanResults.isLoading && rows.length === 0 && (
        <Empty label="No signals with a stop and target have been generated yet." />
      )}

      {rows.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                {COLUMNS.map((col) => (
                  <th
                    key={col.key}
                    className="sortable"
                    title={col.title ?? `Click to sort by ${col.label.toLowerCase()}.`}
                    onClick={() => toggleSort(col.key)}
                    aria-sort={
                      sortKey === col.key ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'
                    }
                  >
                    {col.label}
                    <span className="sort-arrow">
                      {sortKey === col.key ? (sortDir === 'asc' ? ' ▲' : ' ▼') : ''}
                    </span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sorted.map((row) => {
                const status = statusFor(row)
                const resultPct = resultPctFor(row)
                const horizonTag = horizonTagFor(row)
                return (
                  <tr key={row.signal_id} onClick={() => setSelected(row)} style={{ cursor: 'pointer' }}>
                    <td>{row.symbol}</td>
                    <td>{row.cap_tier}</td>
                    <td>
                      <span className={`badge ${horizonTag === 'Long-term' ? 'badge-paper' : 'badge-hold'}`}>
                        {horizonTag}
                      </span>
                    </td>
                    <td>
                      {formatDate(row.generated_at)} <span className="muted">({row.age_days}d ago)</span>
                    </td>
                    <td>{formatCurrency(row.price)}</td>
                    <td>{formatCurrency(row.stop_loss)}</td>
                    <td>{formatCurrency(row.take_profit)}</td>
                    <td>{row.current_price != null ? formatCurrency(row.current_price) : '—'}</td>
                    <td>{row.confidence != null ? `${(row.confidence * 100).toFixed(0)}%` : '—'}</td>
                    <td>
                      {status.icon} {status.label}
                    </td>
                    <td className={resultPct != null ? (resultPct >= 0 ? 'pos' : 'neg') : undefined}>
                      {resultPct != null ? `${(resultPct * 100).toFixed(1)}%` : '—'}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {selected && (
        <Modal onClose={() => setSelected(null)}>
          <h2>{selected.symbol} — signal detail</h2>
          <p>
            <strong>Strategy:</strong> {selected.strategy_name} ({selected.mode})
          </p>
          <p>
            <strong>Confidence:</strong>{' '}
            {selected.confidence != null ? `${(selected.confidence * 100).toFixed(0)}%` : '—'}
          </p>
          <p>
            <strong>Reason:</strong> {selected.reason ?? '—'}
          </p>
          {selected.was_executed && (
            <p>
              <strong>Actual trade result:</strong>{' '}
              {selected.trade_net_pnl != null ? formatCurrency(selected.trade_net_pnl) : 'pending'}
              {selected.trade_return_pct != null ? ` (${(selected.trade_return_pct * 100).toFixed(1)}%)` : ''}
            </p>
          )}
        </Modal>
      )}
    </>
  )
}
