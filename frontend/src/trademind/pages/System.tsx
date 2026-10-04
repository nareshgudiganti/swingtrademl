import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../../api/client'
import type { BrainModuleInfo, ModuleMode } from '../../api/types'
import { Confirm } from '../Confirm'
import { useHealth, useModules, useRuns } from '../live'
import { MARKET_LABEL, MODULE_PLAIN, STEP_LABEL, moduleName } from '../vocab'
import { BrainGate, Card, NotConnected, Seg, Tag } from '../ui'
import { formatDateTime, modelLabel } from '../../lib/format'

const MODE_LABEL: Record<ModuleMode, string> = { on: 'On', shadow: 'Trial', off: 'Off' }

const RUN_KIND: Record<string, string> = { nightly: 'Nightly', intraday: 'Holdings check', why: 'One stock' }

// A run that hasn't finished yet (anything other than 'done'/'failed') is
// shown by its own status word rather than the generic "Failed: null" the
// old code produced for any non-'done' status (M3).
const RUN_STATUS_TEXT: Record<string, string> = { running: 'Running…', queued: 'Queued' }

const MODE_MEANING: Record<ModuleMode, string> = {
  on: 'On: the module works and its answer is used.',
  shadow: 'Trial: the module works and its answer is recorded, but the brain does not use it.',
  off: 'Off: the module does not work at all and a simple built-in answer is used.',
}

const MODE_OPTIONS = (['on', 'shadow', 'off'] as ModuleMode[]).map((id) => ({ id, label: MODE_LABEL[id] }))

const BRAIN_KEYS = ['brainLatest', 'brainHealth', 'brainRuns', 'brainModules', 'brainTrace']

const NOT_MEASURED = 'Not measured yet — the learning loop reports real results once ideas finish.'

export default function System() {
  return (
    <BrainGate allowNoRun>
      <SystemBody />
    </BrainGate>
  )
}

