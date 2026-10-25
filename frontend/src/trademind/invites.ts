// Admin > Invites: the shapes the API sends and the plain words the page shows. Pure, so it can be tested.

export type InviteStatus = 'pending' | 'approved' | 'rejected'

export type InviteRequestRow = {
  id: number
  name: string
  email: string
  phone: string | null
  experience: string
  language: string
  status: InviteStatus
  created_at: string
  decided_at: string | null
  decided_by: string | null
  note: string | null
  used: boolean
  used_at: string | null
  /** Someone already has an account with this email. */
  has_account: boolean
}

/** Approve / new-code answers carry the one-time code once; only its hash is kept on the server. */
export type InviteDecision = InviteRequestRow & { invite_code: string; signup_path: string }

const EXPERIENCE: Record<string, string> = {
  just_starting: 'Just starting',
  now_and_then: 'Now and then',
  every_week: 'Every week',
}
const LANGUAGE: Record<string, string> = { english: 'English', telugu: 'Telugu' }

export const experienceLabel = (v: string) => EXPERIENCE[v] ?? v
export const languageLabel = (v: string) => LANGUAGE[v] ?? v

/** Where a request stands, in a word the owner reads at a glance. */
export function inviteState(r: InviteRequestRow): { text: string; tone: 'wait' | 'ok' | 'off' | 'done' } {
  if (r.status === 'pending') return { text: 'Waiting', tone: 'wait' }
  if (r.status === 'rejected') return { text: 'Rejected', tone: 'off' }
  if (r.used) return { text: 'Account made', tone: 'done' }
  return { text: 'Approved, not used yet', tone: 'ok' }
}

/** The full sign-up link to send by hand (there is no email service). */
export function inviteLink(origin: string, signupPath: string): string {
  return `${origin.replace(/\/+$/, '')}${signupPath}`
}

export function countWaiting(rows: InviteRequestRow[]): number {
  return rows.filter((r) => r.status === 'pending').length
}
