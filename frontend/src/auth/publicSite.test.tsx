// Wave 4 signed-out pages: which page shows where, invite-only wording, the Google button only when the server
// has it, the honest-wording rules, and the request form's checks. Admin > Invites words are tested here too.
import { renderToString } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { countWaiting, inviteLink, inviteState, type InviteRequestRow } from '../trademind/invites'
import {
  BANNED_PUBLIC_WORDS,
  DISCLAIMER,
  afterSignIn,
  friendlyError,
  inviteFormProblem,
  isValidEmail,
  readInviteLink,
  viewFor,
  type AuthOptions,
} from './authRules'
import PublicSite from './PublicSite'

const CLOSED: AuthOptions = { signup_allowed: false, invites: true, google: false }

function render(path: string, options: AuthOptions = CLOSED, initialError: string | null = null): string {
  return renderToString(
    <MemoryRouter initialEntries={[path]}>
      <PublicSite initialOptions={options} initialError={initialError} />
    </MemoryRouter>,
  )
}

const text = (html: string) => html.replace(/<[^>]+>/g, ' ').replace(/&#x27;|&#39;/g, "'").replace(/\s+/g, ' ')

describe('which page a signed-out visitor sees', () => {
  it('front page only at the root; invite and sign-up by address; anything else is sign-in', () => {
    expect(viewFor('/')).toBe('landing')
    expect(viewFor('/invite')).toBe('invite')
    expect(viewFor('/invite/')).toBe('invite')
    expect(viewFor('/signup')).toBe('signup')
    expect(viewFor('/signin')).toBe('signin')
    expect(viewFor('/trademind/positions')).toBe('signin')
  })

  it('a sign-in error (Google redirect failed) shows the sign-in page, even at the root', () => {
    expect(viewFor('/', true)).toBe('signin')
    expect(render('/', CLOSED, 'This sign-in link has expired.')).toContain('This sign-in link has expired.')
  })

  it('after signing in, public pages go to the app start; a deep link stays where it was', () => {
    expect(afterSignIn('/signin')).toBe('home')
    expect(afterSignIn('/signup')).toBe('home')
    expect(afterSignIn('/invite')).toBe('home')
    expect(afterSignIn('/trademind/records')).toBe('stay')
  })
})

describe('B: front page', () => {
  it('is invite only: asks for an invite, offers sign-in, no open sign-up while it is closed', () => {
    const t = text(render('/'))
    expect(t).toContain('Ask for an invite')
    expect(t).toContain('Invite only while we test')
    expect(t).toContain('Sign in')
    expect(t).not.toContain('Create an account')
    expect(t).toContain('TRADE, WATCH, WAIT or AVOID')
  })

  it('offers sign-up only when the server has open sign-up on', () => {
    expect(text(render('/', { ...CLOSED, signup_allowed: true }))).toContain('Create an account')
  })

  it('says the example is an example', () => {
    expect(text(render('/'))).toContain('Example only, not real ideas')
  })
})

describe('C: sign-in', () => {
  it('has email-or-username and password, ask for an invite, and no forgot-password (no reset flow exists)', () => {
    const t = text(render('/signin'))
    expect(t).toContain('Email or username')
    expect(t).toContain('Password')
    expect(t).toContain('Ask for an invite')
    expect(t).toContain('Welcome back')
    expect(t.toLowerCase()).not.toContain('forgot')
    expect(t).not.toContain('తెలుగు') // the language switch waits until Telugu exists
  })

  it('shows Google only when the server says it is set up', () => {
    expect(render('/signin')).not.toContain('Continue with Google')
    const html = render('/signin', { ...CLOSED, google: true })
    expect(html).toContain('Continue with Google')
    expect(html).toContain('/auth/google/login')
  })
})

describe('H: ask for an invite', () => {
  it('asks name, email, optional phone, experience and language, and promises no automatic email', () => {
    const t = text(render('/invite'))
    for (const field of ['Your name', 'Email', 'Phone (optional)', 'How much do you trade?', 'Preferred language']) {
      expect(t).toContain(field)
    }
    expect(t).toContain('Send my request')
    expect(t).toContain('the owner will contact you')
    expect(t.toLowerCase()).not.toContain('we’ll email you')
    expect(t.toLowerCase()).not.toContain("we'll email you")
  })

  it('checks the form the same way the server does', () => {
    const ok = { name: 'Asha', email: 'asha@example.com', phone: '', experience: 'just_starting', language: 'english' }
    expect(inviteFormProblem(ok)).toBeNull()
    expect(inviteFormProblem({ ...ok, name: '  ' })).toMatch(/name/)
    expect(inviteFormProblem({ ...ok, email: 'asha@' })).toMatch(/email/)
    expect(inviteFormProblem({ ...ok, phone: 'call me' })).toMatch(/phone/)
    expect(inviteFormProblem({ ...ok, phone: '+91 98765 43210' })).toBeNull()
    expect(inviteFormProblem({ ...ok, experience: 'pro' })).toMatch(/trade/)
    expect(isValidEmail('a@b')).toBe(false)
    expect(isValidEmail('a@b.co')).toBe(true)
  })
})

describe('sign-up', () => {
  it('without an invite link, while sign-up is closed, sends people to ask for an invite', () => {
    const html = render('/signup')
    expect(html).toContain('signup-closed')
    expect(text(html)).toContain('Sign-up is by invite only')
    expect(html).not.toContain('Create account')
  })

  it('with an invite link, shows the form with the invited email filled in', () => {
    const html = render('/signup?invite=abc123DEF456ghi7&email=Asha%40Example.com')
    expect(html).toContain('Create account')
    expect(html).toContain('value="asha@example.com"')
    expect(text(html)).toContain('Your invite is ready')
  })

  it('reads the invite link', () => {
    expect(readInviteLink('?invite=xyz&email=A%40B.com')).toEqual({ code: 'xyz', email: 'a@b.com' })
    expect(readInviteLink('?email=a@b.com')).toBeNull()
    expect(readInviteLink('')).toBeNull()
  })
})

describe('honest wording on every public page', () => {
  const pages = ['/', '/signin', '/invite', '/signup', '/signup?invite=abc&email=a%40b.co']
  it.each(pages)('%s carries the learning-not-advice line and no hype words', (path) => {
    const t = text(render(path, { ...CLOSED, google: true })).toLowerCase()
    expect(t).toContain(DISCLAIMER.toLowerCase())
    for (const word of BANNED_PUBLIC_WORDS) expect(t).not.toContain(word)
    expect(t).not.toMatch(/\d+% (win|accura|return)/)
  })
})

describe('plain-English errors', () => {
  it('turns a 422 list into its first message', () => {
    const detail = JSON.stringify([{ loc: ['body', 'email'], msg: 'Value error, Please enter a valid email address.' }])
    expect(friendlyError(detail, 422)).toBe('Please enter a valid email address.')
    expect(friendlyError('[{"msg":"String should have at least 8 characters"}]', 422)).toMatch(/8 characters/)
    expect(friendlyError('not json', 422)).toMatch(/check the form/)
    expect(friendlyError('Incorrect username or password.', 401)).toBe('Incorrect username or password.')
  })
})

describe('Admin > Invites words', () => {
  const row = (over: Partial<InviteRequestRow>): InviteRequestRow => ({
    id: 1, name: 'Asha', email: 'asha@example.com', phone: null, experience: 'just_starting', language: 'english',
    status: 'pending', created_at: '2026-10-25T10:00:00Z', decided_at: null, decided_by: null, note: null,
    used: false, used_at: null, has_account: false, ...over,
  })
  it('says where each request stands', () => {
    expect(inviteState(row({})).text).toBe('Waiting')
    expect(inviteState(row({ status: 'approved' })).text).toBe('Approved, not used yet')
    expect(inviteState(row({ status: 'approved', used: true })).text).toBe('Account made')
    expect(inviteState(row({ status: 'rejected' })).text).toBe('Rejected')
    expect(countWaiting([row({}), row({ status: 'rejected' })])).toBe(1)
  })
  it('builds the full link from the site address', () => {
    expect(inviteLink('https://swingtrademl.com/', '/signup?invite=x&email=a%40b.co')).toBe(
      'https://swingtrademl.com/signup?invite=x&email=a%40b.co',
    )
  })
})
