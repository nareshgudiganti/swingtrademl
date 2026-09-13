import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../api/client'
import Stat from '../components/Stat'
import { Empty, ErrorBox, Loading } from '../components/Loading'
import TierBadge from '../components/TierBadge'
import { TIERS } from '../lib/tiers'
import { formatCurrency, formatDate, formatDateTime, formatPercent, formatSignedPercent } from '../lib/format'

const ALGORITHMS = [
  { value: 'lightgbm', label: 'LightGBM' },
  { value: 'random_forest', label: 'Random Forest' },
  { value: 'gradient_boosting', label: 'Gradient Boosting' },
  { value: 'logistic_regression', label: 'Logistic Regression' },
] as const

export default function Models() {
  const queryClient = useQueryClient()
  const models = useQuery({ queryKey: ['models'], queryFn: api.models })
  const strategies = useQuery({ queryKey: ['strategies'], queryFn: api.strategies })
  const predictions = useQuery({ queryKey: ['predictions', 100], queryFn: () => api.predictions(100) })

  const [horizonInput, setHorizonInput] = useState('5')
  const [testedHorizon, setTestedHorizon] = useState<number | null>(null)
  const horizonAccuracy = useQuery({
    queryKey: ['predAccuracyHorizon', testedHorizon],
    queryFn: () => api.predictionAccuracyAtHorizon(testedHorizon as number),
    enabled: testedHorizon !== null,
  })

  const [trainTierIdx, setTrainTierIdx] = useState(0)
  const [trainAlgorithm, setTrainAlgorithm] = useState<string>('lightgbm')
  const trainTier = TIERS[trainTierIdx] ?? TIERS[0]
  // Each tier trains on its own strategy's symbol universe — omitted (→
  // undefined, the backend's "whole watchlist" default) only for large-cap's
  // ml_swing_main, whose own `symbols` list is deliberately empty for the
  // same reason.
  const trainStrategy = strategies.data?.find((s) => s.name === trainTier.match)
  const trainSymbols = trainStrategy?.symbols.length ? trainStrategy.symbols : undefined

  const train = useMutation({
    mutationFn: () =>
      api.train({
        name: trainTier.modelName,
        algorithm: trainAlgorithm,
        symbols: trainSymbols,
        auto_activate: false,
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['models'] }),
  })

  // One live-accuracy read per tier's currently active model — the pooled,
  // single number this page used to show hid that only large-cap has enough
  // history to mean anything yet (see the honest state on each card below).
  const activeModelByTier = TIERS.map((tier) =>
    models.data?.find((m) => m.status === 'ACTIVE' && m.name === tier.modelName),
  )
  const tierAccuracy = [
    useQuery({
      queryKey: ['predAccuracy', activeModelByTier[0]?.id],
      queryFn: () => api.predictionAccuracy(activeModelByTier[0]!.id),
      enabled: !!activeModelByTier[0],
    }),
    useQuery({
      queryKey: ['predAccuracy', activeModelByTier[1]?.id],
      queryFn: () => api.predictionAccuracy(activeModelByTier[1]!.id),
      enabled: !!activeModelByTier[1],
    }),
    useQuery({
      queryKey: ['predAccuracy', activeModelByTier[2]?.id],
      queryFn: () => api.predictionAccuracy(activeModelByTier[2]!.id),
      enabled: !!activeModelByTier[2],
    }),
  ]

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
      </div>

      <p className="muted" style={{ marginTop: '-0.5rem', marginBottom: '1.1rem' }}>
        Three independent classifiers, one per market-cap tier — each answers the same question,
        "will this stock move up by its target return within its horizon?", for its own universe.
      </p>

      <div className="grid" style={{ marginBottom: '1.5rem' }}>
        {TIERS.map((tier, i) => {
          const active = activeModelByTier[i]
          const acc = tierAccuracy[i]?.data
          return (
            <div className="card" key={tier.match}>
              <div className="row" style={{ justifyContent: 'space-between', marginBottom: '0.6rem' }}>
                <TierBadge tier={tier} />
                <span className="mono muted" style={{ fontSize: '0.78rem' }}>
                  {active ? `${active.name}:${active.version}` : 'none active'}
                </span>
              </div>
              {active ? (
                <>
                  <div className="stat-sub" style={{ marginBottom: '0.5rem' }}>
                    {active.algorithm} · {active.prediction_horizon_days}d horizon · +
                    {formatPercent(active.target_return_pct, 1)} target
                  </div>
                  <div className="stat-value" style={{ fontSize: '1.3rem' }}>
                    {acc && acc.evaluated_predictions > 0 ? formatPercent(acc.accuracy, 1) : '—'}
                  </div>
                  <div className="stat-sub">
                    {acc && acc.evaluated_predictions > 0
                      ? `live accuracy — ${acc.correct} of ${acc.evaluated_predictions} evaluated calls correct`
                      : 'no evaluated predictions yet — too new to have a live win-rate'}
                  </div>
                </>
              ) : (
                <div className="stat-sub">Train and activate a model for this tier below.</div>
              )}
            </div>
          )
        })}
      </div>

      <h2>Train a new version</h2>
      <div className="card" style={{ marginBottom: '1.5rem' }}>
        <div className="grid" style={{ marginBottom: '0.9rem' }}>
          <label>
            <div className="stat-label">Tier</div>
            <select value={trainTierIdx} onChange={(e) => setTrainTierIdx(Number(e.target.value))}>
              {TIERS.map((tier, i) => (
                <option key={tier.match} value={i}>
                  {tier.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            <div className="stat-label">Algorithm</div>
            <select value={trainAlgorithm} onChange={(e) => setTrainAlgorithm(e.target.value)}>
              {ALGORITHMS.map((a) => (
                <option key={a.value} value={a.value}>
                  {a.label}
                </option>
              ))}
            </select>
          </label>
        </div>
        <button className="primary" onClick={() => train.mutate()} disabled={train.isPending}>
          {train.isPending ? 'Training…' : `Train ${trainTier.label}`}
        </button>
        <p className="muted" style={{ fontSize: '0.82rem', marginBottom: 0 }}>
          Trains on {trainSymbols ? `${trainSymbols.length} symbols (${trainTier.label}'s own universe)` : 'the full watchlist'}
          . New versions start inactive — review its metrics below, then activate.
        </p>
      </div>

      {train.data && <div className="banner banner-info">{train.data.message}. {train.data.detail}</div>}
      {(train.error || activate.error) && <ErrorBox error={train.error ?? activate.error} />}

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
                <th>Tier</th>
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
              {[...rows]
                .sort((a, b) => {
                  const ai = TIERS.findIndex((t) => t.modelName === a.name)
                  const bi = TIERS.findIndex((t) => t.modelName === b.name)
                  return ai - bi || b.version.localeCompare(a.version)
                })
                .map((m) => {
                  const tier = TIERS.find((t) => t.modelName === m.name)
                  return (
                <tr key={m.id}>
                  <td>{tier ? <TierBadge tier={tier} /> : <span className="muted">{m.name}</span>}</td>
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
                  )
                })}
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
