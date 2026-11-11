// Pure rules for the signed-out pages (New look wave 4): which page a signed-out visitor sees, the invite
// link, the request form's checks, and plain-English errors. No React here, so it can be tested directly.

/** What the sign-in page may offer, from GET /auth/options. */
export type AuthOptions = {
  signup_allowed: boolean
  /** People may ask for an invite (sign-up with an approved invite link works even while sign-up is closed). */
  invites?: boolean
  /** The Google button will work on this server. */
  google?: boolean
}

export type PublicView =
  | 'landing'
  | 'signin'
  | 'invite'
  | 'signup'
  | 'verify'
  | 'forgot'
  | 'reset'

export const PUBLIC_PATHS: Record<Exclude<PublicView, 'landing'>, string> = {
  signin: '/signin',
  invite: '/invite',
  signup: '/signup',
  verify: '/verify-email',
  forgot: '/forgot-password',
  reset: '/reset-password',
}

/**
 * The page a signed-out visitor sees. The front page only at the app root; any other address (a bookmarked
 * screen, or a session that just ended there) gets the sign-in page, so a returning person is one step from
 * where they were. A sign-in error (Google redirect failed) always shows the sign-in page.
 */
export function viewFor(pathname: string, hasError = false): PublicView {
  const path = pathname.replace(/\/+$/, '') || '/'
  if (path === PUBLIC_PATHS.invite) return 'invite'
  if (path === PUBLIC_PATHS.signup) return 'signup'
  if (path === PUBLIC_PATHS.verify) return 'verify'
  if (path === PUBLIC_PATHS.forgot) return 'forgot'
  if (path === PUBLIC_PATHS.reset) return 'reset'
  if (hasError) return 'signin'
  if (path === '/') return 'landing'
  return 'signin'
}

/** After signing in: the public pages have no signed-in screen, so they go to the app's start; anywhere else stays. */
export function afterSignIn(pathname: string): 'home' | 'stay' {
  const path = pathname.replace(/\/+$/, '') || '/'
  return Object.values(PUBLIC_PATHS).includes(path) ? 'home' : 'stay'
}

/** The invite link the owner sends: /signup?invite=CODE&email=... (Admin > Invites makes it). */
export function readInviteLink(search: string): { code: string; email: string } | null {
  const params = new URLSearchParams(search)
  const code = (params.get('invite') ?? '').trim()
  if (!code) return null
  return { code, email: (params.get('email') ?? '').trim().toLowerCase() }
}

/** The password rule in plain words (server: 15 or more characters, no symbol rules, not a very common one). */
export const PASSWORD_MIN = 15
export const PASSWORD_HINT = `Please use a password of at least ${PASSWORD_MIN} characters. A few random words with spaces works well.`
export const PASSWORD_PLACEHOLDER = `At least ${PASSWORD_MIN} characters`

/** The first problem with a new password, or null. The server has the final say (it also refuses very common ones). */
export function passwordProblem(password: string): string | null {
  if (!password) return 'Please choose a password.'
  if (password.length < PASSWORD_MIN) return PASSWORD_HINT
  if (password.length > 256) return 'Please keep your password under 256 characters.'
  return null
}

/** The link in the email: /verify-email?token=... or /reset-password?token=... Null when there is no token. */
export function readEmailToken(search: string): string | null {
  const token = (new URLSearchParams(search).get('token') ?? '').trim()
  return token || null
}

export type RegisterForm = { name: string; email: string; mobile: string; password: string }

/** The first problem with the open sign-up form, in plain words; null when it can be sent. */
export function registerFormProblem(f: RegisterForm): string | null {
  const name = f.name.trim()
  if (!name) return 'Please tell us your name.'
  if (name.length > 80) return 'Please keep your name under 80 letters.'
  if (!isValidEmail(f.email)) return 'Please enter a valid email address.'
  const mobile = f.mobile.trim()
  if (mobile && !/^\+?[0-9][0-9 -]{5,18}$/.test(mobile)) {
    return 'Please enter a mobile number with digits only, or leave it empty.'
  }
  return passwordProblem(f.password)
}

const EMAIL_RE = /^[^@\s]{1,64}@[^@\s]+\.[^@\s.]{2,}$/
const PHONE_RE = /^\+?[0-9][0-9 -]{5,18}$/

export function isValidEmail(email: string): boolean {
  const e = email.trim()
  return e.length <= 254 && EMAIL_RE.test(e)
}

export const EXPERIENCE_OPTIONS = [
  { value: 'just_starting', label: 'I’m just starting' },
  { value: 'now_and_then', label: 'Now and then' },
  { value: 'every_week', label: 'Every week' },
] as const

// Telugu is planned for later; the choice is recorded now so the owner knows who is waiting for it.
export const LANGUAGE_OPTIONS = [
  { value: 'english', label: 'English' },
  { value: 'telugu', label: 'తెలుగు (Telugu)' },
] as const

export type InviteForm = { name: string; email: string; phone: string; experience: string; language: string }

/** The first problem with the request form, in plain words; null when it can be sent. Same limits as the server. */
export function inviteFormProblem(f: InviteForm): string | null {
  const name = f.name.trim()
  if (!name) return 'Please tell us your name.'
  if (name.length > 80) return 'Please keep your name under 80 letters.'
  if (!isValidEmail(f.email)) return 'Please enter a valid email address.'
  const phone = f.phone.trim()
  if (phone && (phone.length > 20 || !PHONE_RE.test(phone))) {
    return 'Please enter a phone number with digits only, or leave it empty.'
  }
  if (!EXPERIENCE_OPTIONS.some((o) => o.value === f.experience)) return 'Please choose how much you trade.'
  if (!LANGUAGE_OPTIONS.some((o) => o.value === f.language)) return 'Please choose a language.'
  return null
}

/**
 * A server error in plain words. FastAPI's 422 detail is a JSON list of field errors; show the first one's
 * message (our own validators already word it for people) instead of raw JSON.
 */
export function friendlyError(message: string, status?: number): string {
  if (status === 429) return message || 'Too many tries from your connection. Please wait a minute and try again.'
  if (status === 422) {
    try {
      const items = JSON.parse(message) as { msg?: string; loc?: string[] }[]
      const first = Array.isArray(items) ? items[0] : undefined
      if (first?.msg) {
        const msg = first.msg.replace(/^Value error, /, '')
        if (/at least 15/.test(msg) || /at least 8/.test(msg)) return PASSWORD_HINT
        if (/at least 3/.test(msg)) return 'Please use a username of at least 3 characters.'
        return msg.endsWith('.') ? msg : `${msg}.`
      }
    } catch {
      /* not JSON: fall through */
    }
    return 'Some details are not right. Please check the form and try again.'
  }
  return message || 'Something went wrong. Please try again.'
}

/** Words the public pages must never use (owner decision 2026-10-25: honest wording, no hype, no claims). */
export const BANNED_PUBLIC_WORDS = [
  'real-time',
  'institutional-grade',
  'neural network',
  'trade like a pro',
  'guaranteed',
  'profit',
] as const

export const DISCLAIMER = 'Ideas are for learning, not investment advice.'
