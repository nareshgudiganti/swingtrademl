// Account deletion, in plain words. Pure rules (no React) so the wording and which buttons show can be tested
// directly. The server decides everything: this only describes where the person's request stands.
import { formatDate } from './billingRules'

/** GET /account/deletion. `status` is the latest request: pending (link emailed), scheduled (grace period),
 *  cancelled (they kept the account) or completed (the account is gone, so nobody sees this). */
export type DeletionStatus = {
  enabled: boolean
  protected: boolean
  grace_days: number
  status: 'pending' | 'scheduled' | 'cancelled' | 'completed' | null
  scheduled_for: string | null
}

export type DeletionState = 'protected' | 'none' | 'requested' | 'scheduled' | 'kept'

export type DeletionView = {
  state: DeletionState
  headline: string
  detail: string
  /** Show the "Delete my account" button (also used to send the link again). */
  canRequest: boolean
  requestLabel: string
}

export function deletionView(s: DeletionStatus): DeletionView {
  if (s.protected) {
    return {
      state: 'protected',
      headline: 'This account cannot be deleted here',
      detail: 'It is the owner account. Ask the person who runs this system if it really has to go.',
      canRequest: false,
      requestLabel: '',
    }
  }
  if (s.status === 'pending') {
    return {
      state: 'requested',
      headline: 'Check your email to finish',
      detail:
        'We sent you a link. Nothing is deleted until you open it and confirm. If you do not want this, just ignore the email.',
      canRequest: true,
      requestLabel: 'Send the link again',
    }
  }
  if (s.status === 'scheduled') {
    const when = formatDate(s.scheduled_for)
    return {
      state: 'scheduled',
      headline: when ? `Your account will be deleted on ${when}` : 'Your account is set to be deleted',
      detail: 'Use the "keep my account" link in the email we sent you before then, and nothing will be lost.',
      canRequest: false,
      requestLabel: '',
    }
  }
  if (s.status === 'cancelled') {
    return {
      state: 'kept',
      headline: 'Your account is kept',
      detail: 'The earlier request to delete it was cancelled. You can ask again any time.',
      canRequest: true,
      requestLabel: 'Delete my account',
    }
  }
  return {
    state: 'none',
    headline: 'Delete my account',
    detail: `We send you a link to confirm. After you confirm you are signed out and have ${s.grace_days} days to change your mind. Then your name, email and other personal details are removed for good.`,
    canRequest: true,
    requestLabel: 'Delete my account',
  }
}

/** A plain sentence for a failed deletion call. `message` is the server's own text when it has one. */
export function deletionErrorText(status: number, message: string): string {
  if (status === 404) return 'Deleting an account is not open yet.'
  if (status === 429) return 'Too many tries. Please wait a few minutes and try again.'
  if (status === 403) return 'Please sign in as yourself to do this.'
  if (status === 502) return message || 'We could not cancel your Pro plan just now, so nothing was changed. Please try again in a few minutes.'
  return message || 'Something went wrong. Please try again.'
}

/** The two email-link pages (they work signed in or signed out, and the one-time token must reach them). */
export const DELETION_LINK_PATHS = { confirm: '/confirm-deletion', keep: '/cancel-deletion' } as const

export function deletionLinkKind(pathname: string): 'confirm' | 'keep' | null {
  const path = pathname.replace(/\/+$/, '')
  if (path === DELETION_LINK_PATHS.confirm) return 'confirm'
  if (path === DELETION_LINK_PATHS.keep) return 'keep'
  return null
}
