import { useCallback, useEffect, useState } from 'react'

import { ErrorBox, Loading } from '../components/Loading'
import type { AdminCall } from './AdminModules'

// Admin only, read only: which 5D and 15D models exist, which are approved, when they last ran and whether the
// Brain used them. This screen only displays; nothing here can change, activate or train a model.

export type BrainUsage = { state: 'used' | 'shadow_only' | 'unknown'; label: string; last_session: string | null }
export type ModelRow = {
  id: number
  name: string
  version: string
  algorithm: string
  horizon_days: number
  status: string
  approval: { live_approved: boolean; label: string; role: string; role_recorded: boolean; approved_at: string | null; approved_by: string }
  evidence: Record<string, string | number>
  last_scored_at: string
  last_shadow_lane_day: string | null
  brain_usage: BrainUsage
}
export type JobRow = {
  id: string
  about: string
  scheduled: boolean
  schedule: string | null
  next_run: string | null
  last_started_at: string | null
  last_status: string | null
}
export type ModelOverview = {
  horizons: Record<string, ModelRow[]>
  jobs: { worker_alive: boolean; runs_available: boolean; rows: JobRow[] }
  not_recorded: string[]
}

const when = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' }) + ' IST' : 'unknown'

export function ModelOverviewView({ data }: { data: ModelOverview }) {
  return (
    <div>
      <h2 style={{ marginTop: 0 }}>Models: 5D and 15D</h2>
      <p>This page only shows information. Nothing here can approve, switch or train a model.</p>
      {['5', '15'].map((h) => (
        <section key={h}>
          <h3>{h}-day models</h3>
          {(data.horizons[h] ?? []).length === 0 && <p>No approved or frozen {h}-day model found.</p>}
          {(data.horizons[h] ?? []).map((m) => (
            <div className="card" key={m.id}>
              <strong>{m.name}</strong> version {m.version} ({m.algorithm}), looks {m.horizon_days} trading days ahead
              <ul>
                <li>Approval: {m.approval.label}. Approved by: {m.approval.approved_by}.</li>
                <li>Role: {m.approval.role}{m.approval.role_recorded ? '' : ' (worked out from the name, not recorded)'}</li>
                <li>Trained: {String(m.evidence.trained_at)}; examples used: {String(m.evidence.training_samples)}</li>
                <li>
                  Test results: accuracy {String(m.evidence.accuracy)}, precision {String(m.evidence.precision)}, report link:{' '}
                  {String(m.evidence.evaluation_report_link)}
                </li>
                <li>Last scored: {m.last_scored_at === 'never scored' ? m.last_scored_at : when(m.last_scored_at)}</li>
                <li>
                  Brain: {m.brain_usage.label}
                  {m.brain_usage.last_session ? ` (last ${m.brain_usage.last_session})` : ''}
                </li>
              </ul>
            </div>
          ))}
        </section>
      ))}
      <h3>Scheduled runs</h3>
      {!data.jobs.worker_alive && <p role="alert">The background worker is not reporting, so run times may be missing.</p>}
      <ul>
        {data.jobs.rows.map((j) => (
          <li key={j.id}>
            {j.about}: {j.scheduled ? `${j.schedule ?? 'scheduled'}, next run ${when(j.next_run)}` : 'not scheduled (switched off)'}; last
            started {when(j.last_started_at)}
            {j.last_status ? `, ${j.last_status}` : ''}
          </li>
        ))}
      </ul>
      <h3>Not recorded anywhere yet</h3>
      <ul>
        {data.not_recorded.map((t) => (
          <li key={t}>{t}</li>
        ))}
      </ul>
    </div>
  )
}

export default function AdminModels({ call, onExpired }: { call: AdminCall; onExpired: () => void }) {
  const [data, setData] = useState<ModelOverview | null>(null)
  const [error, setError] = useState<unknown>(null)
  const load = useCallback(() => {
    call<ModelOverview>('/admin/console/models')
      .then(setData)
      .catch((e: { code?: string | null }) => (e.code === 'mfa_required' ? onExpired() : setError(e)))
  }, [call, onExpired])
  useEffect(load, [load])
  if (error != null) return <ErrorBox error={error} />
  if (data === null) return <Loading label="Loading the models…" />
  return <ModelOverviewView data={data} />
}
