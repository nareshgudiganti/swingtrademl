import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, ApiError } from '../api/client'
import type { RegistryEvidenceItem, RegistryModel, RegistrySlot, RegistrySlots } from '../api/types'
import { Empty, ErrorBox, Loading } from '../components/Loading'
import { formatDate } from '../lib/format'
import { useIsOwner } from '../lib/plan'

// Model registry, phase 1 (owner only). It shows the nine model slots and what the app already knows about each
// model. The only thing it can change is a slot's research priority, label and note. Saving those does not train,
// activate or switch anything, and nothing else in the app reads them.

const TIER_LABEL: Record<string, string> = { large: 'Large cap', midcap: 'Mid cap', smallcap: 'Small cap' }
const TIERS = ['large', 'midcap', 'smallcap']
const HORIZONS = [15, 10, 5]
const STATUS_LABEL: Record<string, string> = {
  not_started: 'Not started',
  researching: 'Researching',
  paused: 'Paused',
  dropped: 'Dropped',
}

/** A metric nobody measured says so in words. It is never shown as zero. */
export function metricText(item: RegistryEvidenceItem, digits = 3): string {
  if (item.value === null || item.value === undefined) return item.note ?? 'Not measured'
  return item.value.toFixed(digits)
}

function strategiesText(m: RegistryModel): string {
  if (m.active_strategies === null) return 'Unknown (strategies could not be read)'
  if (m.active_strategies.length === 0) return 'None. No switched-on strategy names this model.'
  return m.active_strategies.map((s) => `${s.strategy} (${s.mode}, ${s.execution_mode})`).join(', ')
}

function ModelBlock({ m, forward }: { m: RegistryModel; forward: string | null }) {
  const p = m.provenance
  const h = m.evidence.historical
  return (
    <div style={{ borderTop: '1px solid var(--border, #ddd)', paddingTop: 8, marginTop: 8, fontSize: 13 }}>
      <div>
        <strong>
          #{p.model_id} {p.name} {p.version}
        </strong>{' '}
        <span className="badge badge-off">Registry status: {m.registry_status}</span>
      </div>
      <div className="muted">
        Asks: reach +{((p.target_return_pct ?? 0) * 100).toFixed(0)}% within {p.horizon_days} days
        {p.stop_return_pct ? ` before −${(p.stop_return_pct * 100).toFixed(0)}%` : ''} · {p.label_kind ?? 'Unknown'}
      </div>
      <dl style={{ margin: '6px 0', display: 'grid', gridTemplateColumns: 'minmax(120px,170px) 1fr', gap: '2px 10px' }}>
        <dt className="muted">Used by strategies</dt>
        <dd style={{ margin: 0 }}>{strategiesText(m)}</dd>
        <dt className="muted">Inputs</dt>
        <dd style={{ margin: 0 }}>
          {p.n_inputs ?? 'Unknown'}
          {p.inputs_fingerprint ? ` · list fingerprint ${p.inputs_fingerprint.slice(0, 10)}` : ''}
        </dd>
        <dt className="muted">Training stocks</dt>
        <dd style={{ margin: 0 }}>
          {p.n_training_symbols ?? 'Unknown'}
          {p.training_universe_fingerprint ? ` · fingerprint ${p.training_universe_fingerprint.slice(0, 10)}` : ''}
        </dd>
        <dt className="muted">Trained until</dt>
        <dd style={{ margin: 0 }}>{p.train_end ? formatDate(p.train_end) : 'Unknown'}</dd>
        <dt className="muted">Calibration</dt>
        <dd style={{ margin: 0 }}>{p.calibration}</dd>
        <dt className="muted">Model file fingerprint</dt>
        <dd style={{ margin: 0, overflowWrap: 'anywhere' }}>{p.model_file_fingerprint}</dd>
      </dl>
      <div>
        <div className="muted">Historical evidence</div>
        <ul style={{ margin: '2px 0 6px', paddingLeft: 18 }}>
          <li>
            {h.held_out_auc.label}: <strong>{metricText(h.held_out_auc)}</strong>
          </li>
          <li>
            {h.precision_at_threshold.label}: <strong>{metricText(h.precision_at_threshold)}</strong>
          </li>
          <li>
            {h.top5_ranking.label}: <strong>{metricText(h.top5_ranking)}</strong>
          </li>
          <li>
            {h.net_return_after_costs.label}: <strong>{metricText(h.net_return_after_costs)}</strong>
          </li>
          <li>
            {h.drawdown.label}: <strong>{metricText(h.drawdown)}</strong>
          </li>
        </ul>
        <div className="muted">Forward evidence (kept separate)</div>
        <div>{forward ?? 'Not measured: no forward test for this slot'}</div>
      </div>
    </div>
  )
}

