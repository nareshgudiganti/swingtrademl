import { useQuery } from '@tanstack/react-query'

import { api } from '../../api/client'
import type { ModuleMode } from '../../api/types'
import { useBrainStatus, useHealth, useModules, useRuns } from '../live'
import { MARKET_LABEL, STEP_LABEL } from '../vocab'
import { BrainOff, Card, NotConnected, Tag } from '../ui'
import { formatDateTime } from '../../lib/format'

const MODE_LABEL: Record<ModuleMode, string> = { on: 'On', shadow: 'Trial', off: 'Off' }
const MODE_TONE: Record<ModuleMode, 'green' | 'blue' | 'red'> = { on: 'green', shadow: 'blue', off: 'red' }

const RUN_KIND: Record<string, string> = { nightly: 'Nightly', intraday: 'Holdings check', why: 'One stock' }

// A run that hasn't finished yet (anything other than 'done'/'failed') is
// shown by its own status word rather than the generic "Failed: null" the
// old code produced for any non-'done' status (M3).
const RUN_STATUS_TEXT: Record<string, string> = { running: 'Running…', queued: 'Queued' }

const NOT_MEASURED = 'Not measured yet — the learning loop reports real results once ideas finish.'

export default function System() {
  const status = useBrainStatus()
  const health = useHealth()
  const modules = useModules()
  const runs = useRuns(8)
  const appStatus = useQuery({ queryKey: ['status'], queryFn: api.status })
  const moduleById = new Map((modules.data?.modules ?? []).map((m) => [m.id, m]))

  if (status === 'off') return <div className="tm-page"><BrainOff /></div>

  if (status === 'loading') {
    return (
      <div className="tm-page">
        <p className="tm-dim">Connecting to the brain…</p>
      </div>
    )
  }

  if (status === 'error') {
    return (
      <div className="tm-page">
        <Card title="Could not reach the brain">
          <p className="tm-dim">Something went wrong talking to the brain. Try again shortly.</p>
        </Card>
      </div>
    )
  }

  return (
    <div className="tm-page tm-grid">
      <div className="tm-grid tm-cols-3">
        <Card title="Last Run">
          {health.isLoading && <p className="tm-dim">Loading…</p>}
          {health.isError && <p className="tm-dim">Could not load.</p>}
          {health.data && (
            <>
              <div className="tm-big" style={{ fontSize: '1.2rem' }}>
                {health.data.last_run ? formatDateTime(health.data.last_run.started_at) : 'Never'}
              </div>
              {health.data.last_run && (
                <div className="tm-stat-label">
                  {health.data.last_run.status === 'done'
                    ? `Took ${(health.data.last_run.ms / 1000).toFixed(1)} s`
                    : health.data.last_run.status === 'failed'
                    ? `Failed: ${health.data.last_run.error ?? 'Unknown error'}`
                    : RUN_STATUS_TEXT[health.data.last_run.status] ?? health.data.last_run.status}
                </div>
              )}
            </>
          )}
        </Card>
        <Card title="Price Data">
          {health.isLoading && <p className="tm-dim">Loading…</p>}
          {health.isError && <p className="tm-dim">Could not load.</p>}
          {health.data && (
            <>
              <div className="tm-big" style={{ fontSize: '1.2rem' }}>
                {health.data.data.fresh == null ? 'Not checked' : health.data.data.fresh ? 'Up to date' : 'Not reliable'}
              </div>
              <div className="tm-stat-label">
                {health.data.data.fresh
                  ? 'Every check passed.'
                  : (health.data.data.issues[0] ?? '') +
                    (health.data.stale_count ? ` · ${health.data.stale_count} stocks affected` : '')}
              </div>
            </>
          )}
        </Card>
        <Card title="Failed Runs, Last 7 Days">
          {health.isLoading && <p className="tm-dim">Loading…</p>}
          {health.isError && <p className="tm-dim">Could not load.</p>}
          {health.data && (
            <>
              <div className="tm-big" style={{ fontSize: '1.2rem' }}>{health.data.failed_runs_7d}</div>
              <div className="tm-stat-label">
                {health.data.failed_runs_7d ? 'See the run list below.' : 'None — every run finished.'}
              </div>
            </>
          )}
        </Card>
      </div>

      <Card title="This Server" sub="What the app itself reports right now">
        {appStatus.isLoading && <p className="tm-dim">Loading…</p>}
        {appStatus.isError && <p className="tm-dim">Could not load server status.</p>}
        {appStatus.data && (
          <div className="tm-grid tm-cols-4">
            <div>
              <div className="tm-stat-value">{appStatus.data.active_model ?? 'No model set'}</div>
              <div className="tm-stat-label">Active model</div>
            </div>
            <div>
              <div className="tm-stat-value">{appStatus.data.broker_authenticated ? 'Connected' : 'Not connected'}</div>
              <div className="tm-stat-label">Zerodha</div>
            </div>
            <div>
              <div className="tm-stat-value">{appStatus.data.watchlist_size}</div>
              <div className="tm-stat-label">Stocks watched</div>
            </div>
            <div>
              <div className="tm-stat-value">{appStatus.data.open_positions}</div>
              <div className="tm-stat-label">Open positions</div>
            </div>
          </div>
        )}
      </Card>

      <div className="tm-grid tm-cols-2">
        <NotConnected what="Model Performance" reason={NOT_MEASURED} />
        <NotConnected what="Backtesting" reason={NOT_MEASURED} />
      </div>
      <div className="tm-grid tm-cols-2">
        <NotConnected what="Feature Importance" reason={NOT_MEASURED} />
        <NotConnected what="Strategy Equity Curve" reason={NOT_MEASURED} />
      </div>

      <Card title="The Eight Thinking Steps" sub="Each step is answered by an installed module, or a simple built-in answer until one is built. “Trial” runs a module and records its answer without using it.">
        {modules.isLoading && <p className="tm-dim">Loading…</p>}
        {modules.isError && <p className="tm-dim">Could not load the module list.</p>}
        {modules.data && (
          <div className="tm-table-wrap">
            <table className="tm-table">
              <tbody>
                {modules.data.steps.map((s) => (
                  <tr key={s.step}>
                    <td className="tm-strong" style={{ width: '30%' }}>{STEP_LABEL[s.step] ?? s.step}</td>
                    <td>
                      {s.modules.length === 0 && <span className="tm-dim">Simple built-in answer</span>}
                      {s.modules.map((id) => {
                        const m = moduleById.get(id)
                        return m ? (
                          <div key={id} className="tm-between" style={{ padding: '0.2rem 0' }}>
                            <span className="tm-dim">{m.id} · {m.name}</span>
                            <Tag tone={MODE_TONE[m.mode]}>{MODE_LABEL[m.mode]}{m.mandatory ? ' · required' : ''}</Tag>
                          </div>
                        ) : null
                      })}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card title="Recent Runs">
        {runs.isLoading && <p className="tm-dim">Loading…</p>}
        {runs.isError && <p className="tm-dim">Could not load recent runs.</p>}
        {runs.data && runs.data.length === 0 && <p className="tm-dim">No runs recorded yet.</p>}
        {runs.data && runs.data.length > 0 && (
          <div className="tm-table-wrap">
            <table className="tm-table">
              <thead>
                <tr>
                  <th>When</th>
                  <th>Market</th>
                  <th>Result</th>
                </tr>
              </thead>
              <tbody>
                {runs.data.map((r) => (
                  <tr key={r.run_id}>
                    <td>
                      {formatDateTime(r.started_at)}
                      <div className="tm-faint">
                        {RUN_KIND[r.kind] ?? r.kind}
                        {!r.live && ' · replay'}
                      </div>
                    </td>
                    <td className="tm-dim">{r.banner.mode ? MARKET_LABEL[r.banner.mode] ?? r.banner.mode : '—'}</td>
                    <td>
                      {r.status === 'failed' ? (
                        <Tag tone="red">Failed</Tag>
                      ) : (
                        <span className="tm-dim">
                          {Object.entries(r.counts)
                            .map(([w, n]) => `${n} ${w}`)
                            .join(' · ')}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  )
}
