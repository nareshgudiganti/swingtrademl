import { useQuery } from '@tanstack/react-query'

import { api } from '../api/client'
import type { BrainCompareSummary } from '../api/types'
import { formatSignedPercent } from '../lib/format'
import { ErrorBox, Loading } from './Loading'

/* Brain go-live (build book M18): the brain as a practice strategy next to
 * version 1, scored the same way. Plain words only. */

function pct(value: number | null): string {
  return value === null ? 'n/a' : `${(value * 100).toFixed(0)}%`
}

function avg(value: number | null): string {
  return value === null ? 'n/a' : formatSignedPercent(value, 1)
}

function SummaryCells({ s }: { s: BrainCompareSummary }) {
  return (
    <>
      <td>{s.ideas}</td>
      <td>{s.finished}</td>
      <td>{pct(s.hit_rate)}</td>
      <td>{pct(s.stopped)}</td>
      <td>{avg(s.avg_outcome_pct)}</td>
    </>
  )
}

export function BrainCompareCard() {
  const compare = useQuery({ queryKey: ['brainCompare'], queryFn: api.brainCompare })
  const data = compare.data
  return (
    <div className="card" style={{ marginBottom: '1.25rem' }}>
      <h2>Brain vs version 1</h2>
      <p className="stat-sub">
        The brain runs as a practice strategy next to version 1. Both are scored the same way: did the price reach
        the target before the stop? Only days when the brain ran are compared.
      </p>
      {compare.isLoading && <Loading />}
      {compare.isError && <ErrorBox error={compare.error} />}
      {data && (
        <>
          <div className="banner banner-info" style={{ margin: '0.6rem 0' }}>
            {data.note}
          </div>
          <p className="stat-sub">
            {Math.min(data.brain_finished, data.needed)} of {data.needed} brain ideas have finished. {data.needed} are
            needed before its ideas can be bought, and even then only with your OK.
          </p>
          {data.strategies.length > 0 && (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Strategy</th>
                    <th>Ideas</th>
                    <th>Finished</th>
                    <th>Reached the target</th>
                    <th>Hit the stop</th>
                    <th>Average result</th>
                  </tr>
                </thead>
                <tbody>
                  {data.strategies.map((s) => (
                    <tr key={s.name}>
                      <td>{s.is_brain ? <strong>{s.name} (brain)</strong> : s.name}</td>
                      <SummaryCells s={s} />
                    </tr>
                  ))}
                  <tr>
                    <td>
                      <em>All of version 1</em>
                    </td>
                    <SummaryCells s={data.version1} />
                  </tr>
                </tbody>
              </table>
            </div>
          )}
          {data.by_week.length > 0 && (
            <>
              <h3>By week</h3>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Week</th>
                      <th>Brain: finished</th>
                      <th>Brain: reached the target</th>
                      <th>Brain: average</th>
                      <th>Version 1: finished</th>
                      <th>Version 1: reached the target</th>
                      <th>Version 1: average</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.by_week.map((w) => (
                      <tr key={w.week}>
                        <td>{w.week}</td>
                        <td>{w.brain.finished}</td>
                        <td>{pct(w.brain.hit_rate)}</td>
                        <td>{avg(w.brain.avg_outcome_pct)}</td>
                        <td>{w.version1.finished}</td>
                        <td>{pct(w.version1.hit_rate)}</td>
                        <td>{avg(w.version1.avg_outcome_pct)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </>
      )}
    </div>
  )
}
