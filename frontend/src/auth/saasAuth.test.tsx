// Customer sign-up, email links and plan wording: the pure rules, and what each page says when drawn.
import { renderToString } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import type { BillingMe, BillingPlans } from '../api/types'
import { accountView, formatDate, formatPrice, proPriceLine } from '../lib/billingRules'
import {
  BANNED_PUBLIC_WORDS,
  DISCLAIMER,
  PASSWORD_MIN,
  afterSignIn,
  friendlyError,
  passwordProblem,
  readEmailToken,
  registerFormProblem,
  viewFor,
  type AuthOptions,
} from './authRules'
import PublicSite from './PublicSite'

const OPEN: AuthOptions = { signup_allowed: true, invites: true, google: false }
const CLOSED: AuthOptions = { signup_allowed: false, invites: true, google: false }

function render(path: string, options: AuthOptions = OPEN): string {
  return renderToString(
    <MemoryRouter initialEntries={[path]}>
      <PublicSite initialOptions={options} />
    </MemoryRouter>,
  )
}
const text = (html: string) => html.replace(/<[^>]+>/g, ' ').replace(/&#x27;|&#39;/g, "'").replace(/\s+/g, ' ')

describe('the password rule', () => {
  it('is 15 characters, counted as characters', () => {
    expect(PASSWORD_MIN).toBe(15)
    expect(passwordProblem('a'.repeat(14))).toMatch(/at least 15 characters/)
    expect(passwordProblem('a'.repeat(15))).toBeNull()
    expect(passwordProblem('purple tractor eats seven cold noodles')).toBeNull()
    expect(passwordProblem('')).toMatch(/choose a password/i)
    expect(passwordProblem('a'.repeat(257))).toMatch(/256/)
  })
  it('an old "at least 8" server message is shown with the new rule', () => {
    expect(friendlyError('[{"msg":"String should have at least 8 characters"}]', 422)).toMatch(/15 characters/)
  })
})

describe('the sign-up form checks', () => {
  const ok = { name: 'Asha Rao', email: 'asha@example.com', mobile: '', password: 'purple tractor eats seven cold noodles' }
  it('accepts a good form, with the mobile left empty', () => {
    expect(registerFormProblem(ok)).toBeNull()
    expect(registerFormProblem({ ...ok, mobile: '+91 98765 43210' })).toBeNull()
  })
  it('names the first problem in plain words', () => {
    expect(registerFormProblem({ ...ok, name: ' ' })).toMatch(/your name/)
    expect(registerFormProblem({ ...ok, email: 'nope' })).toMatch(/valid email/)
    expect(registerFormProblem({ ...ok, mobile: 'abc' })).toMatch(/mobile number/)
    expect(registerFormProblem({ ...ok, password: 'short' })).toMatch(/15 characters/)
  })
})

describe('which page shows where', () => {
  it('email links and forgot-password have their own pages', () => {
    expect(viewFor('/verify-email')).toBe('verify')
    expect(viewFor('/forgot-password')).toBe('forgot')
    expect(viewFor('/reset-password/')).toBe('reset')
    // A sign-in error from Google must still show the sign-in page, but not hide an email-link page.
    expect(viewFor('/verify-email', true)).toBe('verify')
  })
  it('after signing in from one of them, goes to the app start', () => {
    expect(afterSignIn('/verify-email')).toBe('home')
    expect(afterSignIn('/reset-password')).toBe('home')
    expect(afterSignIn('/trademind/stock/INFY')).toBe('stay')
  })
  it('reads the one-time token from the link', () => {
    expect(readEmailToken('?token=abc123')).toBe('abc123')
    expect(readEmailToken('?token=')).toBeNull()
    expect(readEmailToken('')).toBeNull()
  })
})

describe('the public pages drawn', () => {
  it('open sign-up asks for name, email, optional mobile and a password, and says what happens next', () => {
    const html = render('/signup')
    const t = text(html)
    expect(t).toContain('Create your account')
    expect(t).toContain('Your name')
    expect(t).toContain('Mobile number (optional)')
    expect(html).toContain('minLength="15"')
    expect(html).not.toContain('minLength="8"')
    expect(t).toContain('Free plan')
  })
  it('closed sign-up still says invite only', () => {
    expect(render('/signup', CLOSED)).toContain('signup-closed')
  })
  it('an invite link keeps the invite form but with the 15-character rule', () => {
    const html = render('/signup?invite=abc123DEF456ghi7&email=a%40b.co', CLOSED)
    expect(text(html)).toContain('Your invite is ready')
    expect(html).toContain('minLength="15"')
  })
  it('sign-in links to forgot password', () => {
    expect(render('/signin')).toContain('href="/forgot-password"')
  })
  it('forgot, reset and confirm pages draw, and carry no hype words', () => {
    for (const path of ['/forgot-password', '/reset-password?token=x', '/reset-password', '/verify-email?token=x', '/signup']) {
      const t = text(render(path)).toLowerCase()
      for (const word of BANNED_PUBLIC_WORDS) expect(t, `${path}: ${word}`).not.toContain(word)
    }
    expect(text(render('/signup'))).toContain(DISCLAIMER)
  })
  it('a reset page with no link asks for a new one', () => {
    expect(render('/reset-password')).toContain('reset-bad')
  })
})

describe('plan wording', () => {
  const plans = (open = true): BillingPlans => ({
    plans: [
      { key: 'free', name: 'Free', features: {} },
      { key: 'pro', name: 'Pro', features: {}, price: { amount_paise: 49900, currency: 'INR', interval: 'monthly' } },
    ],
    provider: 'fake',
    sandbox: true,
    checkout_open: open,
  })
  const me = (over: Partial<BillingMe>): BillingMe => ({
    plan: 'free',
    stored_plan: 'free',
    complimentary: false,
    provider: 'fake',
    sandbox: true,
    subscription: null,
    ...over,
  })
  const sub = (status: string, cancel = false, end: string | null = '2026-12-14T10:00:00+00:00') => ({
    provider: 'fake',
    status,
    paid_through: end,
    cancel_scheduled: cancel,
    cancelled_at: null,
  })

  it('formats money and dates the way people read them', () => {
    expect(formatPrice(49900)).toBe('₹499')
    expect(formatPrice(49950)).toBe('₹499.50')
    expect(proPriceLine(plans())).toBe('₹499 a month')
    expect(proPriceLine(undefined)).toBeNull()
    expect(formatDate('2026-12-14T10:00:00+00:00')).toBe('14 Dec 2026')
    // 20:00 UTC on 13 Dec is already 14 Dec in India.
    expect(formatDate('2026-12-13T20:00:00+00:00')).toBe('14 Dec 2026')
    expect(formatDate(null)).toBeNull()
    expect(formatDate('not a date')).toBeNull()
  })
  it('Free with upgrades open can upgrade; closed cannot', () => {
    expect(accountView(me({}), plans(true))).toMatchObject({ state: 'free', canUpgrade: true, canCancel: false })
    expect(accountView(me({}), plans(false))).toMatchObject({ state: 'free-upgrades-closed', canUpgrade: false })
    // Plans not loaded yet: never offer a button we cannot back.
    expect(accountView(me({}), undefined).canUpgrade).toBe(false)
  })
  it('paying Pro can stop; a stopped one shows the date and offers nothing', () => {
    const active = accountView(me({ plan: 'pro', subscription: sub('active') }), plans())
    expect(active).toMatchObject({ state: 'pro', canCancel: true, canUpgrade: false })
    expect(active.detail).toContain('14 Dec 2026')
    const ending = accountView(me({ plan: 'pro', subscription: sub('active', true) }), plans())
    expect(ending).toMatchObject({ state: 'pro-ending', canCancel: false, canUpgrade: false })
    expect(ending.headline).toBe('Pro until 14 Dec 2026')
    expect(ending.detail).toContain('go')
  })
  it('closed checkouts do not take away or hide an existing Pro', () => {
    expect(accountView(me({ plan: 'pro', subscription: sub('active') }), plans(false)).canCancel).toBe(true)
  })
  it('an owner-given Pro has nothing to pay or cancel', () => {
    expect(accountView(me({ plan: 'pro', complimentary: true }), plans())).toMatchObject({
      state: 'pro-given',
      canCancel: false,
      canUpgrade: false,
    })
  })
  it('a payment still being confirmed shows no upgrade button, so nobody pays twice', () => {
    for (const s of ['created', 'authenticated', 'pending']) {
      expect(accountView(me({ subscription: sub(s, false, null) }), plans())).toMatchObject({
        state: 'confirming',
        canUpgrade: false,
      })
    }
  })
  it('an ended plan is Free and can be started again while checkouts are open', () => {
    expect(accountView(me({ subscription: sub('cancelled', true) }), plans())).toMatchObject({ state: 'ended', canUpgrade: true })
    expect(accountView(me({ subscription: sub('halted') }), plans(false))).toMatchObject({ state: 'ended', canUpgrade: false })
  })
})
