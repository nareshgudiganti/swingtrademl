import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { api } from '../api/client'
import { Empty, ErrorBox, Loading } from '../components/Loading'
import { formatDate, formatPercent } from '../lib/format'
import { modelLabel } from '../lib/tiers'

type Source = 'signals' | 'predictions'

/** A gap is the difference between what the model claimed and what happened.
 * Negative means it promised more than it delivered, which is the direction
 * that costs money — so it is the one called out. */
function verdictFor(gap: number | null, meaningful: boolean): { label: string; cls: string } {
  if (!meaningful) return { label: 'Too few to judge', cls: 'badge-off' }
  if (gap == null) return { label: '—', cls: 'badge-off' }
  if (gap <= -0.1) return { label: 'Over-confident', cls: 'badge-warn' }
  if (gap >= 0.1) return { label: 'Under-confident', cls: 'badge-paper' }
  return { label: 'Honest', cls: 'badge-on' }
}

export default function ModelLab() {
  const [source, setSource] = useState<Source>('signals')
  const report = useQuery({
    queryKey: ['calibration', source],
    queryFn: () => api.calibration(source),
  })
  const models = useQuery({ queryKey: ['models'], queryFn: api.models })
  const d = report.data
  const buckets = d?.buckets ?? []

  // Walk-forward lives on the model row, not the calibration report, and three
  // models run at once — one per cap tier. Picking whichever the search hit
  // first showed an unlabelled table the reader could not attribute to
  // anything, so every live model that has folds gets its own titled card and
  // the ones that have none are named rather than silently dropped.
  const activeModels = (models.data ?? []).filter((m) => m.status === 'ACTIVE')
  const tested = activeModels
    .map((m) => ({ model: m, folds: (m.metrics?.walk_forward ?? []).filter((f) => !f.skipped) }))
    .filter((t) => t.folds.length > 0)
  const untested = activeModels.filter(
    (m) => (m.metrics?.walk_forward ?? []).filter((f) => !f.skipped).length === 0,
  )

  return (
    <>
      <div className="page-head">
        <h1>Model Lab</h1>
        <div className="row">
          <button
            className={source === 'signals' ? 'primary' : 'ghost'}
            onClick={() => setSource('signals')}
          >
            Signals
          </button>
          <button
            className={source === 'predictions' ? 'primary' : 'ghost'}
            onClick={() => setSource('predictions')}
          >
            Predictions
          </button>
        </div>
      </div>

      <div className="card" style={{ marginBottom: '1.25rem' }}>
        <h2>Is the confidence number honest?</h2>
        <p className="stat-sub" style={{ marginTop: '0.3rem' }}>
          Every card in this app shows a confidence percentage. This is the only page that checks
          whether it was ever true: of the calls the model scored at 70%, how many actually worked
          out? A bucket with fewer than 30 examples is not evidence, and is marked as such.
        </p>
      </div>

      {report.isLoading && <Loading />}
      {report.isError && <ErrorBox error={report.error as Error} />}

      {d && (
        <>
          <div className="grid" style={{ marginBottom: '1.25rem' }}>
            <div className="card">
              <div className="stat-label">Calls scored</div>
              <div className="stat-value">{d.total_scored}</div>
              <div className="stat-sub">{d.excluded_below_min} below the confidence bar, ignored</div>
            </div>
            <div className="card">
              <div className="stat-label">Brier score</div>
              <div className="stat-value">
                {d.brier_score != null ? d.brier_score.toFixed(3) : '—'}
              </div>
              <div className="stat-sub">Lower is better. 0.25 is a coin flip.</div>
            </div>
            {/* signal_calibration leaves label_kind unset — a signal is graded
                against its own barrier, not against a model's label — so this
                tile read as a bare dash on the tab that actually has data. */}
            <div className="card">
              <div className="stat-label">{source === 'signals' ? 'Graded on' : 'Trained on'}</div>
              <div className="stat-value" style={{ fontSize: '1.1rem' }}>
                {source === 'signals' ? 'Target before stop' : (d.label_kind ?? '—')}
              </div>
              <div className="stat-sub">
                {source === 'signals'
                  ? 'Running out of time counts as a loss, not a draw'
                  : 'The question the model was asked'}
              </div>
            </div>
          </div>

          {tested.map(({ model, folds }) => (
            <div key={model.id} className="card" style={{ marginBottom: '1.25rem' }}>
              <h2>
                {modelLabel(model.name)}: tested across {folds.length} separate time periods
              </h2>
              <p className="stat-sub" style={{ marginTop: '0.3rem' }}>
                {/* A single train/test split can be flattered indefinitely by one
                    lucky window. Successive windows are the check on that. */}
                One good test window can flatter a model forever. Each row here trains on an
                earlier stretch of history and is judged on the stretch that followed it, which it
                never saw. &ldquo;Worth acting on&rdquo; counts only the calls it was confident
                enough to trade.
              </p>
              <div className="table-wrap" style={{ marginTop: '0.8rem' }}>
                <table>
                  <thead>
                    <tr>
                      <th>Period tested</th>
                      <th className="num">Confident calls</th>
                      <th className="num">Of those, right</th>
                      <th className="num">Better than chance?</th>
                    </tr>
                  </thead>
                  <tbody>
                    {folds.map((f) => {
                      const p = f.metrics.precision_at_threshold
                      const auc = f.metrics.roc_auc
                      // 0.5 is a coin flip; anything at or under it means the
                      // ranking carried no information on that window.
                      const beatsChance = auc != null && auc > 0.53
                      return (
                        <tr key={f.fold}>
                          <td>
                            {formatDate(f.test_start)} → {formatDate(f.test_end)}
                          </td>
                          <td className="num">{f.metrics.confident_signal_count ?? '—'}</td>
                          <td className="num">{p != null ? formatPercent(p, 0) : '—'}</td>
                          <td className="num">
                            <span className={`badge ${beatsChance ? 'badge-on' : 'badge-warn'}`}>
                              {auc == null ? '—' : beatsChance ? 'Yes' : 'No better'}
                            </span>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
              {folds.some((f) => (f.metrics.roc_auc ?? 0) <= 0.53) && (
                <div className="note" style={{ marginTop: '1rem' }}>
                  <span className="warnc">Read this honestly.</span> On at least one period the
                  model ranked stocks no better than chance. That is the number the readiness
                  gates care about, and it is the argument for staying on paper money.
                </div>
              )}
            </div>
          ))}

          {untested.length > 0 && (
            <div className="card" style={{ marginBottom: '1.25rem' }}>
              <h2>Never tested across separate time periods</h2>
              <p className="stat-sub" style={{ marginTop: '0.3rem' }}>
                {untested.map((m) => modelLabel(m.name)).join(', ')} —{' '}
                {untested.length === 1 ? 'this model was' : 'these models were'} checked on a
                single slice of history and nothing else. That is the weakest evidence a model can
                have: one lucky stretch can flatter it indefinitely and there is no second window
                to catch it. Retraining is what fills this in.
              </p>
            </div>
          )}

          {buckets.length === 0 && source === 'signals' && (
            <Empty label="Nothing has been scored yet — calibration needs closed trades to judge." />
          )}

          {/* The predictions report filters on label_kind='barrier' (see
              ml/calibration.py::prediction_calibration), so while every model on
              the system is still an endpoint-era one this tab is empty by
              construction. An unexplained Empty read as a broken page. */}
          {buckets.length === 0 && source === 'predictions' && (
            <div className="card">
              <h2>Nothing to show here yet</h2>
              <p className="stat-sub" style={{ marginTop: '0.3rem' }}>
                This tab only counts models trained on the trade the system actually takes — up 8%
                before down 4%, within 15 trading days. No model has been trained on that question
                and scored yet, so there is nothing to grade. The Signals tab is the one with data
                in it.
              </p>
            </div>
          )}

          {buckets.length > 0 && (
            <div className="card">
              <h2>By confidence band</h2>
              <div className="table-wrap" style={{ marginTop: '0.8rem' }}>
                <table>
                  <thead>
                    <tr>
                      <th>It said</th>
                      <th className="num">Calls</th>
                      <th className="num">Worked out</th>
                      <th className="num">Actually right</th>
                      <th className="num">Off by</th>
                      <th>Verdict</th>
                    </tr>
                  </thead>
                  <tbody>
                    {buckets.map((b) => {
                      const verdict = verdictFor(b.calibration_gap, b.meaningful)
                      return (
                        <tr key={`${b.lower}-${b.upper}`}>
                          <td>
                            {formatPercent(b.lower, 0)} – {formatPercent(b.upper, 0)}
                          </td>
                          <td className="num">{b.n}</td>
                          <td className="num">{b.wins}</td>
                          <td className="num">
                            {b.observed_rate != null ? formatPercent(b.observed_rate, 0) : '—'}
                          </td>
                          <td
                            className={`num ${
                              b.calibration_gap == null || !b.meaningful
                                ? ''
                                : b.calibration_gap < 0
                                  ? 'neg'
                                  : 'pos'
                            }`}
                          >
                            {b.calibration_gap != null
                              ? `${b.calibration_gap > 0 ? '+' : ''}${(b.calibration_gap * 100).toFixed(0)} pts`
                              : '—'}
                          </td>
                          <td>
                            <span className={`badge ${verdict.cls}`}>{verdict.label}</span>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
              <div className="note" style={{ marginTop: '1rem' }}>
                &ldquo;Off by&rdquo; is what it claimed minus what happened. Negative means it
                promised more than it delivered — the direction that costs money.
              </div>
              {/* signal_calibration filters on mode only, so all three cap-tier
                  models plus the benchmark land in the same buckets. Separating
                  the record per model is version-tracking work; until then the
                  page must not imply these rows describe one model. */}
              <div className="note" style={{ marginTop: '0.6rem' }}>
                Every paper strategy&rsquo;s calls are counted together here — large cap, mid cap,
                small cap and the benchmark share these rows. One model with a long record can
                therefore speak for all of them.
              </div>
            </div>
          )}
        </>
      )}
    </>
  )
}
