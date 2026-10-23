// Plain-English text for the one recommendation card (oa12). Pure functions, so they can be tested.
//
// Two rules hold everywhere on the card:
//  - The model score is a ranking between today's ideas, never a chance (see ../scoreText.ts). Only a
//    calibrated chance (honest_score measured on days the model had not seen) may be shown with a % sign.
//  - Every signal is "Experimental, unproven": the 15-day model failed its frozen test.

import type { BrainDecision } from '../../api/types'

/** Shown on every signal. */
export const EXPERIMENTAL = 'Experimental, unproven'

/** The frozen walk-forward test (wf-protocol-v1, 1 Jul 2023 to 31 Jan 2025) failed on both parts.
 *  Source: docs/brain/evidence/wf_v1/walk_forward_2023-07-01_2025-01-31.md. The verdict endpoint
 *  (/brain/observatory/effectiveness) is owner-only, so Today and Discover cannot read it for everyone;
 *  replace this with the backend's horizon state when /beginner/horizons exists (Phase 3, Task 3). */
export const MODEL_STATUS =
  'Model status: Experimental, unproven. It failed its frozen test on past data (Jul 2023 to Jan 2025): it ' +
  'beat simply buying every stock in only 7 of 21 periods, and made money after costs in only 9 of 21.'

export const NA = 'Not available'

/** True only when the API sent a calibrated chance: measured on unseen days, or M06's own calibrated score. */
export function isCalibrated(d: BrainDecision): boolean {
  const h = d.honest_score
  return !!h && (h.status === 'measured' || h.status === 'calibrated') && h.honest_chance != null
}

// The raw-score scrubber lives with the other score wording (ux10); re-exported here for the card.
export { withoutScorePercent } from '../scoreText'

const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** "2026-11-06" → "Fri 6 Nov 2026" (a calendar date from the backend, no time zone); the input as-is when it
 *  is not a date. */
export function dayText(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso)
  if (!m) return iso
  const [y, mo, d] = [Number(m[1]), Number(m[2]), Number(m[3])]
  const day = new Date(Date.UTC(y, mo - 1, d))
  if (day.getUTCMonth() !== mo - 1) return iso
  return `${WEEKDAYS[day.getUTCDay()]} ${d} ${MONTHS[mo - 1]} ${y}`
}

/** Words the card must never use about the model or its signals (it has not passed its test). */
export const BANNED_CLAIMS = /\b(validated|proven|profitable|probability)\b/i
