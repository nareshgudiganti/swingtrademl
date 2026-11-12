// "Delete my account" on the Account page. It shows where the person's request stands right now (nothing asked,
// link emailed, set to be deleted on a date, or cancelled) because the server's answer is the only truth.
// Asking needs the password (Google accounts have none, so they confirm by email only). Nothing is deleted
// until the person opens the emailed link; that page is auth/DeletionLinks.tsx.
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { ApiError, api } from '../api/client'
import { deletionErrorText, deletionView } from '../lib/deletionRules'
import { Confirm } from './Confirm'

function errText(err: unknown): string {
  if (err instanceof ApiError) return deletionErrorText(err.status, err.message)
  return 'Something went wrong. Please try again.'
}

/** Save the person's own data as a file. The server builds it; this only hands it to the browser. */
function saveJson(data: unknown) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'my-trademind-data.json'
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

export default function DeleteAccount({ usesPassword }: { usesPassword: boolean }) {
  const qc = useQueryClient()
  const status = useQuery({
    queryKey: ['account-deletion'],
    queryFn: api.deletionStatus,
    retry: false,
    // Nothing to poll: the status changes when the person opens an email link.
    staleTime: 0,
  })
  const [asking, setAsking] = useState(false)
  const [password, setPassword] = useState('')
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const exporter = useMutation({
    mutationFn: api.exportMyData,
    onSuccess: (data) => {
      setError(null)
      saveJson(data)
      setNotice('Your data has been saved to a file.')
    },
    onError: (err) => setError(errText(err)),
  })

  if (status.isLoading) {
    return (
      <div className="tm-card" data-testid="delete-account">
        <p className="tm-dim" role="status">
          Loading…
        </p>
      </div>
    )
  }
  if (status.isError) {
    const code = status.error instanceof ApiError ? status.error.status : 0
    // A person with no right to this (the shared key) sees nothing. A switched-off server says so plainly.
    if (code === 403) return null
    return (
      <div className="tm-card" data-testid="delete-account" data-state={code === 404 ? 'off' : 'error'}>
        <div className="tm-card-head">
          <span className="tm-card-title">Delete my account</span>
        </div>
        {code === 404 ? (
          <p className="tm-dim">Deleting an account is not open yet.</p>
        ) : (
          <p className="tm-state-error" role="alert">
            We could not check this just now. Please refresh the page.
          </p>
        )}
      </div>
    )
  }

  if (!status.data) return null
  const data = status.data
  const view = deletionView(data)

  async function ask() {
    try {
      const r = await api.requestDeletion(usesPassword ? password : null)
      setNotice(r.message)
      setPassword('')
      void qc.invalidateQueries({ queryKey: ['account-deletion'] })
    } catch (err) {
      throw new Error(errText(err))
    }
  }

  return (
    <div className="tm-card" data-testid="delete-account" data-state={view.state}>
      <div className="tm-card-head">
        <span className="tm-card-title">Your data</span>
      </div>
      <p className="tm-strong" data-testid="deletion-headline">
        {view.headline}
      </p>
      <p className="tm-dim">{view.detail}</p>

      {view.canRequest && (
        <button
          type="button"
          className="tm-btn tm-btn-ghost"
          onClick={() => {
            setError(null)
            setNotice(null)
            setAsking(true)
          }}
          data-testid="deletion-request"
        >
          {view.requestLabel}
        </button>
      )}
      <button
        type="button"
        className="tm-btn tm-btn-ghost"
        disabled={exporter.isPending}
        onClick={() => exporter.mutate()}
        data-testid="export-data"
      >
        {exporter.isPending ? 'Preparing…' : 'Download my data'}
      </button>

      {notice && (
        <p className="tm-dim" role="status" data-testid="deletion-notice">
          {notice}
        </p>
      )}
      {error && (
        <p className="tm-state-error" role="alert">
          {error}
        </p>
      )}

      {asking && (
        <Confirm
          title="Delete my account?"
          confirmLabel="Email me the confirm link"
          danger
          onConfirm={ask}
          onClose={() => {
            setAsking(false)
            setPassword('')
          }}
        >
          <p>
            We will email you a link. Nothing is deleted until you open it and confirm. After that you are signed out,
            any Pro plan is stopped, and you have {data.grace_days} days to change your mind.
          </p>
          {usesPassword ? (
            <label className="tm-field">
              <span>Your password, to show it is you</span>
              <input
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                data-testid="deletion-password"
              />
            </label>
          ) : (
            <p className="tm-dim">You sign in with Google, so the email link is all we need.</p>
          )}
        </Confirm>
      )}
    </div>
  )
}