function SlotCard({ slot, statuses, forward }: { slot: RegistrySlot; statuses: string[]; forward: string | null }) {
  const queryClient = useQueryClient()
  const [status, setStatus] = useState(slot.research_status)
  const [priority, setPriority] = useState(slot.priority === null ? '' : String(slot.priority))
  const [note, setNote] = useState(slot.note ?? '')
  const [message, setMessage] = useState<string | null>(null)

  const save = useMutation({
    mutationFn: () =>
      api.modelRegistryChange(slot.slot_key, {
        expected_version: slot.version,
        research_status: status,
        priority: priority === '' ? null : Number(priority),
        note: note.trim() === '' ? null : note,
      }),
    onSuccess: () => {
      setMessage('Saved. Nothing was started or switched.')
      void queryClient.invalidateQueries({ queryKey: ['modelRegistry'] })
    },
    onError: (err) => {
      if (err instanceof ApiError && err.status === 409) {
        setMessage('Someone else changed this slot. The latest values are loaded; check them and save again.')
        void queryClient.invalidateQueries({ queryKey: ['modelRegistry'] })
      } else {
        setMessage(err instanceof Error ? err.message : 'Could not save.')
      }
    },
  })

  return (
    <div className="card" style={{ minWidth: 0 }}>
      <div className="between" style={{ gap: 8, flexWrap: 'wrap' }}>
        <strong>
          {slot.horizon_days}-day · {TIER_LABEL[slot.cap_tier] ?? slot.cap_tier}
        </strong>
        <span className="badge badge-on">{slot.priority === null ? 'Unranked' : `Priority ${slot.priority}`}</span>
      </div>
      <div className="muted" style={{ fontSize: 12 }}>
        Order {slot.rank} of 9 · {slot.models.length === 0 ? 'no model yet' : `${slot.models.length} model version(s)`}
      </div>
      <div style={{ display: 'grid', gap: 6, marginTop: 8 }}>
        <label htmlFor={`status-${slot.slot_key}`} className="muted" style={{ fontSize: 12 }}>
          Research status (a label only)
        </label>
        <select id={`status-${slot.slot_key}`} value={status} onChange={(e) => setStatus(e.target.value)}>
          {statuses.map((s) => (
            <option key={s} value={s}>
              {STATUS_LABEL[s] ?? s}
            </option>
          ))}
        </select>
        <label htmlFor={`priority-${slot.slot_key}`} className="muted" style={{ fontSize: 12 }}>
          Research priority (1 = first)
        </label>
        <select id={`priority-${slot.slot_key}`} value={priority} onChange={(e) => setPriority(e.target.value)}>
          <option value="">Unranked</option>
          {[1, 2, 3, 4, 5, 6, 7, 8, 9].map((n) => (
            <option key={n} value={n}>
              {n}
            </option>
          ))}
        </select>
        <label htmlFor={`note-${slot.slot_key}`} className="muted" style={{ fontSize: 12 }}>
          Note
        </label>
        <textarea
          id={`note-${slot.slot_key}`}
          rows={2}
          maxLength={2000}
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
        <button type="button" onClick={() => save.mutate()} disabled={save.isPending}>
          {save.isPending ? 'Saving…' : 'Save research notes'}
        </button>
        <div className="muted" style={{ fontSize: 12 }}>
          Saving does not start training, activate a model or change any trading.
          {slot.updated_by ? ` Last changed by ${slot.updated_by}${slot.updated_at ? ` on ${formatDate(slot.updated_at)}` : ''}.` : ''}
        </div>
        {message && <div className="banner banner-warn">{message}</div>}
      </div>
      {slot.models.map((m) => (
        <ModelBlock key={m.provenance.model_id} m={m} forward={slot.horizon_days === 5 ? forward : null} />
      ))}
    </div>
  )
}

