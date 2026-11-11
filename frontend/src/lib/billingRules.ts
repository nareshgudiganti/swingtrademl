// What the account screen says about the person's plan, as pure functions (no React) so the wording and the
// buttons can be tested. Everything is plain English: "Free" or "Pro", a date, and what happens next.
// The server decides who is on Pro (GET /billing/me `plan`); this file only describes it and never grants anything.

import type { BillingMe, BillingPlans } from '../api/types'

export const PRO_FEATURES_FALLBACK = [
  'Every idea of the day, not just the top few',
  'The reasons behind each idea, in plain words',
  'Your own watchlist, with more stocks',
]

/** 49900 paise -> "₹499". */
export function formatPrice(paise: number): string {
  const rupees = paise / 100
  return `₹${Number.isInteger(rupees) ? rupees.toLocaleString('en-IN') : rupees.toLocaleString('en-IN', { minimumFractionDigits: 2 })}`
}

/** "14 Dec 2026", in India time (the server sends UTC). */
export function formatDate(iso: string | null | undefined): string | null {
  if (!iso) return null
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return null
  return new Intl.DateTimeFormat('en-IN', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'Asia/Kolkata' }).format(d)
}

export type AccountState =
  | 'free'
  | 'free-upgrades-closed'
  | 'confirming'
  | 'pro'
  | 'pro-ending'
  | 'pro-given'
  | 'ended'

export type AccountView = {
  state: AccountState
  /** One line a person can read at a glance. */
  headline: string
  detail: string
  canUpgrade: boolean
  canCancel: boolean
}

/** The state of the plan card. `plans` may be missing (not loaded yet): upgrades then stay off. */
export function accountView(me: BillingMe, plans: BillingPlans | undefined): AccountView {
  const sub = me.subscription
  const through = formatDate(sub?.paid_through)
  const open = plans?.checkout_open === true

  if (me.plan === 'pro') {
    if (me.complimentary && (!sub || sub.status === 'cancelled' || sub.status === 'completed')) {
      return {
        state: 'pro-given',
        headline: 'You have Pro',
        detail: 'Pro was added to your account by the owner. There is nothing to pay.',
        canUpgrade: false,
        canCancel: false,
      }
    }
    if (sub?.cancel_scheduled || sub?.status === 'cancelled') {
      return {
        state: 'pro-ending',
        headline: through ? `Pro until ${through}` : 'Pro, ending soon',
        detail: through
          ? `You will not be charged again. On ${through} your account goes back to Free.`
          : 'You will not be charged again. Your account goes back to Free at the end of the period you paid for.',
        canUpgrade: false,
        canCancel: false,
      }
    }
    if (!sub) {
      return {
        state: 'pro',
        headline: 'You have Pro',
        detail: 'Pro is on for your account.',
        canUpgrade: false,
        canCancel: false,
      }
    }
    return {
      state: 'pro',
      headline: 'You have Pro',
      detail: through ? `Paid until ${through}. It renews each month unless you cancel.` : 'It renews each month unless you cancel.',
      canUpgrade: false,
      canCancel: true,
    }
  }

  if (sub && (sub.status === 'created' || sub.status === 'authenticated' || sub.status === 'pending')) {
    return {
      state: 'confirming',
      headline: 'We are confirming your payment',
      detail: 'This usually takes a minute. This page will update by itself; you do not need to pay again.',
      canUpgrade: false,
      canCancel: false,
    }
  }
  if (sub && (sub.status === 'cancelled' || sub.status === 'completed' || sub.status === 'halted' || sub.status === 'paused')) {
    return {
      state: 'ended',
      headline: 'You are on Free',
      detail: 'Your Pro plan has ended. You can start it again whenever you like.',
      canUpgrade: open,
      canCancel: false,
    }
  }
  if (!open) {
    return {
      state: 'free-upgrades-closed',
      headline: 'You are on Free',
      detail: 'Upgrading is not open yet. We will tell you when it is.',
      canUpgrade: false,
      canCancel: false,
    }
  }
  return {
    state: 'free',
    headline: 'You are on Free',
    detail: 'Upgrade to Pro to see every idea of the day.',
    canUpgrade: true,
    canCancel: false,
  }
}

/** The Pro price line, or null when the server did not send one. */
export function proPriceLine(plans: BillingPlans | undefined): string | null {
  const price = plans?.plans.find((p) => p.key === 'pro')?.price
  if (!price) return null
  return `${formatPrice(price.amount_paise)} a month`
}

/** Plain words for an error from the billing calls. */
export function billingErrorText(status: number | null, message: string): string {
  if (status === 409) return 'You already have Pro.'
  if (status === 404) return 'This is not available right now.'
  if (status === 502 || status === 503) return message || 'The payment service did not answer. Please try again in a minute.'
  if (status === 403) return 'Please sign in with your own account to use this.'
  return message || 'Something went wrong. Please try again.'
}
