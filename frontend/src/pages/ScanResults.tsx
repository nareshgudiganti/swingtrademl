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

export default function ScanResults() {
  const [selected, setSelected] = useState<TrackRecordSignal | null>(null)
  const scanResults = useQuery({ queryKey: ['scanResults'], queryFn: api.scanResults })

  const rows = useMemo(() => scanResults.data ?? [], [scanResults.data])

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
                <th>Stock</th>
                <th>Cap tier</th>
                <th>Called on</th>
                <th>Entry</th>
                <th>Stop</th>
                <th>Target</th>
                <th>Current</th>
                <th>Status</th>
                <th>Result</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const status = statusFor(row)
                const resultPct = resultPctFor(row)
                return (
                  <tr key={row.signal_id} onClick={() => setSelected(row)} style={{ cursor: 'pointer' }}>
                    <td>{row.symbol}</td>
                    <td>{row.cap_tier}</td>
                    <td>
                      {formatDate(row.generated_at)} <span className="muted">({row.age_days}d ago)</span>
                    </td>
                    <td>{formatCurrency(row.price)}</td>
                    <td>{formatCurrency(row.stop_loss)}</td>
                    <td>{formatCurrency(row.take_profit)}</td>
                    <td>{row.current_price != null ? formatCurrency(row.current_price) : '—'}</td>
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
