import { useQuery } from '@tanstack/react-query'

import { api } from '../api/client'
import { Empty, ErrorBox, Loading } from '../components/Loading'
import { formatCurrency, formatDate, formatSignedPercent, pnlClass } from '../lib/format'

export default function Trades() {
  const trades = useQuery({ queryKey: ['trades'], queryFn: () => api.trades(200) })

  if (trades.isLoading) return <Loading />
  if (trades.error) return <ErrorBox error={trades.error} />

  const rows = trades.data ?? []
  const net = rows.reduce((sum, t) => sum + t.net_pnl, 0)
  const charges = rows.reduce((sum, t) => sum + t.charges, 0)

  return (
    <>
      <div className="page-head">
        <h1>Closed trades</h1>
        <div className="row">
          <span className="muted">Net</span>
          <strong className={pnlClass(net)}>{formatCurrency(net)}</strong>
          <span className="muted">after {formatCurrency(charges)} in charges</span>
        </div>
      </div>

      <div className="table-wrap">
        {!rows.length ? (
          <Empty label="No closed trades yet." />
        ) : (
          <table>
            <thead>
              <tr>
                <th className="sticky-col">Symbol</th>
                <th className="num">Qty</th>
                <th className="num">Entry</th>
                <th className="num">Exit</th>
                <th className="num">Gross</th>
                <th className="num">Charges</th>
                <th className="num">Net P&L</th>
                <th className="num">Return</th>
                <th className="num">Days</th>
                <th>Exit reason</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((t) => (
                <tr key={t.id}>
                  <td className="sticky-col">
                    <strong>{t.symbol}</strong>
                    <div className="muted" style={{ fontSize: '0.75rem' }}>
                      {formatDate(t.entry_at)} → {formatDate(t.exit_at)}
                    </div>
                  </td>
                  <td className="num">{t.quantity}</td>
                  <td className="num">{formatCurrency(t.entry_price)}</td>
                  <td className="num">{formatCurrency(t.exit_price)}</td>
                  <td className={`num ${pnlClass(t.gross_pnl)}`}>{formatCurrency(t.gross_pnl)}</td>
                  <td className="num muted">{formatCurrency(t.charges)}</td>
                  <td className={`num ${pnlClass(t.net_pnl)}`}>{formatCurrency(t.net_pnl)}</td>
                  <td className={`num ${pnlClass(t.net_pnl)}`}>
                    {formatSignedPercent(t.return_pct)}
                  </td>
                  <td className="num">{t.holding_days}</td>
                  <td className="muted">{t.exit_reason ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  )
}