/** The board itself: pure display of what the API returned, plus the per-slot research controls. */
export function RegistryBoard({ data, forward }: { data: RegistrySlots; forward: string | null }) {
  const byKey = new Map(data.slots.map((s) => [s.slot_key, s]))
  return (
    <div style={{ display: 'grid', gap: 16 }}>
      <div className="banner banner-warn">
        {data.status_note} Only the owner sees this page. It does not train or activate anything, and the brain and the
        trading bot do not read it.
      </div>
      <div className="muted" style={{ fontSize: 13 }}>
        Order: {data.ordering}.
      </div>
      {HORIZONS.map((h) => (
        <div
          key={h}
          style={{ display: 'grid', gap: 12, gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))' }}
        >
          {TIERS.map((t) => {
            const slot = byKey.get(`${h}d-${t}`)
            return slot ? (
              <SlotCard
                key={`${slot.slot_key}:${slot.version}`}
                slot={slot}
                statuses={data.statuses}
                forward={forward}
              />
            ) : null
          })}
        </div>
      ))}
      <section>
        <h3 style={{ marginBottom: 4 }}>Unassigned models (read only)</h3>
        <p className="muted" style={{ marginTop: 0 }}>
          Models whose name or horizon is not on the verified list. They are never guessed into a size group.
        </p>
        {data.unassigned.length === 0 ? (
          <Empty label="No unassigned models." />
        ) : (
          <div className="card">
            {data.unassigned.map((m) => (
              <ModelBlock key={m.provenance.model_id} m={m} forward={null} />
            ))}
          </div>
        )}
      </section>
    </div>
  )
}

/** One honest line about the 5-day test; never invents a verdict. */
export function forwardText(report: { runs: unknown[]; verdict?: { state?: string } } | undefined): string | null {
  if (!report) return null
  if (!report.runs || report.runs.length === 0) return 'Not measured yet: the 5-day test has not recorded a run.'
  return `5-day test (see its own report for details): ${report.verdict?.state ?? 'no verdict yet'}`
}

function OwnerGate({ children }: { children: React.ReactNode }) {
  const { isOwner, loading } = useIsOwner()
  if (loading) return <Loading label="Checking owner access…" />
  if (!isOwner) {
    return (
      <div className="card">
        <h2 style={{ marginTop: 0 }}>Owner access required</h2>
        <p>The model registry is visible to the app owner only.</p>
      </div>
    )
  }
  return <>{children}</>
}

function Loaded() {
  const registry = useQuery({ queryKey: ['modelRegistry'], queryFn: api.modelRegistrySlots })
  const h05 = useQuery({ queryKey: ['h05Report'], queryFn: api.h05Report, retry: false })
  if (registry.isLoading) return <Loading label="Loading the model registry…" />
  if (registry.error) return <ErrorBox error={registry.error} />
  if (!registry.data) return <Empty label="Nothing to show." />
  return <RegistryBoard data={registry.data} forward={h05.isError ? 'Not available right now' : forwardText(h05.data)} />
}

export default function ModelRegistry() {
  return (
    <div style={{ display: 'grid', gap: 12 }}>
      <div>
        <h2 style={{ marginBottom: 2 }}>Model registry</h2>
        <p className="muted" style={{ marginTop: 0 }}>
          Nine slots: 5, 10 and 15 trading days across large, mid and small caps. Nine is the most, not a target.
        </p>
      </div>
      <OwnerGate>
        <Loaded />
      </OwnerGate>
    </div>
  )
}
