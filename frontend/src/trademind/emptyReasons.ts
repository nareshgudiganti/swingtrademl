// Why a brain screen is empty, in plain words, built ONLY from what the API said. "No ideas today because the
// market is weak" and "the run failed" are different things and must never read the same. If the API does not
// say why, these return a neutral fact ("no stock passed the brain's checks"), never a made-up reason.

import type { BrainBanner, BrainHealth } from '../api/types'
import { formatDateTime } from '../lib/format'

/**
 * A note when the brain's NEWEST nightly run did not finish, so the screen is showing an older run.
 * /brain/runs/latest only returns finished runs; /brain/health reports the newest run of any status.
 */
export function runFailedNote(latestStartedAt: string | undefined, health: BrainHealth | undefined): string | null {
  const last = health?.last_run
  if (!last || last.kind !== 'nightly' || last.status !== 'failed') return null
  if (latestStartedAt && new Date(last.started_at).getTime() <= new Date(latestStartedAt).getTime()) return null
  const shown = latestStartedAt ? ` This page shows the earlier run from ${formatDateTime(latestStartedAt)}.` : ''
  return `The brain's newest run (${formatDateTime(last.started_at)}) did not finish.${shown}`
}

/**
 * Why there are no TRADE ideas (or no ideas at all) in a finished run. `ideaCount` = all ideas the run scored,
 * `tradeCount` = how many it said TRADE. Null when there ARE TRADE ideas (nothing to explain).
 */
export function noTradeReason(banner: BrainBanner, ideaCount: number, tradeCount: number): string | null {
  if (tradeCount > 0) return null
  const headline = banner.headline ? ` ${banner.headline}` : ''
  if (banner.mode === 'NO_NEW_TRADES') {
    return `No BUY ideas today: the brain is in "No new trades" mode, so it is not buying anything new. Stocks you hold are still watched.${headline}`
  }
  if (banner.mode === 'DEFENSIVE') {
    return `No BUY ideas today: the brain is in "Careful" mode (at most two new ideas, at half size) and no stock passed its checks.${headline}`
  }
  if (ideaCount === 0) return "The brain's last run had no stocks to look at, so there are no ideas."
  return "No BUY ideas today: none of the stocks passed the brain's checks. The others are listed as WATCH, WAIT or AVOID."
}
