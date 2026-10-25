// Admin > Invites (owner only): people who asked for a place in the trial. Approve makes a one-time sign-up
// link that the owner sends by hand (there is no email service); Reject refuses a request or withdraws an
// approved link nobody has used. The server checks the owner on every call; this page only shows the list.
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { api } from '../../api/client'
import { Confirm } from '../Confirm'
import {
  countWaiting,
  experienceLabel,
  inviteLink,
  inviteState,
  languageLabel,
  type InviteDecision,
  type InviteRequestRow,
} from '../invites'
import { Card, PageHead, Tag } from '../ui'

type Dialog = { kind: 'approve' | 'reject' | 'new-code'; row: InviteRequestRow }

const TONE = { wait: 'amber', ok: 'blue', off: 'red', done: 'green' } as const

function when(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Kolkata' })
}

export default function Invites() {
  const queryClient = useQueryClient()
  const q = useQuery({ queryKey: ['admin-invites'], queryFn: api.adminInvites })
  const [dialog, setDialog] = useState<Dialog | null>(null)
  const [link, setLink] = useState<{ name: string; email: string; url: string } | null>(null)
  const [copied, setCopied] = useState(false)
  const rows = q.data ?? []

  function showLink(d: InviteDecision) {
    setCopied(false)
    setLink({ name: d.name, email: d.email, url: inviteLink(window.location.origin, d.signup_path) })
  }
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['admin-invites'] })

  async function copy() {
    if (!link) return
    try {
      await navigator.clipboard.writeText(link.url)
      setCopied(true)
    } catch {
      setCopied(false)
    }
  }

  return (
    <div className="tm-page tm-grid">
      <PageHead
        title="Invites"
        sub="People who asked to join the trial. Only approved people can make an account; sign-up stays closed to everyone else."
      />

      {link && (
        <Card glow="green" title={`Sign-up link for ${link.name}`} sub="Shown once. Send it to them yourself: nothing is emailed automatically.">
          <p className="tm-dim" style={{ marginTop: 0 }}>
            It works once, only with <b>{link.email}</b>. If it gets lost, use “New link” on their row.
          </p>
          <input className="tm-input" style={{ width: '100%' }} readOnly value={link.url} onFocus={(e) => e.target.select()} aria-label="Sign-up link" data-testid="invite-link" />
          <div className="tm-flex" style={{ gap: '0.5rem', marginTop: '0.6rem' }}>
            <button className="tm-btn" onClick={copy}>
              {copied ? 'Copied' : 'Copy link'}
            </button>
            <button className="tm-btn tm-btn-ghost" onClick={() => setLink(null)}>
              Done
            </button>
          </div>
        </Card>
      )}

      {q.isLoading && <p className="tm-dim">Loading…</p>}
      {q.isError && <p className="tm-neg">Could not load the invite requests. Try again shortly.</p>}

      {q.data && (
        <Card
          title={`${rows.length} request${rows.length === 1 ? '' : 's'}`}
          sub={countWaiting(rows) ? `${countWaiting(rows)} waiting for your answer.` : 'Nobody is waiting for an answer.'}
        >
          {rows.length === 0 ? (
            <p className="tm-dim">Nobody has asked yet. The front page has an “Ask for an invite” form.</p>
          ) : (
            <div className="tm-table-wrap" tabIndex={0} role="region" aria-label="Table, scroll sideways to see more">
              <table className="tm-table" data-testid="invites-table">
                <thead>
                  <tr>
                    <th>Person</th>
                    <th>Trades</th>
                    <th>Language</th>
                    <th>Asked</th>
                    <th>Where it stands</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => {
                    const state = inviteState(r)
                    return (
                      <tr key={r.id}>
                        <td>
                          <div className="tm-strong">{r.name}</div>
                          <div className="tm-dim" style={{ fontSize: '0.8rem' }}>
                            {r.email}
                            {r.phone ? ` · ${r.phone}` : ''}
                          </div>
                          {r.has_account && r.status !== 'approved' && (
                            <div className="tm-dim" style={{ fontSize: '0.75rem' }}>
                              Already has an account
                            </div>
                          )}
                        </td>
                        <td>{experienceLabel(r.experience)}</td>
                        <td>{languageLabel(r.language)}</td>
                        <td>{when(r.created_at)}</td>
                        <td>
                          <Tag tone={TONE[state.tone]}>{state.text}</Tag>
                          {r.decided_by && (
                            <div className="tm-dim" style={{ fontSize: '0.75rem' }}>
                              by {r.decided_by}, {when(r.decided_at)}
                              {r.note ? ` · ${r.note}` : ''}
                            </div>
                          )}
                        </td>
                        <td style={{ whiteSpace: 'nowrap' }}>
                          {r.status === 'pending' && (
                            <>
                              <button className="tm-btn" onClick={() => setDialog({ kind: 'approve', row: r })}>
                                Approve
                              </button>{' '}
                              <button className="tm-btn tm-btn-ghost" onClick={() => setDialog({ kind: 'reject', row: r })}>
                                Reject
                              </button>
                            </>
                          )}
                          {r.status === 'approved' && !r.used && (
                            <>
                              <button className="tm-btn tm-btn-ghost" onClick={() => setDialog({ kind: 'new-code', row: r })}>
                                New link
                              </button>{' '}
                              <button className="tm-btn tm-btn-ghost" onClick={() => setDialog({ kind: 'reject', row: r })}>
                                Withdraw
                              </button>
                            </>
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}

      {dialog?.kind === 'approve' && (
        <Confirm
          title={`Approve ${dialog.row.name}?`}
          confirmLabel="Approve"
          reason={{ label: 'A note for yourself (optional)', placeholder: 'For example: friend of Vijay', required: false }}
          onConfirm={async (note) => {
            showLink(await api.approveInvite(dialog.row.id, note))
            refresh()
          }}
          onClose={() => setDialog(null)}
        >
          This makes a one-time sign-up link for {dialog.row.email}. You send it to them yourself. Their account will
          be an ordinary one: paper money only, no Admin, no real account.
        </Confirm>
      )}
      {dialog?.kind === 'new-code' && (
        <Confirm
          title={`New link for ${dialog.row.name}?`}
          confirmLabel="Make a new link"
          onConfirm={async () => {
            showLink(await api.newInviteCode(dialog.row.id))
            refresh()
          }}
          onClose={() => setDialog(null)}
        >
          The old link stops working and a new one is shown once.
        </Confirm>
      )}
      {dialog?.kind === 'reject' && (
        <Confirm
          title={dialog.row.status === 'approved' ? `Withdraw ${dialog.row.name}'s invite?` : `Reject ${dialog.row.name}?`}
          confirmLabel={dialog.row.status === 'approved' ? 'Withdraw' : 'Reject'}
          danger
          reason={{ label: 'A note for yourself (optional)', required: false }}
          onConfirm={async (note) => {
            await api.rejectInvite(dialog.row.id, note)
            refresh()
          }}
          onClose={() => setDialog(null)}
        >
          {dialog.row.status === 'approved'
            ? 'Their sign-up link stops working. Nothing is sent to them.'
            : 'Nothing is sent to them. They can ask again later.'}
        </Confirm>
      )}
    </div>
  )
}
