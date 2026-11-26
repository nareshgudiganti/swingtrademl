import { useCallback, useEffect, useState } from 'react'

import { ErrorBox, Loading } from '../components/Loading'

// Admin only: switch the optional parts of the app on and off. The server decides who may; this screen only asks.
// Switching a part off never deletes anything: its screens and its scheduled work pause, its data stays.

export type ModuleRow = {
  id: string
  label: string
  core: boolean
  state: string
  enabled: boolean
  jobs: string[]
}
export type ModuleList = { modules: ModuleRow[]; scope: string; state_unknown: boolean }
/** The caller (the admin screen) sends the request with the two-step code; a failure carries status and code. */
export type AdminCall = <T>(path: string, init?: RequestInit) => Promise<T>
type Failure = { status?: number; code?: string | null; message?: string }

const WHAT_IT_DOES: Record<string, string> = {
  finance: 'Your money pages: spending, loans and net worth.',
  mutual_funds: 'Your mutual fund holdings and their prices.',
  brain: 'TradeMind reports and its nightly work. Its safety controls (stage, approvals) never switch off.',
  research_lanes: 'The research lanes that test other time horizons on paper.',
  'core.auth': 'Signing in and your account.',
  'core.safety': 'The safety limits and the stop switch.',
  'core.orders': 'Placing and tracking orders.',
  'core.health': 'Health checks and the status screen.',
}

/** Plain-English message for a refused change. Exported so the tests can pin each wording. */
export function refusalText(error: Failure): string {
  if (error.status === 409) {
    return `Not changed. ${error.message ?? 'Another part still depends on this one.'}`
  }
  if (error.status === 403) {
    return 'Not changed. Only the named owner, signed in with the two-step code, can switch parts of the app.'
  }
  if (error.status === 404) return 'Not changed. That part of the app no longer exists. Reload the page.'
  return 'Not changed. Something went wrong. Try again in a moment.'
}

/** Ask the server to switch one part. A reason is required; a refusal comes back as plain words. */
export async function submitSwitch(
  call: AdminCall,
  id: string,
  enabled: boolean,
  reason: string,
): Promise<{ ok: true } | { ok: false; message: string; expired?: boolean }> {
  if (id.startsWith('core.')) return { ok: false, message: 'That part is always on and cannot be switched.' }
  if (reason.trim().length < 3) return { ok: false, message: 'Say why first (a few words is enough).' }
  try {
    await call(`/admin/modules/${encodeURIComponent(id)}`, {
      method: 'PUT',
      body: JSON.stringify({ enabled, reason: reason.trim() }),
    })
    return { ok: true }
  } catch (e) {
    // The two-step code ran out: the screen goes back to the code prompt, like the other admin tabs.
    if ((e as Failure).code === 'mfa_required') return { ok: false, expired: true, message: '' }
    return { ok: false, message: refusalText(e as Failure) }
  }
}

export function summaryText(rows: ModuleRow[]): string {
  const off = rows.filter((m) => !m.core && !m.enabled)
  if (off.length === 0) return 'Everything is on.'
  return `${off.length} ${off.length === 1 ? 'part is' : 'parts are'} switched off: ${off.map((m) => m.label).join(', ')}.`
}

type RowProps = {
  m: ModuleRow
  call: AdminCall
  onChanged: () => void
  onExpired: () => void
  locked: boolean
}

function Row({ m, call, onChanged, onExpired, locked }: RowProps) {
  const [open, setOpen] = useState(false)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const turningOn = !m.enabled
  const reasonOk = reason.trim().length >= 3

  async function apply() {
    setBusy(true)
    setMessage('')
    const result = await submitSwitch(call, m.id, turningOn, reason)
    setBusy(false)
    if (result.ok) {
      setOpen(false)
      setReason('')
      onChanged()
    } else if (result.expired) {
      onExpired()
    } else {
      setMessage(result.message)
    }
  }

  return (
    <li className="card" style={{ marginBottom: 8 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
        <div>
          <strong>{m.label}</strong>
          <div>{WHAT_IT_DOES[m.id] ?? ''}</div>
        </div>
        <div>
          {m.core ? (
            <span>Always on</span>
          ) : (
            <>
              {!locked && <strong>{m.enabled ? 'On' : 'Off'}</strong>}{' '}
              {!open && (
                <button className="btn-link" disabled={locked} onClick={() => setOpen(true)}>
                  {m.enabled ? 'Switch off' : 'Switch on'}
                </button>
              )}
            </>
          )}
        </div>
      </div>
      {!m.core && open && (
        <div style={{ marginTop: 8 }}>
          <label>
            Why are you {turningOn ? 'switching this on' : 'switching this off'}?{' '}
            <input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={200} />
          </label>
          {!turningOn && <p>Nothing is deleted. Its pages stop answering and its scheduled work pauses until you switch it back on.</p>}
          <button className="btn" disabled={!reasonOk || busy} onClick={apply}>
            {turningOn ? 'Switch on' : 'Switch off'}
          </button>{' '}
          <button className="btn-link" onClick={() => { setOpen(false); setMessage('') }}>
            Cancel
          </button>
        </div>
      )}
      {message && <p role="alert">{message}</p>}
    </li>
  )
}

export default function AdminModules({ call, onExpired }: { call: AdminCall; onExpired: () => void }) {
  const [data, setData] = useState<ModuleList | null>(null)
  const [error, setError] = useState<unknown>(null)

  const load = useCallback(() => {
    call<ModuleList>('/admin/modules')
      .then(setData)
      .catch((e: Failure) => (e.code === 'mfa_required' ? onExpired() : setError(e)))
  }, [call, onExpired])
  useEffect(load, [load])

  if (error != null) return <ErrorBox error={error} />
  if (data === null) return <Loading label="Loading the parts of the app…" />
  return <ModuleListView data={data} call={call} onChanged={load} onExpired={onExpired} />
}

export function ModuleListView({
  data,
  call,
  onChanged,
  onExpired = () => {},
}: {
  data: ModuleList
  call: AdminCall
  onChanged: () => void
  onExpired?: () => void
}) {
  return (
    <div>
      <h2 style={{ marginTop: 0 }}>
        {data.state_unknown ? "Can't read the current switches right now." : summaryText(data.modules)}
      </h2>
      {data.state_unknown && (
        <p role="alert">
          Warning: the saved switches could not be read just now, so this list shows the normal settings and may not match what is
          running. Try again before changing anything.
        </p>
      )}
      <ul style={{ listStyle: 'none', padding: 0 }}>
        {data.modules.map((m) => (
          <Row key={m.id} m={m} call={call} onChanged={onChanged} onExpired={onExpired} locked={data.state_unknown} />
        ))}
      </ul>
    </div>
  )
}
