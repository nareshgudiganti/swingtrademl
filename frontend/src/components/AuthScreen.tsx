import { useState } from 'react'

import { ApiError, api, googleLoginUrl, setToken } from '../api/client'

/** Shown whenever there is no valid token: first run, after logout, or after
 * a 401 clears an expired one. Handles both login and self-registration. */
export default function AuthScreen() {
  const [mode, setMode] = useState<'login' | 'signup'>('login')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [email, setEmail] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setError(null)
    setBusy(true)
    try {
      const result =
        mode === 'login'
          ? await api.login(username, password)
          : await api.signup(username, password, email || undefined)
      setToken(result.access_token)
      window.location.reload()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Something went wrong')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={{ display: 'grid', placeItems: 'center', minHeight: '100vh', padding: '1rem' }}>
      <form className="card" style={{ maxWidth: 380, width: '100%' }} onSubmit={submit}>
        <h1 style={{ marginBottom: '0.25rem' }}>Swing Trade ML</h1>
        <p className="muted" style={{ marginTop: 0 }}>
          {mode === 'login' ? 'Sign in to your account.' : 'Create an account to get started.'}
        </p>
        <p className="muted" style={{ fontSize: '0.85rem', lineHeight: 1.5 }}>
          An ML-driven swing-trading bot for NSE stocks — it scans a watchlist daily and
          surfaces buy/hold/exit calls with a confidence score. This is a single shared
          account: everyone who signs in sees the same positions and portfolio, currently
          running in paper (simulated) mode.
        </p>

        {error && (
          <div className="banner banner-warn" style={{ marginBottom: '0.8rem' }}>
            {error}
          </div>
        )}

        <div style={{ display: 'grid', gap: '0.6rem' }}>
          <label>
            <div className="stat-label">Username</div>
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoFocus
              required
              minLength={3}
            />
          </label>

          {mode === 'signup' && (
            <label>
              <div className="stat-label">Email (optional)</div>
              <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
            </label>
          )}

          <label>
            <div className="stat-label">Password</div>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={mode === 'signup' ? 8 : undefined}
            />
          </label>
        </div>

        <button className="primary" type="submit" disabled={busy} style={{ marginTop: '1rem', width: '100%' }}>
          {busy ? 'Please wait…' : mode === 'login' ? 'Sign in' : 'Create account'}
        </button>

        <div style={{ margin: '0.9rem 0', textAlign: 'center' }} className="muted">
          or
        </div>

        <a href={googleLoginUrl()}>
          <button type="button" style={{ width: '100%' }}>
            Sign in with Google
          </button>
        </a>

        <p className="muted" style={{ fontSize: '0.82rem', marginTop: '1rem', textAlign: 'center' }}>
          {mode === 'login' ? (
            <>
              No account?{' '}
              <a href="#" onClick={(e) => (e.preventDefault(), setMode('signup'))} style={{ textDecoration: 'underline' }}>
                Sign up
              </a>
            </>
          ) : (
            <>
              Already have an account?{' '}
              <a href="#" onClick={(e) => (e.preventDefault(), setMode('login'))} style={{ textDecoration: 'underline' }}>
                Sign in
              </a>
            </>
          )}
        </p>
      </form>
    </div>
  )
}
