// The signed-out pages (New look wave 4, owner decisions 2026-10-25): B the light front page at the app root,
// C the split sign-in page, H "ask for an invite", and sign-up for someone holding an invite link. Invite only:
// sign-up needs the owner's approved invite link unless the server has open sign-up switched on.
// Replaces components/AuthScreen.tsx and keeps all its behaviour: the token goes to localStorage via setToken,
// the Google button is a real redirect to /auth/google/login, and the server's own error words are shown.
import { useEffect, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { Link, useLocation } from 'react-router-dom'

import { ApiError, api, googleLoginUrl, setToken } from '../api/client'
import {
  DISCLAIMER,
  EXPERIENCE_OPTIONS,
  LANGUAGE_OPTIONS,
  afterSignIn,
  friendlyError,
  inviteFormProblem,
  readInviteLink,
  viewFor,
  type AuthOptions,
  type InviteForm,
} from './authRules'
import './newAuth.css'

function errorText(err: unknown): string {
  return err instanceof ApiError ? friendlyError(err.message, err.status) : 'Something went wrong. Please try again.'
}

/** A new session: store the token, then open the app (the public pages themselves have no signed-in screen). */
function startSession(token: string) {
  setToken(token)
  if (afterSignIn(window.location.pathname) === 'home') window.location.replace('/')
  else window.location.reload()
}

function Icon({ d, children }: { d?: string; children?: ReactNode }) {
  return (
    <svg className="na-ic" viewBox="0 0 24 24" aria-hidden="true">
      {d ? <path d={d} /> : children}
    </svg>
  )
}

const ICON_PULSE = 'M3 12h4l3-8 4 16 3-8h4'
const ICON_SHIELD = 'M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z'
const ICON_TICK = 'M5 12.5l4.5 4.5L19 7.5'

function Brand({ dark = false }: { dark?: boolean }) {
  return (
    <Link to="/" className={`na-brand${dark ? ' na-brand-dark' : ''}`} aria-label="TradeMind, front page">
      <span className="na-mark">
        <Icon d={ICON_PULSE} />
      </span>
      TradeMind
    </Link>
  )
}

function Lock() {
  return (
    <Icon>
      <rect x="4" y="10" width="16" height="10" rx="2" />
      <path d="M8 10V7a4 4 0 0 1 8 0v3" />
    </Icon>
  )
}

function GoogleButton() {
  return (
    <a className="na-sso" href={googleLoginUrl()}>
      <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
        <path fill="#4285F4" d="M22 12.2c0-.7-.1-1.4-.2-2H12v3.8h5.6a4.8 4.8 0 0 1-2.1 3.1v2.6h3.4c2-1.8 3.1-4.5 3.1-7.5z" />
        <path fill="#34A853" d="M12 22c2.8 0 5.2-.9 6.9-2.5l-3.4-2.6c-.9.6-2.1 1-3.5 1-2.7 0-5-1.8-5.8-4.3H2.7v2.7A10 10 0 0 0 12 22z" />
        <path fill="#FBBC05" d="M6.2 13.6a6 6 0 0 1 0-3.8V7.1H2.7a10 10 0 0 0 0 9.2z" />
        <path fill="#EA4335" d="M12 6c1.5 0 2.9.5 4 1.5l3-3A10 10 0 0 0 2.7 7.1l3.5 2.7C7 7.8 9.3 6 12 6z" />
      </svg>
      Continue with Google
    </a>
  )
}

function ErrorBox({ text }: { text: string | null }) {
  if (!text) return null
  return (
    <div className="na-error" role="alert">
      {text}
    </div>
  )
}

// ------------------------------------------------------------------ B: front page --

function Landing({ options }: { options: AuthOptions | null }) {
  return (
    <div className="na na-page">
      <header className="na-bar">
        <Brand />
        <span className="na-grow" />
        <Link to="/signin" className="na-btn na-ghost">
          Sign in
        </Link>
        {/* On a phone the join card just below carries this button; the bar keeps only Sign in. */}
        <Link to="/invite" className="na-btn na-cta na-hide-phone">
          Ask for an invite
        </Link>
      </header>

      <section className="na-hero">
        <div className="na-left">
          <span className="na-tag">For Indian stocks · Practise with paper money first</span>
          <h1 className="na-h1">
            Know what to do with your stocks <span>tonight</span>.
          </h1>
          <p className="na-lead">
            One clear answer per stock — TRADE, WATCH, WAIT or AVOID — with the reason, the plan and the safety
            checks, in plain English.
          </p>

          <div className="na-preview" aria-label="Example of how ideas look">
            <div className="na-preview-head">
              <b>How an evening’s ideas look</b>
              <span className="na-fine">Example only, not real ideas</span>
            </div>
            <div className="na-prow">
              <span className="na-logo" style={{ background: '#0f4c81' }}>
                AB
              </span>
              <span className="na-prow-text">
                <b>Stock A</b>
                <span className="na-fine">Strong trend, waiting for a better price</span>
              </span>
              <span className="na-word na-watch">WATCH</span>
            </div>
            <div className="na-prow">
              <span className="na-logo" style={{ background: '#6d28d9' }}>
                CD
              </span>
              <span className="na-prow-text">
                <b>Stock B</b>
                <span className="na-fine">Company results due this week</span>
              </span>
              <span className="na-word na-wait">WAIT</span>
            </div>
            <div className="na-prow">
              <span className="na-logo" style={{ background: '#9a3412' }}>
                EF
              </span>
              <span className="na-prow-text">
                <b>Stock C</b>
                <span className="na-fine">Below its 50-day average</span>
              </span>
              <span className="na-word na-avoid">AVOID</span>
            </div>
          </div>

          <div className="na-three">
            <div className="na-t">
              <span className="na-ti" style={{ background: '#ede9fe', color: '#5b21b6' }}>
                <Icon>
                  <path d="M9 12l2 2 4-4" />
                  <circle cx="12" cy="12" r="9" />
                </Icon>
              </span>
              <span>
                <b>See every step</b>
                <span className="na-fine">The checks behind each idea</span>
              </span>
            </div>
            <div className="na-t">
              <span className="na-ti" style={{ background: '#dcfce7', color: '#166534' }}>
                <Icon d={ICON_SHIELD} />
              </span>
              <span>
                <b>Safety net</b>
                <span className="na-fine">−4% stop, +8% target</span>
              </span>
            </div>
            <div className="na-t">
              <span className="na-ti" style={{ background: '#e0ecff', color: '#1e40af' }}>
                <Icon>
                  <circle cx="12" cy="12" r="9" />
                  <path d="M12 7v5l3 2" />
                </Icon>
              </span>
              <span>
                <b>Every evening</b>
                <span className="na-fine">After the market closes</span>
              </span>
            </div>
          </div>
        </div>

        <aside className="na-card na-join" aria-label="How to join">
          <span className="na-badge">
            <Lock />
            Invite only while we test
          </span>
          <h2 className="na-h2">Join the trial</h2>
          <p className="na-fine na-body">
            We’re trying TradeMind with a few people first, using paper money only. Ask for a place and the owner
            will get in touch.
          </p>
          <Link to="/invite" className="na-btn na-go">
            Ask for an invite
          </Link>
          {options?.signup_allowed && (
            <Link to="/signup" className="na-btn na-ghost na-wide">
              Create an account
            </Link>
          )}
          <p className="na-fine na-center">
            Already have an account? <Link to="/signin">Sign in</Link>
          </p>
          <p className="na-fine na-center">{DISCLAIMER}</p>
        </aside>
      </section>

      <section className="na-strip" aria-label="Why TradeMind">
        <div className="na-s">
          <b>Plain answers</b>
          <span className="na-fine">One word per stock, one reason.</span>
        </div>
        <div className="na-s">
          <b>Paper first</b>
          <span className="na-fine">Practise with paper money before any real money.</span>
        </div>
        <div className="na-s">
          <b>Honest records</b>
          <span className="na-fine">Wins and losses, both shown.</span>
        </div>
        <div className="na-s">
          <b>Learning, not advice</b>
          <span className="na-fine">You decide what to do with your money.</span>
        </div>
      </section>
      <footer className="na-foot">{DISCLAIMER}</footer>
    </div>
  )
}

// ------------------------------------------------------------------ C: sign in --

function Promises() {
  return (
    <section className="na-panel" aria-label="About TradeMind">
      <Brand dark />
      <div className="na-panel-mid">
        <p className="na-quote">One clear answer for every stock, every evening.</p>
        <div className="na-pts">
          <div className="na-pt">
            <span className="na-dot">
              <Icon d={ICON_TICK} />
            </span>
            <span>
              <b>TRADE, WATCH, WAIT or AVOID</b>
              <br />
              with the reason and the plan.
            </span>
          </div>
          <div className="na-pt">
            <span className="na-dot">
              <Icon d={ICON_SHIELD} />
            </span>
            <span>
              <b>Safety net built in</b>
              <br />
              −4% stop, +8% target, out within 15 trading days.
            </span>
          </div>
          <div className="na-pt">
            <span className="na-dot">
              <Lock />
            </span>
            <span>
              <b>Paper money first</b>
              <br />
              Real money only when you decide.
            </span>
          </div>
        </div>
      </div>
      <p className="na-panel-foot">{DISCLAIMER}</p>
    </section>
  )
}

function SignIn({ options, initialError }: { options: AuthOptions | null; initialError: string | null }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(initialError)
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    setBusy(true)
    try {
      const result = await api.login(username.trim(), password)
      startSession(result.access_token)
    } catch (err) {
      setError(errorText(err))
      setBusy(false)
    }
  }

  return (
    <div className="na na-split">
      <Promises />
      <section className="na-formside" aria-label="Sign in">
        <form className="na-form" onSubmit={submit}>
          <h1 className="na-h1 na-h1-sm">Welcome back</h1>
          <p className="na-fine na-body">Sign in to see tonight’s ideas.</p>
          <ErrorBox text={error} />
          {options?.google && (
            <>
              <GoogleButton />
              <div className="na-or">OR</div>
            </>
          )}
          <label className="na-label">
            Email or username
            <input
              className="na-input"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              autoCapitalize="none"
              autoFocus
              required
            />
          </label>
          <label className="na-label">
            Password
            <input
              className="na-input"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
            />
          </label>
          <button className="na-btn na-go" type="submit" disabled={busy}>
            {busy ? 'Signing in…' : 'Sign in'}
          </button>
          <p className="na-fine na-center">
            New here? <Link to="/invite">Ask for an invite</Link>
            {options?.signup_allowed && (
              <>
                {' '}
                or <Link to="/signup">create an account</Link>
              </>
            )}
          </p>
          <p className="na-fine na-center">{DISCLAIMER}</p>
        </form>
      </section>
    </div>
  )
}

