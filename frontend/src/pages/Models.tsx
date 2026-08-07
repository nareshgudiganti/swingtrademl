import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../api/client'
import Stat from '../components/Stat'
import { Empty, ErrorBox, Loading } from '../components/Loading'
import { formatCurrency, formatDate, formatDateTime, formatPercent, formatSignedPercent } from '../lib/format'

export default function Models() {
  const queryClient = useQueryClient()
  const models = useQuery({ queryKey: ['models'], queryFn: api.models })
  const accuracy = useQuery({ queryKey: ['predAccuracy'], queryFn: api.predictionAccuracy })
  const predictions = useQuery({ queryKey: ['predictions', 100], queryFn: () => api.predictions(100) })

  const [horizonInput, setHorizonInput] = useState('5')
  const [testedHorizon, setTestedHorizon] = useState<number | null>(null)
  const horizonAccuracy = useQuery({
    queryKey: ['predAccuracyHorizon', testedHorizon],
    queryFn: () => api.predictionAccuracyAtHorizon(testedHorizon as number),
    enabled: testedHorizon !== null,
  })

  const train = useMutation({
    mutationFn: (algorithm: string) => api.train({ algorithm, auto_activate: false }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['models'] }),
  })

  const activate = useMutation({
    mutationFn: (id: number) => api.activateModel(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['models'] })
      queryClient.invalidateQueries({ queryKey: ['status'] })
    },
  })

  if (models.isLoading) return <Loading />
  if (models.error) return <ErrorBox error={models.error} />

  const rows = models.data ?? []

  return (
    <>
      <div className="page-head">
        <h1>ML models</h1>
        <div className="row">
          <button onClick={() => train.mutate('lightgbm')} disabled={train.isPending}>
            Train LightGBM
          </button>
          <button onClick={() => train.mutate('random_forest')} disabled={train.isPending}>
            Train Random Forest
          </button>
        </div>
      </div>

      {train.data && <div className="banner banner-info">{train.data.message}. {train.data.detail}</div>}
      {(train.error || activate.error) && <ErrorBox error={train.error ?? activate.error} />}

      <div className="banner banner-info">
        Held-out metrics come from a chronological split at training time. The numbers that matter
        are below — realised accuracy on predictions the bot actually made, scored once each
        prediction&apos;s horizon has elapsed.
      </div>

      <div className="grid">
        <Stat
          label="Live prediction accuracy"
          value={
            accuracy.data ? formatPercent(accuracy.data.accuracy, 1) : '—'
          }
          sub={
            accuracy.data
              ? `${accuracy.data.correct} correct of ${accuracy.data.evaluated_predictions} evaluated`
              : 'No predictions scored yet'
          }
        />
        <Stat label="Registered versions" value={rows.length} />
        <Stat
          label="Active model"
          value={rows.find((m) => m.status === 'ACTIVE')?.version ?? 'none'}
          sub={rows.find((m) => m.status === 'ACTIVE')?.name ?? 'Train and activate one'}
        />
      </div>

      <h2>Test a custom horizon</h2>
      <div className="banner banner-info">
        The live accuracy above is locked to whatever horizon the active model was trained for.
        This re-scores every prediction already on record against a horizon <em>you</em> pick —
        read-only, nothing is retrained or overwritten — so you can check "is the app guessing
        properly" at 3 days, 10 days, or anything else, using the same predictions it already made.
      </div>
      <div className="row" style={{ marginBottom: '1rem' }}>
        <input
          type="number"
          min={1}
          max={60}
          value={horizonInput}
          onChange={(e) => setHorizonInput(e.target.value)}
          style={{ width: '5rem' }}
        />
        <span className="muted">days</span>
        <button
          onClick={() => setTestedHorizon(Number(horizonInput))}
          disabled={horizonAccuracy.isFetching || !horizonInput}
        >
          {horizonAccuracy.isFetching ? 'Checking…' : 'Check accuracy at this horizon'}
        </button>
      </div>
      {horizonAccuracy.error && <ErrorBox error={horizonAccuracy.error} />}
      {horizonAccuracy.data && (
        <div className="grid" style={{ marginBottom: '1.5rem' }}>
          <Stat
            label={`Accuracy at ${horizonAccuracy.data.horizon_days}d`}
            value={
              horizonAccuracy.data.evaluable
                ? formatPercent(horizonAccuracy.data.accuracy, 1)
                : '—'
            }
            sub={
              horizonAccuracy.data.evaluable
                ? `${horizonAccuracy.data.correct} correct of ${horizonAccuracy.data.evaluable} old enough to check`
                : 'No predictions are old enough yet to test this horizon'
            }
          />
          <Stat
            label="Avg actual return"
            value={
              horizonAccuracy.data.evaluable
                ? formatPercent(horizonAccuracy.data.avg_actual_return, 2)
                : '—'
            }
            sub={`vs. the +${formatPercent(horizonAccuracy.data.target_return, 0)} target`}
          />
        </div>
      )}

      <div className="table-wrap">
        {!rows.length ? (
          <Empty label="No models trained yet. Ingest candles first, then train." />
        ) : (
          <table>
            <thead>
              <tr>
                <th>Model</th>
                <th>Algorithm</th>
                <th>Status</th>
                <th className="num">Samples</th>
                <th className="num">Accuracy</th>
                <th className="num">Precision</th>
                <th className="num">Recall</th>
                <th className="num">ROC AUC</th>
                <th>Trained</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((m) => (
                <tr key={m.id}>
                  <td>
                    <strong>
                      {m.name}:{m.version}
                    </strong>
                    <div className="muted" style={{ fontSize: '0.75rem' }}>
                      {m.prediction_horizon_days}d horizon, +
                      {formatPercent(m.target_return_pct, 1)} target
                    </div>
                  </td>
                  <td className="muted">{m.algorithm}</td>
                  <td>
                    <span className={`badge ${m.status === 'ACTIVE' ? 'badge-on' : 'badge-off'}`}>
                      {m.status.toLowerCase()}
                    </span>
                  </td>
                  <td className="num">{m.n_samples?.toLocaleString('en-IN') ?? '—'}</td>
                  <td className="num">{m.accuracy !== null ? m.accuracy.toFixed(3) : '—'}</td>
                  <td className="num">{m.precision !== null ? m.precision.toFixed(3) : '—'}</td>
                  <td className="num">{m.recall !== null ? m.recall.toFixed(3) : '—'}</td>
                  <td className="num">{m.roc_auc !== null ? m.roc_auc.toFixed(3) : '—'}</td>
                  <td className="muted">{m.trained_at ? formatDate(m.trained_at) : '—'}</td>
                  <td>
                    {m.status !== 'ACTIVE' && (
                      <button
                        className="primary"
                        onClick={() => activate.mutate(m.id)}
                        disabled={activate.isPending}
                      >
                        Activate
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <h2 style={{ marginTop: '2rem' }}>Prediction history</h2>
      <div className="banner banner-info">
        What the bot actually predicted for each symbol, and — once the prediction&apos;s horizon
        has elapsed — what really happened in the market. This is the same data the accuracy stat
        above is computed from, one row per prediction. A fresh row is recorded for the whole
        watchlist automatically every trading day after the close.
      </div>
      <div className="table-wrap">
        {predictions.isLoading ? (
          <Loading />
        ) : predictions.error ? (
          <ErrorBox error={predictions.error} />
        ) : !predictions.data?.length ? (
          <Empty label="No predictions recorded yet — check back after the next trading day's close." />
        ) : (
          <table>
            <thead>
              <tr>
                <th>Predicted</th>
                <th>Symbol</th>
                <th>Called</th>
                <th className="num">Confidence</th>
                <th className="num">Price then</th>
                <th className="num">Actual return</th>
                <th>Outcome</th>
              </tr>
            </thead>
            <tbody>
              {predictions.data.map((p) => (
                <tr key={p.id}>
                  <td className="muted">{formatDateTime(p.ts)}</td>
                  <td>
                    <strong>{p.symbol}</strong>
                  </td>
                  <td>
                    <span className={`badge ${p.predicted_class ? 'badge-buy' : 'badge-sell'}`}>
                      {p.predicted_class ? 'UP' : 'NO MOVE'}
                    </span>
                  </td>
                  <td className="num">{formatPercent(p.probability, 1)}</td>
                  <td className="num">{formatCurrency(p.price_at_prediction)}</td>
                  <td className="num">
                    {p.actual_return !== null ? formatSignedPercent(p.actual_return, 1) : '—'}
                  </td>
                  <td>
                    {p.was_correct === null ? (
                      <span className="badge badge-hold">pending</span>
                    ) : p.was_correct ? (
                      <span className="badge badge-on">correct</span>
                    ) : (
                      <span className="badge badge-off">wrong</span>
                    )}
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
