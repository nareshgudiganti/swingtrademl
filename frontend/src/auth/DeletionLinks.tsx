// The two links in the account-deletion emails. They work signed in or signed out (a person is signed out the
// moment they confirm), so App.tsx shows them before it asks who is signed in.
//  /confirm-deletion?token=...  "Yes, delete my account": asks for one more click, then starts the grace period.
//  /cancel-deletion?token=...   "Keep my account".
// Neither acts on page load: an email scanner that opens links must not be able to confirm or cancel for the person.
import { useEffect, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'

import { ApiError, api, clearToken } from '../api/client'
import { deletionErrorText, deletionLinkKind } from '../lib/deletionRules'
import { readEmailToken } from './authRules'
import { LinkPage } from './PublicSite'
import './newAuth.css'

type Phase = 'ready' | 'working' | 'done' | 'bad' | 'retry'

function errText(err: unknown): { text: string; retry: boolean } {
  if (err instanceof ApiError) return { text: deletionErrorText(err.status, err.message), retry: err.status === 502 }
  return { text: 'Something went wrong. Please try again.', retry: true }
}

export default function DeletionLink() {
  const location = useLocation()
  const kind = deletionLinkKind(location.pathname) ?? 'keep'
  const path = location.pathname.replace(/\/+$/, '')
  const [token] = useState(() => readEmailToken(location.search))
  const [phase, setPhase] = useState<Phase>(token ? 'ready' : 'bad')
  const [message, setMessage] = useState('')

  // Take the one-time token out of the address bar; this page keeps it in memory only.
  useEffect(() => {
    if (token) window.history.replaceState({}, '', path)
    document.title = kind === 'confirm' ? 'Delete your account · TradeMind' : 'Keep your account · TradeMind'
  }, [token, path, kind])

  async function go() {
    if (!token) return
    setPhase('working')
    try {
      if (kind === 'confirm') {
        const r = await api.confirmDeletion(token)
        clearToken() // the server has ended every session; do not leave a dead sign-in behind
        setMessage(r.message)
      } else {
        const r = await api.keepAccount(token)
        setMessage(r.message)
      }
      setPhase('done')
    } catch (err) {
      const e = errText(err)
      setMessage(e.text)
      setPhase(e.retry ? 'retry' : 'bad')
    }
  }

  if (kind === 'confirm') {
    return (
      <LinkPage label="Delete your account">
        {(phase === 'ready' || phase === 'working' || phase === 'retry') && (
          <>
            <h1 className="na-h1 na-h1-sm">Delete your account?</h1>
            <p className="na-body" data-testid="deletion-confirm-text">
              If you go ahead, you are signed out, any Pro plan is stopped, and your account is deleted after a few
              days. Until then the email we send you has a link to keep it.
            </p>
            {phase === 'retry' && (
              <p className="na-error" role="alert" data-testid="deletion-retry">
                {message}
              </p>
            )}
            <button type="button" className="na-btn na-go na-danger" disabled={phase === 'working'} onClick={go} data-testid="deletion-go">
              {phase === 'working' ? 'Please wait…' : 'Yes, delete my account'}
            </button>
            <p className="na-fine">
              Changed your mind? Just close this page. <Link to="/signin">Go to sign in</Link>
            </p>
          </>
        )}
        {phase === 'done' && (
          <>
            <h1 className="na-h1 na-h1-sm">Your account is set to be deleted</h1>
            <p className="na-body" data-testid="deletion-done">
              {message}
            </p>
          </>
        )}
        {phase === 'bad' && <BadLink message={message} token={token} />}
      </LinkPage>
    )
  }

  return (
    <LinkPage label="Keep your account">
      {(phase === 'ready' || phase === 'working' || phase === 'retry') && (
        <>
          <h1 className="na-h1 na-h1-sm">Keep your account?</h1>
          <p className="na-body">This cancels the deletion. Nothing is lost, and you can sign in again.</p>
          {phase === 'retry' && (
            <p className="na-error" role="alert">
              {message}
            </p>
          )}
          <button type="button" className="na-btn na-go" disabled={phase === 'working'} onClick={go} data-testid="keep-go">
            {phase === 'working' ? 'Please wait…' : 'Keep my account'}
          </button>
        </>
      )}
      {phase === 'done' && (
        <>
          <h1 className="na-h1 na-h1-sm">Your account is kept</h1>
          <p className="na-body" data-testid="keep-done">
            {message}
          </p>
          <Link to="/signin" className="na-btn na-go">
            Sign in
          </Link>
        </>
      )}
      {phase === 'bad' && <BadLink message={message} token={token} />}
    </LinkPage>
  )
}

function BadLink({ message, token }: { message: string; token: string | null }) {
  return (
    <>
      <h1 className="na-h1 na-h1-sm">This link is not valid any more</h1>
      <p className="na-body" data-testid="deletion-bad">
        {token
          ? message || 'It may have been used already, or the waiting time is over.'
          : 'The link looks incomplete. Please use the link in your email.'}
      </p>
      <Link to="/signin" className="na-btn na-go">
        Go to sign in
      </Link>
    </>
  )
}
