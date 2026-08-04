import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'

import { api } from '../api/client'
import { Empty, ErrorBox, Loading } from '../components/Loading'
import { formatCurrency, formatDateTime, formatPercent } from '../lib/format'

// Mirrors the strategy's own thresholds (ml_swing.py default_params) so the
// labels here mean the same thing a scan would actually do with the signal.
const STRONG_BUY = 0.7
const BUY = 0.6
const WATCH = 0.5
const EXIT = 0.35

function actionFor(probability: number, held: boolean) {
  if (held && probability <= EXIT) return { label: 'SELL / EXIT', tone: 'sell' as const }
  if (probability >= STRONG_BUY) return { label: 'STRONG BUY', tone: 'buy' as const }
  if (probability >= BUY) return { label: 'BUY', tone: 'buy' as const }
  if (probability >= WATCH) return { label: 'WATCH', tone: 'hold' as const }
  return { label: held ? 'HOLD' : 'AVOID', tone: 'hold' as const }
}

export default function Recommendations() {
  const models = useQuery({ queryKey: ['models'], queryFn: api.models })
  const positions = useQuery({ queryKey: ['positions'], queryFn: api.positions })
  const predictions = useQuery({ queryKey: ['predictions'], queryFn: () => api.predict(true) })

  const activeModel = models.data?.find((m) => m.status === 'ACTIVE')
  const heldSymbols = useMemo(
    () => new Set((positions.data ?? []).map((p) => p.symbol)),
    [positions.data],
  )

  const rows = useMemo(
    () =>
      (predictions.data ?? []).map((p) => {
        const held = heldSymbols.has(p.symbol)
        return { ...p, held, action: actionFor(p.probability, held) }
      }),
    [predictions.data, heldSymbols],
  )

  const sellFocus = rows.filter((r) => r.action.label === 'SELL / EXIT')
  const buyFocus = rows
    .filter((r) => r.action.label === 'BUY' || r.action.label === 'STRONG BUY')
    .slice(0, 8)

  return (
    <>
      <div className="page-head">
        <h1>Recommendations</h1>
        <button onClick={() => predictions.refetch()} disabled={predictions.isFetching}>
          {predictions.isFetching ? 'Scanning…' : 'Refresh now'}
        </button>
      </div>

      {activeModel ? (
        <div className="banner banner-info">
          <strong>
            {activeModel.name}:{activeModel.version}
          </strong>{' '}
          scores the watchlist for the probability of a ≥
          {formatPercent(activeModel.target_return_pct, 1)} move within{' '}
          {activeModel.prediction_horizon_days} trading days — roughly a day to two weeks out.
          This is the near-term focus list; a strategy still applies liquidity and volatility
          filters before it would actually act on a signal.
        </div>
      ) : (
        <div className="banner banner-warn">
          No active model, so there is nothing to rank yet. Train and activate one on the ML
          Models page first.
        </div>
      )}

      {predictions.error && <ErrorBox error={predictions.error} />}

      {sellFocus.length > 0 && (
        <>
          <h2>Holdings losing conviction — consider selling</h2>
          <div className="table-wrap" style={{ marginBottom: '1.5rem' }}>
            <table>
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th className="num">Price</th>
                  <th className="num">Confidence</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {sellFocus.map((r) => (
                  <tr key={r.instrument_id}>
                    <td>
                      <strong>{r.symbol}</strong>
                    </td>
                    <td className="num">{formatCurrency(r.price)}</td>
                    <td className="num">{formatPercent(r.probability, 1)}</td>
                    <td>
                      <span className={`badge badge-${r.action.tone}`}>{r.action.label}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      <h2>Top focus — buy candidates</h2>
      <div className="table-wrap" style={{ marginBottom: '1.5rem' }}>
        {predictions.isLoading ? (
          <Loading />
        ) : !buyFocus.length ? (
          <Empty label="No buy-strength candidates right now. Refresh after the next candle close, or check that the watchlist has enough history." />
        ) : (
          <table>
            <thead>
              <tr>
                <th>Symbol</th>
                <th className="num">Price</th>
                <th className="num">Confidence</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {buyFocus.map((r) => (
                <tr key={r.instrument_id}>
                  <td>
                    <strong>{r.symbol}</strong>
                  </td>
                  <td className="num">{formatCurrency(r.price)}</td>
                  <td className="num">{formatPercent(r.probability, 1)}</td>
                  <td>
                    <span className={`badge badge-${r.action.tone}`}>{r.action.label}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <h2>Full watchlist ranking</h2>
      <div className="table-wrap">
        {predictions.isLoading ? (
          <Loading />
        ) : !rows.length ? (
          <Empty label="No predictions yet. Sync instruments, set a watchlist, backfill history, and train a model first." />
        ) : (
          <table>
            <thead>
              <tr>
                <th>Symbol</th>
                <th className="num">Price</th>
                <th className="num">Confidence</th>
                <th>Status</th>
                <th>Action</th>
                <th>Scored</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.instrument_id}>
                  <td>
                    <strong>{r.symbol}</strong>
                  </td>
                  <td className="num">{formatCurrency(r.price)}</td>
                  <td className="num">{formatPercent(r.probability, 1)}</td>
                  <td>
                    {r.held ? (
                      <span className="badge badge-on">holding</span>
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                  <td>
                    <span className={`badge badge-${r.action.tone}`}>{r.action.label}</span>
                  </td>
                  <td className="muted">{formatDateTime(r.ts)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  )
}
