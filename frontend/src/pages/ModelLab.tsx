import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { api } from '../api/client'
import { Empty, ErrorBox, Loading } from '../components/Loading'
import { formatPercent } from '../lib/format'

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
  const d = report.data
  const buckets = d?.buckets ?? []

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
            <div className="card">
              <div className="stat-label">Trained on</div>
              <div className="stat-value" style={{ fontSize: '1.1rem' }}>
                {d.label_kind ?? '—'}
              </div>
              <div className="stat-sub">The question the model was asked</div>
            </div>
          </div>

          {buckets.length === 0 && (
            <Empty label="Nothing has been scored yet — calibration needs closed trades to judge." />
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
            </div>
          )}
        </>
      )}
    </>
  )
}
