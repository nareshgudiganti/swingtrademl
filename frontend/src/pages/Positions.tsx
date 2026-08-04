import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../api/client'
import { Empty, ErrorBox, Loading } from '../components/Loading'
import { formatCurrency, formatDate, formatSignedPercent, pnlClass } from '../lib/format'

export default function Positions() {
  const queryClient = useQueryClient()
  const positions = useQuery({ queryKey: ['positions'], queryFn: api.positions })

  const close = useMutation({
    mutationFn: (id: number) => api.closePosition(id),
    onSuccess: () => {
      // A close writes a Trade and moves cash, so the summary and trade list
      // are stale too — not just the position list.
      queryClient.invalidateQueries({ queryKey: ['positions'] })
      queryClient.invalidateQueries({ queryKey: ['summary'] })
      queryClient.invalidateQueries({ queryKey: ['trades'] })
    },
  })

  if (positions.isLoading) return <Loading />
  if (positions.error) return <ErrorBox error={positions.error} />

  const rows = positions.data ?? []
  const totalPnl = rows.reduce((sum, p) => sum + p.unrealized_pnl, 0)

  return (
    <>
      <div className="page-head">
        <h1>Open positions</h1>
        <div className="row">
          <span className="muted">Unrealised</span>
          <strong className={pnlClass(totalPnl)}>{formatCurrency(totalPnl)}</strong>
        </div>
      </div>

      {close.error && <ErrorBox error={close.error} />}

      <div className="table-wrap">
        {!rows.length ? (
          <Empty label="No open positions." />
        ) : (
          <table>
            <thead>
              <tr>
                <th>Symbol</th>
                <th className="num">Qty</th>
                <th className="num">Entry</th>
                <th className="num">Current</th>
                <th className="num">Invested</th>
                <th className="num">P&L</th>
                <th className="num">Return</th>
                <th className="num">Stop</th>
                <th className="num">Target</th>
                <th className="num">Days</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => (
                <tr key={p.id}>
                  <td>
                    <strong>{p.symbol}</strong>
                    <div className="muted" style={{ fontSize: '0.75rem' }}>
                      {formatDate(p.entry_at)}
                    </div>
                  </td>
                  <td className="num">{p.quantity}</td>
                  <td className="num">{formatCurrency(p.entry_price)}</td>
                  <td className="num">{formatCurrency(p.current_price)}</td>
                  <td className="num">{formatCurrency(p.invested)}</td>
                  <td className={`num ${pnlClass(p.unrealized_pnl)}`}>
                    {formatCurrency(p.unrealized_pnl)}
                  </td>
                  <td className={`num ${pnlClass(p.unrealized_pnl)}`}>
                    {formatSignedPercent(p.unrealized_pnl_pct)}
                  </td>
                  <td className="num muted">
                    {p.stop_loss ? formatCurrency(p.stop_loss) : '—'}
                  </td>
                  <td className="num muted">
                    {p.take_profit ? formatCurrency(p.take_profit) : '—'}
                  </td>
                  <td className="num">{p.holding_days}</td>
                  <td>
                    <button
                      className="danger"
                      disabled={close.isPending}
                      onClick={() => {
                        if (confirm(`Close ${p.quantity} × ${p.symbol} at market?`)) {
                          close.mutate(p.id)
                        }
                      }}
                    >
                      Close
                    </button>
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
