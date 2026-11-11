import { useCallback, useEffect, useState } from 'react'

import { BASE_URL, getToken } from '../api/client'
import { Empty, ErrorBox, Loading } from '../components/Loading'
import { formatDate } from '../lib/format'
import { useIsOwner } from '../lib/plan'

// Admin only: people, Free/Pro, gifts, the change log and the release switches.
// The second-step token is kept in memory only (gone on refresh, ends after 15 minutes).

export type AdminUserRow = {
  id: number
  username: string
  email: string | null
  full_name: string | null
  role: string
  is_active: boolean
  email_verified: boolean
  stored_plan: string
  effective_plan: string
  subscription_status: string | null
  subscription_ends_at: string | null
  grant_expires_at: string | null
  has_active_grant: boolean
  last_login_at: string | null
}
type AuditRow = { id: number; ts: string; actor: string; action: string; target_id: string | null }
type Switch = { key: string; label: string; enabled: boolean }
type Tab = 'users' | 'audit' | 'switches'

class AdminError extends Error {
  code: string | null
  status: number
  constructor(message: string, status: number, code: string | null) {
    super(message)
    this.status = status
    this.code = code
  }
}

async function adminCall<T>(path: string, init: RequestInit = {}, stepUp = ''): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${getToken()}`,
      ...(stepUp ? { 'X-Admin-Mfa': stepUp } : {}),
    },
  })
  if (!response.ok) {
    let message = response.statusText
    let code: string | null = null
    try {
      const body = await response.json()
      if (typeof body.detail === 'string') message = body.detail
      else if (body.detail?.message) {
        message = body.detail.message
        code = body.detail.code ?? null
      }
    } catch {
      /* keep the status line */
    }
    throw new AdminError(message, response.status, code)
  }
  return (await response.json()) as T
}

const ACTION_LABEL: Record<string, string> = {
  'user.plan_change': 'Changed a plan',
  'plan.grant': 'Gave free Pro',
  'plan.grant_revoke': 'Took back free Pro',
  'admin.mfa_enabled': 'Turned on two-step sign-in',
  'admin.mfa_verified': 'Entered a two-step code',
  'admin.mfa_recovery_used': 'Used a recovery code',
  'admin.mfa_failed': 'Wrong two-step code',
  'admin.mfa_setup': 'Started two-step setup',
}

export function planText(u: Pick<AdminUserRow, 'stored_plan' | 'effective_plan' | 'has_active_grant' | 'subscription_status'>): string {
  if (u.stored_plan === 'pro') return 'Pro (set by admin)'
  if (u.has_active_grant) return 'Pro (free gift)'
  if (u.effective_plan === 'pro') return 'Pro (paid)'
  return 'Free'
}

export function SecondStep({ onToken }: { onToken: (token: string) => void }) {
  const [code, setCode] = useState('')
  const [useRecovery, setUseRecovery] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  async function submit() {
    setBusy(true)
    setError(null)
    try {
      const body = useRecovery ? { recovery_code: code } : { code }
      const r = await adminCall<{ step_up_token: string }>('/admin/mfa/verify', {
        method: 'POST',
        body: JSON.stringify(body),
      })
      onToken(r.step_up_token)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not check the code')
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="card" style={{ maxWidth: 420 }}>
      <h2 style={{ marginTop: 0 }}>Enter your two-step code</h2>
      <p>{useRecovery ? 'Type one of your saved recovery codes. Each works once.' : 'Open your authenticator app and type the 6 digits.'}</p>
      <input
        aria-label={useRecovery ? 'Recovery code' : 'Six-digit code'}
        value={code}
        onChange={(e) => setCode(e.target.value)}
        inputMode={useRecovery ? 'text' : 'numeric'}
        autoComplete="one-time-code"
        maxLength={useRecovery ? 24 : 6}
      />
      <div style={{ marginTop: 12, display: 'flex', gap: 12, alignItems: 'center' }}>
        <button className="btn" onClick={submit} disabled={busy || !code.trim()}>
          {busy ? 'Checking…' : 'Continue'}
        </button>
        <button className="btn-link" onClick={() => { setUseRecovery(!useRecovery); setCode(''); setError(null) }}>
          {useRecovery ? 'Use my authenticator app' : 'Use a recovery code'}
        </button>
      </div>
      {error && <div className="banner banner-warn" style={{ marginTop: 12 }}>{error}</div>}
    </div>
  )
}

export function Enrol({ onDone }: { onDone: (token: string) => void }) {
  const [setup, setSetup] = useState<{ secret: string; otpauth_uri: string } | null>(null)
  const [code, setCode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState<{ codes: string[]; token: string } | null>(null)
  const [saved, setSaved] = useState(false)

  async function start() {
    setError(null)
    try {
      setSetup(await adminCall('/admin/mfa/setup', { method: 'POST' }))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not start setup')
    }
  }
  async function enable() {
    setError(null)
    try {
      const r = await adminCall<{ recovery_codes: string[]; step_up_token: string }>('/admin/mfa/enable', {
        method: 'POST',
        body: JSON.stringify({ code }),
      })
      setDone({ codes: r.recovery_codes, token: r.step_up_token })
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not turn it on')
    }
  }

  if (done) {
    return (
      <div className="card" style={{ maxWidth: 460 }}>
        <h2 style={{ marginTop: 0 }}>Two-step sign-in is on</h2>
        <p>Save these recovery codes somewhere safe. They are shown only now. Each one works once if you lose your phone.</p>
        <pre aria-label="Recovery codes">{done.codes.join('\n')}</pre>
        <label style={{ display: 'block', margin: '12px 0' }}>
          <input type="checkbox" checked={saved} onChange={(e) => setSaved(e.target.checked)} /> I saved them
        </label>
        <button className="btn" disabled={!saved} onClick={() => onDone(done.token)}>
          Open the admin screen
        </button>
      </div>
    )
  }
  return (
    <div className="card" style={{ maxWidth: 460 }}>
      <h2 style={{ marginTop: 0 }}>Set up two-step sign-in</h2>
      <p>The admin screen can change who pays and who sees what, so it asks for a code from your phone each time.</p>
      {!setup ? (
        <button className="btn" onClick={start}>Start setup</button>
      ) : (
        <>
          <p>In an authenticator app, add an account by typing this key:</p>
          <pre aria-label="Setup key">{setup.secret}</pre>
          <p>Then type the 6 digits the app shows.</p>
          <input aria-label="Six-digit code" value={code} onChange={(e) => setCode(e.target.value)} inputMode="numeric" maxLength={6} />
          <div style={{ marginTop: 12 }}>
            <button className="btn" onClick={enable} disabled={code.trim().length !== 6}>Turn on</button>
          </div>
        </>
      )}
      {error && <div className="banner banner-warn" style={{ marginTop: 12 }}>{error}</div>}
    </div>
  )
}

function Users({ token, onExpired }: { token: string; onExpired: () => void }) {
  const [q, setQ] = useState('')
  const [rows, setRows] = useState<AdminUserRow[] | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [note, setNote] = useState<string | null>(null)
  const [giftFor, setGiftFor] = useState<AdminUserRow | null>(null)
  const [reason, setReason] = useState('')
  const [days, setDays] = useState('30')

  const guard = useCallback(
    (e: unknown) => {
      if (e instanceof AdminError && e.code === 'mfa_required') onExpired()
      else setError(e)
    },
    [onExpired],
  )
  const load = useCallback(async () => {
    try {
      const r = await adminCall<{ users: AdminUserRow[] }>(
        `/admin/console/users?q=${encodeURIComponent(q)}&limit=100`,
        {},
        token,
      )
      setRows(r.users)
      setError(null)
    } catch (e) {
      guard(e)
    }
  }, [q, token, guard])
  useEffect(() => {
    void load()
  }, [load])

  async function setPlan(u: AdminUserRow, plan: 'free' | 'pro') {
    const who = u.email ?? u.username
    if (!window.confirm(`Change ${who} to ${plan === 'pro' ? 'Pro' : 'Free'}?`)) return
    try {
      await adminCall(`/admin/console/users/${u.id}/plan`, { method: 'PUT', body: JSON.stringify({ plan }) }, token)
      setNote(`${who} is now ${plan === 'pro' ? 'Pro' : 'Free'} (set by admin).`)
      await load()
    } catch (e) {
      guard(e)
    }
  }
  async function gift() {
    if (!giftFor) return
    const n = Number(days)
    const body: Record<string, unknown> = { reason }
    if (n > 0) body.expires_at = new Date(Date.now() + n * 86_400_000).toISOString()
    try {
      await adminCall(`/admin/console/users/${giftFor.id}/grants`, { method: 'POST', body: JSON.stringify(body) }, token)
      setNote(`Gave ${giftFor.email ?? giftFor.username} free Pro${n > 0 ? ` for ${n} days` : ' with no end date'}.`)
      setGiftFor(null)
      setReason('')
      await load()
    } catch (e) {
      guard(e)
    }
  }

  return (
    <div>
      <input aria-label="Search people" placeholder="Search by name or email" value={q} onChange={(e) => setQ(e.target.value)} />
      {note && <div className="banner" role="status" style={{ marginTop: 12 }}>{note}</div>}
      {error != null && <ErrorBox error={error} />}
      {rows === null && error == null && <Loading label="Loading people…" />}
      {rows !== null && rows.length === 0 && <Empty label="No one matches." />}
      {rows !== null && rows.length > 0 && (
        <div style={{ overflowX: 'auto', marginTop: 12 }}>
          <table className="table">
            <thead>
              <tr>
                <th>Person</th><th>Email checked</th><th>Plan</th><th>Subscription</th><th>Last sign-in</th><th />
              </tr>
            </thead>
            <tbody>
              {rows.map((u) => (
                <tr key={u.id}>
                  <td>{u.full_name ?? u.username}<br /><small>{u.email ?? u.username}</small></td>
                  <td>{u.email_verified ? 'Yes' : 'No'}</td>
                  <td>
                    {planText(u)}
                    {u.has_active_grant && u.grant_expires_at && <><br /><small>until {formatDate(u.grant_expires_at)}</small></>}
                  </td>
                  <td>
                    {u.subscription_status ?? '—'}
                    {u.subscription_ends_at && <><br /><small>ends {formatDate(u.subscription_ends_at)}</small></>}
                  </td>
                  <td>{u.last_login_at ? formatDate(u.last_login_at) : 'Never'}</td>
                  <td>
                    {u.role === 'owner' ? (
                      <small>Admin</small>
                    ) : (
                      <>
                        <button className="btn-link" onClick={() => setPlan(u, u.stored_plan === 'pro' ? 'free' : 'pro')}>
                          {u.stored_plan === 'pro' ? 'Make Free' : 'Make Pro'}
                        </button>{' '}
                        <button className="btn-link" onClick={() => setGiftFor(u)}>Give free Pro</button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {giftFor && (
        <div className="card" style={{ marginTop: 12, maxWidth: 460 }}>
          <h3 style={{ marginTop: 0 }}>Give free Pro to {giftFor.email ?? giftFor.username}</h3>
          <label>Why (kept in the change log)
            <input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} />
          </label>
          <label style={{ display: 'block', marginTop: 8 }}>For how many days (0 = no end date)
            <input value={days} onChange={(e) => setDays(e.target.value)} inputMode="numeric" />
          </label>
          <div style={{ marginTop: 12, display: 'flex', gap: 12 }}>
            <button className="btn" onClick={gift} disabled={reason.trim().length < 3}>Give Pro</button>
            <button className="btn-link" onClick={() => setGiftFor(null)}>Cancel</button>
          </div>
        </div>
      )}
    </div>
  )
}

function Audit({ token, onExpired }: { token: string; onExpired: () => void }) {
  const [rows, setRows] = useState<AuditRow[] | null>(null)
  const [error, setError] = useState<unknown>(null)
  useEffect(() => {
    adminCall<AuditRow[]>('/admin/console/audit?limit=100', {}, token)
      .then(setRows)
      .catch((e) => (e instanceof AdminError && e.code === 'mfa_required' ? onExpired() : setError(e)))
  }, [token, onExpired])
  if (error != null) return <ErrorBox error={error} />
  if (rows === null) return <Loading label="Loading the change log…" />
  if (rows.length === 0) return <Empty label="Nothing recorded yet." />
  return (
    <table className="table">
      <thead><tr><th>When</th><th>Who</th><th>What</th></tr></thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.id}>
            <td>{formatDate(r.ts)}</td>
            <td>{r.actor}</td>
            <td>{ACTION_LABEL[r.action] ?? r.action}{r.target_id ? ` (person ${r.target_id})` : ''}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function Switches({ token, onExpired }: { token: string; onExpired: () => void }) {
  const [rows, setRows] = useState<Switch[] | null>(null)
  const [error, setError] = useState<unknown>(null)
  useEffect(() => {
    adminCall<{ switches: Switch[] }>('/admin/console/release-switches', {}, token)
      .then((r) => setRows(r.switches))
      .catch((e) => (e instanceof AdminError && e.code === 'mfa_required' ? onExpired() : setError(e)))
  }, [token, onExpired])
  if (error != null) return <ErrorBox error={error} />
  if (rows === null) return <Loading label="Loading switches…" />
  return (
    <div>
      <p>These are read-only here. They are changed on the server, never from this screen.</p>
      <ul>
        {rows.map((s) => (
          <li key={s.key}>{s.label}: <strong>{s.enabled ? 'ON' : 'off'}</strong></li>
        ))}
      </ul>
    </div>
  )
}

export default function AdminUsers() {
  const { isOwner, loading } = useIsOwner()
  const [enrolled, setEnrolled] = useState<boolean | null>(null)
  const [token, setToken] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [tab, setTab] = useState<Tab>('users')
  const expired = useCallback(() => setToken(''), [])

  useEffect(() => {
    if (!isOwner) return
    adminCall<{ enrolled: boolean }>('/admin/mfa')
      .then((r) => setEnrolled(r.enrolled))
      .catch(setError)
  }, [isOwner])

  if (loading) return <Loading label="Checking access…" />
  if (!isOwner) {
    return (
      <div className="card">
        <h2 style={{ marginTop: 0 }}>Admin access required</h2>
        <p>This screen is only for the admin.</p>
      </div>
    )
  }
  if (error != null) return <ErrorBox error={error} />
  if (enrolled === null) return <Loading label="Checking two-step sign-in…" />
  if (!enrolled) return <Enrol onDone={(t) => { setEnrolled(true); setToken(t) }} />
  if (!token) return <SecondStep onToken={setToken} />

  return (
    <div>
      <h1>Admin</h1>
      <div role="tablist" style={{ display: 'flex', gap: 12, marginBottom: 12 }}>
        {(['users', 'audit', 'switches'] as Tab[]).map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? 'btn' : 'btn-link'} onClick={() => setTab(t)}>
            {t === 'users' ? 'People' : t === 'audit' ? 'Change log' : 'Release switches'}
          </button>
        ))}
      </div>
      {tab === 'users' && <Users token={token} onExpired={expired} />}
      {tab === 'audit' && <Audit token={token} onExpired={expired} />}
      {tab === 'switches' && <Switches token={token} onExpired={expired} />}
    </div>
  )
}