// ------------------------------------------------------------------ H: ask for an invite --

function InviteRequest() {
  const [form, setForm] = useState<InviteForm>({
    name: '',
    email: '',
    phone: '',
    experience: 'just_starting',
    language: 'english',
  })
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [sentTo, setSentTo] = useState<string | null>(null)
  const set = (k: keyof InviteForm) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value })

  async function submit(event: FormEvent) {
    event.preventDefault()
    const problem = inviteFormProblem(form)
    if (problem) {
      setError(problem)
      return
    }
    setError(null)
    setBusy(true)
    try {
      await api.requestInvite({ ...form, name: form.name.trim(), email: form.email.trim() })
      setSentTo(form.name.trim().split(' ')[0] || form.name.trim())
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="na na-page">
      <header className="na-bar">
        <Brand />
        <span className="na-grow" />
        <span className="na-fine na-hide-phone">Already invited?</span>
        <Link to="/signin" className="na-btn na-ghost">
          Sign in
        </Link>
      </header>
      <div className="na-main">
        <div className="na-left">
          <span className="na-badge">
            <Lock />
            Invite only while we test
          </span>
          <h1 className="na-h1 na-h1-md">TradeMind is in a small, careful trial.</h1>
          <p className="na-lead">
            We’re testing with a few people first, using paper money only. Ask for a place and the owner will
            contact you when one opens.
          </p>
          <ol className="na-steps">
            <li className="na-step">
              <span className="na-n">1</span>
              <span>
                <b>Ask for an invite</b>
                <span className="na-fine">Takes 30 seconds.</span>
              </span>
            </li>
            <li className="na-step">
              <span className="na-n">2</span>
              <span>
                <b>The owner reads every request</b>
                <span className="na-fine">If there is a place, they send you a personal sign-up link themselves.</span>
              </span>
            </li>
            <li className="na-step">
              <span className="na-n">3</span>
              <span>
                <b>Start with paper money</b>
                <span className="na-fine">See tonight’s ideas and every reason behind them.</span>
              </span>
            </li>
          </ol>
        </div>

        {sentTo ? (
          <div className="na-card na-form-card" role="status" data-testid="invite-thanks">
            <span className="na-done">
              <Icon d={ICON_TICK} />
            </span>
            <h2 className="na-h2">Thanks, {sentTo}.</h2>
            <p className="na-body">
              Your request is with the owner. Nothing is sent automatically: if a place opens, the owner will
              contact you personally with your sign-up link.
            </p>
            <p className="na-fine">You can close this page.</p>
            <Link to="/" className="na-btn na-ghost na-wide">
              Back to the front page
            </Link>
          </div>
        ) : (
          <form className="na-card na-form-card" onSubmit={submit} noValidate>
            <h2 className="na-h2">Ask for an invite</h2>
            <ErrorBox text={error} />
            <label className="na-label">
              Your name
              <input className="na-input" value={form.name} onChange={set('name')} autoComplete="name" maxLength={80} required />
            </label>
            <label className="na-label">
              Email
              <input
                className="na-input"
                type="email"
                value={form.email}
                onChange={set('email')}
                autoComplete="email"
                autoCapitalize="none"
                maxLength={254}
                required
              />
            </label>
            <label className="na-label">
              Phone (optional)
              <input className="na-input" type="tel" value={form.phone} onChange={set('phone')} autoComplete="tel" maxLength={20} placeholder="+91" />
            </label>
            <label className="na-label">
              How much do you trade?
              <select className="na-input" value={form.experience} onChange={set('experience')}>
                {EXPERIENCE_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="na-label">
              Preferred language
              <select className="na-input" value={form.language} onChange={set('language')}>
                {LANGUAGE_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>
            <button className="na-btn na-go" type="submit" disabled={busy}>
              {busy ? 'Sending…' : 'Send my request'}
            </button>
            <p className="na-fine">
              Only the owner sees your request; your email is used to contact you about the invite. {DISCLAIMER}
            </p>
          </form>
        )}
      </div>
      <footer className="na-foot">{DISCLAIMER}</footer>
    </div>
  )
}

// ------------------------------------------------------------------ sign up (with an invite) --

function SignUp({ options, invite }: { options: AuthOptions | null; invite: { code: string; email: string } | null }) {
  const [email, setEmail] = useState(invite?.email ?? '')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const allowed = !!invite || !!options?.signup_allowed

  async function submit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    if (password.length < 8) {
      setError('Please use a password of at least 8 characters.')
      return
    }
    setBusy(true)
    try {
      const result = await api.signup(username.trim(), password, email.trim() || undefined, invite?.code)
      startSession(result.access_token)
    } catch (err) {
      setError(errorText(err))
      setBusy(false)
    }
  }

  return (
    <div className="na na-split">
      <Promises />
      <section className="na-formside" aria-label="Create your account">
        {allowed ? (
          <form className="na-form" onSubmit={submit}>
            <h1 className="na-h1 na-h1-sm">Create your account</h1>
            <p className="na-fine na-body">
              {invite ? 'Your invite is ready. ' : ''}You start with paper money: no real money is used.
            </p>
            <ErrorBox text={error} />
            <label className="na-label">
              Email{invite ? ' (the one your invite was sent for)' : ' (optional)'}
              <input
                className="na-input"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="email"
                autoCapitalize="none"
                required={!!invite}
              />
            </label>
            <label className="na-label">
              Choose a username
              <input
                className="na-input"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
                autoCapitalize="none"
                minLength={3}
                maxLength={64}
                required
              />
            </label>
            <label className="na-label">
              Choose a password
              <input
                className="na-input"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="new-password"
                placeholder="At least 8 characters"
                minLength={8}
                required
              />
            </label>
            <button className="na-btn na-go" type="submit" disabled={busy}>
              {busy ? 'Please wait…' : 'Create account'}
            </button>
            <p className="na-fine na-center">
              Already have an account? <Link to="/signin">Sign in</Link>
            </p>
            <p className="na-fine na-center">{DISCLAIMER}</p>
          </form>
        ) : (
          <div className="na-form" data-testid="signup-closed">
            <h1 className="na-h1 na-h1-sm">Sign-up is by invite only</h1>
            <p className="na-body">
              To create an account you need the personal sign-up link the owner sends after approving your request.
            </p>
            <Link to="/invite" className="na-btn na-go">
              Ask for an invite
            </Link>
            <p className="na-fine na-center">
              Already have an account? <Link to="/signin">Sign in</Link>
            </p>
            <p className="na-fine na-center">{DISCLAIMER}</p>
          </div>
        )}
      </section>
    </div>
  )
}

// ------------------------------------------------------------------ the switch --

/** Shown whenever there is no valid token: first visit, after logout, or after a 401 clears an expired one. */
export default function PublicSite({
  initialError = null,
  initialOptions = null,
}: {
  initialError?: string | null
  /** Tests pass the server's options directly; the app asks GET /auth/options. */
  initialOptions?: AuthOptions | null
}) {
  const location = useLocation()
  const [options, setOptions] = useState<AuthOptions | null>(initialOptions)
  // The invite link is read once and taken out of the address bar (like the Google login code), so the
  // one-time code doesn't sit in the browser history after it has been used.
  const [invite] = useState(() => readInviteLink(location.search))

  useEffect(() => {
    if (invite && typeof window !== 'undefined') window.history.replaceState({}, '', '/signup')
  }, [invite])

  useEffect(() => {
    if (initialOptions) return
    api
      .authOptions()
      .then(setOptions)
      .catch(() => setOptions({ signup_allowed: false, invites: true, google: false }))
  }, [initialOptions])

  const view = viewFor(location.pathname, !!initialError)
  useEffect(() => {
    document.title =
      view === 'invite' ? 'Ask for an invite · TradeMind' : view === 'signin' ? 'Sign in · TradeMind' : 'TradeMind'
  }, [view])

  if (view === 'landing') return <Landing options={options} />
  if (view === 'invite') return <InviteRequest />
  if (view === 'signup') return <SignUp options={options} invite={invite} />
  return <SignIn options={options} initialError={initialError} />
}