function SystemBody() {
  const health = useHealth()
  const modules = useModules()
  const runs = useRuns(8)
  const appStatus = useQuery({ queryKey: ['status'], queryFn: api.status })
  const moduleById = new Map((modules.data?.modules ?? []).map((m) => [m.id, m]))
  const queryClient = useQueryClient()
  const [change, setChange] = useState<{ m: BrainModuleInfo; mode: ModuleMode } | null>(null)
  const setMode = useMutation({
    mutationFn: ({ id, mode }: { id: string; mode: ModuleMode }) => api.setBrainModuleMode(id, mode),
    onSuccess: () => {
      for (const key of BRAIN_KEYS) void queryClient.invalidateQueries({ queryKey: [key] })
    },
  })

  return (
    <div className="tm-page tm-grid">
      <RunControls />
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
              {(appStatus.data.active_models ?? []).length > 0 ? (
                appStatus.data.active_models!.map((m) => (
                  <div key={m} className="tm-strong" title={m}>
                    {modelLabel(m)}
                  </div>
                ))
              ) : (
                <div className="tm-stat-value">{appStatus.data.active_model ?? 'No model set'}</div>
              )}
              <div className="tm-stat-label">Active models</div>
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
                          <div key={id} className="tm-between" style={{ padding: '0.2rem 0', flexWrap: 'wrap' }}>
                            <span className="tm-dim" title={`${m.id} · ${m.name}. ${MODULE_PLAIN[m.id]?.does ?? ''}`}>
                              {moduleName(m.id)}
                            </span>
                            {m.mandatory ? (
                              <Tag tone="green">Always on · required</Tag>
                            ) : (
                              <Seg
                                small
                                options={MODE_OPTIONS}
                                active={m.mode}
                                onChange={(mode) => mode !== m.mode && setChange({ m, mode })}
                              />
                            )}
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

      {change && (
        <Confirm
          title={`Set “${moduleName(change.m.id)}” to ${MODE_LABEL[change.mode]}?`}
          confirmLabel={`Set to ${MODE_LABEL[change.mode]}`}
          danger={change.mode === 'off'}
          onConfirm={() => setMode.mutateAsync({ id: change.m.id, mode: change.mode })}
          onClose={() => setChange(null)}
        >
          {MODE_MEANING[change.mode]} It takes effect from the next time the brain runs.
        </Confirm>
      )}

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

// Run the brain now, and the Telegram alert for the latest run.
function RunControls() {
  const queryClient = useQueryClient()
  const [asking, setAsking] = useState(false)
  const [asSend, setAsSend] = useState(false)
  const latest = useQuery({
    queryKey: ['brainLatest', 'nightly'],
    queryFn: () => api.brainLatestRun('nightly'),
    retry: false,
  })
  const runId = latest.data?.run_id
  const preview = useQuery({
    queryKey: ['brainAlert', runId],
    queryFn: () => api.brainAlertPreview(runId!),
    enabled: !!runId,
  })
  const runNow = useMutation({
    mutationFn: api.brainRunNow,
    onSuccess: () => {
      for (const key of [...BRAIN_KEYS, 'brainAlert']) void queryClient.invalidateQueries({ queryKey: [key] })
    },
  })
  const send = useMutation({
    mutationFn: () => api.brainAlertSend(runId!),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['brainAlert'] }),
  })
  const items = preview.data?.items ?? []
  const done = runNow.data
  const counts = done ? Object.entries(done.counts).map(([w, n]) => `${n} ${w}`).join(' · ') : ''

  return (
    <div className="tm-grid tm-cols-2">
      <Card title="Run the brain now" sub="Makes the brain think again about every stock right now, instead of waiting for tonight.">
        <div className="tm-gl-actions">
          <button className="tm-btn" disabled={runNow.isPending} onClick={() => setAsking(true)}>
            {runNow.isPending ? 'Thinking…' : 'Run the brain now'}
          </button>
        </div>
        {runNow.isPending && <p className="tm-dim">This takes a few minutes. You can leave this page open.</p>}
        {runNow.isError && (
          <p className="tm-neg">The run failed: {runNow.error instanceof Error ? runNow.error.message : String(runNow.error)}</p>
        )}
        {done && !runNow.isPending && (
          <p className="tm-dim">
            {done.status === 'failed'
              ? `The run failed: ${done.error ?? 'unknown error'}`
              : `Finished ${formatDateTime(done.started_at)}, took ${(done.ms / 1000).toFixed(1)} s${counts ? ': ' + counts : ''}.`}
          </p>
        )}
      </Card>

      <Card title="Today's alert" sub="The short message the brain would send to your phone on Telegram for its latest run.">
        {latest.isLoading && <p className="tm-dim">Loading…</p>}
        {!latest.isLoading && !runId && <p className="tm-dim">The brain has not run yet, so there is nothing to send.</p>}
        {runId && preview.isLoading && <p className="tm-dim">Loading…</p>}
        {runId && preview.isError && <p className="tm-neg">Could not load the alert.</p>}
        {runId && preview.data && items.length === 0 && (
          <p className="tm-dim">Nothing new to tell since the last run (or it was already sent today).</p>
        )}
        {items.length > 0 && (
          <ul style={{ margin: '0 0 0.7rem', paddingLeft: '1.1rem' }} className="tm-dim">
            {items.map((i) => (
              <li key={i.key}>{i.text}</li>
            ))}
          </ul>
        )}
        <div className="tm-gl-actions">
          <button className="tm-btn" disabled={!items.length || send.isPending} onClick={() => setAsSend(true)}>
            {send.isPending ? 'Sending…' : 'Send to Telegram'}
          </button>
        </div>
        {send.data && (
          <p className="tm-dim">
            {send.data.sent
              ? `Sent ${send.data.count} update${send.data.count === 1 ? '' : 's'} to Telegram.`
              : send.data.count
                ? 'Not sent: Telegram is switched off or did not answer. Nothing was marked as told.'
                : 'Nothing new to send.'}
          </p>
        )}
      </Card>

      {asking && (
        <Confirm
          title="Run the brain now?"
          confirmLabel="Run now"
          onConfirm={() => {
            // Do not hold the dialog open for the whole run; the card shows progress and errors.
            runNow.mutate()
          }}
          onClose={() => setAsking(false)}
        >
          This takes a few minutes. The brain only records its decisions — nothing is bought or sold.
        </Confirm>
      )}
      {asSend && (
        <Confirm
          title="Send this alert to Telegram?"
          confirmLabel="Send"
          onConfirm={() => send.mutateAsync()}
          onClose={() => setAsSend(false)}
        >
          The message above goes to your Telegram now. Each update is only sent once.
        </Confirm>
      )}
    </div>
  )
}
