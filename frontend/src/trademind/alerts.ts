// Admin > Alerts (tracker ux3): which Telegram messages reach the owner's phone, quiet hours and the daily digest.
// Types and pure helpers for pages/Alerts.tsx, kept here so they can be tested without a browser.
// The server (services/alert_settings.py) is the one that decides; this file only edits the owner's choices.

export type AlertType = { key: string; label: string; explain: string; on: boolean }

export type AlertSettings = {
  switchable: AlertType[]
  always_on: AlertType[]
  disabled: string[]
  quiet_enabled: boolean
  quiet_start: string
  quiet_end: string
  digest_enabled: boolean
  digest_time: string
  last_digest_on: string | null
  held: number
  timezone: string
}

export type AlertSettingsUpdate = {
  disabled: string[]
  quiet_enabled: boolean
  quiet_start: string
  quiet_end: string
  digest_enabled: boolean
  digest_time: string
}

export function draftFrom(s: AlertSettings): AlertSettingsUpdate {
  return {
    disabled: [...s.disabled].sort(),
    quiet_enabled: s.quiet_enabled,
    quiet_start: s.quiet_start,
    quiet_end: s.quiet_end,
    digest_enabled: s.digest_enabled,
    digest_time: s.digest_time,
  }
}

/** Switch one alert type on or off; the list stays sorted so "changed?" is a plain comparison. */
export function toggle(d: AlertSettingsUpdate, key: string, on: boolean): AlertSettingsUpdate {
  const rest = d.disabled.filter((k) => k !== key)
  return { ...d, disabled: (on ? rest : [...rest, key]).sort() }
}

export function isOn(d: AlertSettingsUpdate, key: string): boolean {
  return !d.disabled.includes(key)
}

export function sameDraft(a: AlertSettingsUpdate, b: AlertSettingsUpdate): boolean {
  return JSON.stringify(a) === JSON.stringify(b)
}

const HHMM = /^([01]\d|2[0-3]):[0-5]\d$/

function minutes(t: string): number {
  return Number(t.slice(0, 2)) * 60 + Number(t.slice(3, 5))
}

/** Same rule as the server: start minute is inside, end minute is not; 22:00–07:00 runs overnight. */
export function inWindow(t: string, start: string, end: string): boolean {
  const [x, s, e] = [minutes(t), minutes(start), minutes(end)]
  if (s === e) return false
  return s < e ? x >= s && x < e : x >= s || x < e
}

/** A plain reason the draft can't be saved, or null when it is fine. */
export function problem(d: AlertSettingsUpdate): string | null {
  for (const t of [d.quiet_start, d.quiet_end, d.digest_time]) {
    if (!HHMM.test(t)) return 'Times must look like 07:30.'
  }
  if (d.quiet_enabled && d.quiet_start === d.quiet_end) return 'Quiet hours need a start and an end that differ.'
  if (d.digest_enabled && d.quiet_enabled && inWindow(d.digest_time, d.quiet_start, d.quiet_end)) {
    return 'Pick a digest time outside your quiet hours, or it would never be sent.'
  }
  return null
}

/** "22:00 to 07:00 (overnight)" */
export function quietText(start: string, end: string): string {
  return `${start} to ${end}${minutes(start) > minutes(end) ? ' (overnight)' : ''}`
}

export function heldText(n: number): string | null {
  if (n <= 0) return null
  return `${n} message${n === 1 ? ' is' : 's are'} waiting to be sent (quiet hours or the digest).`
}
