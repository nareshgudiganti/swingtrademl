import { useQuery } from '@tanstack/react-query'

import { api } from '../api/client'
import { Empty, ErrorBox, Loading } from '../components/Loading'
import { formatCurrency, formatDateTime, formatPercent } from '../lib/format'

export default function Signals() {
  const signals = useQuery({ queryKey: ['signals', 100], queryFn: () => api.latestSignals(100) })

  if (signals.isLoading) return <Loading />
  if (signals.error) return <ErrorBox error={signals.error} />

  const rows = signals.data ?? []

  return (
    <>
      <div className="page-head">
        <h1>Signals</h1>
        <span className="muted">{rows.length} most recent actionable signals</span>
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
                <th>Time</th>
                <th>Symbol</th>
                <th>Signal</th>
                <th className="num">Price</th>
                <th className="num">Qty</th>
                <th className="num">Confidence</th>
                <th className="num">Stop</th>
                <th className="num">Target</th>
                <th>Status</th>
                <th>Reason</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((s) => (
                <tr key={s.id}>
                  <td className="muted">{formatDateTime(s.generated_at)}</td>
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
                    <span className={`badge ${s.executed ? 'badge-on' : 'badge-off'}`}>
                      {s.executed ? 'executed' : 'not taken'}
                    </span>
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
