// The new look's Today (pages/TodayNew.tsx): the headline sentence and the small counts behind it. Pure functions,
// built only from the brain's latest run. Nothing is invented: no chance, no profit figure (the trial is sealed).

import type { BrainDecision, IdeaWord, MarketMode } from '../../api/types'
import { withoutScorePercent } from '../scoreText'
import { finalWord } from '../live'
import { whyNotTrade } from '../whyNotTrade'

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`

/** One sentence that answers "what do I do today?". Counts are the 15-day ideas (the only window with a strategy). */
export function todayHeadline(
  mode: MarketMode | null,
  counts: Record<IdeaWord, number>,
  holdingsToReview: number,
): string {
  let first: string
  if (counts.TRADE > 0) first = `${plural(counts.TRADE, 'new trade idea', 'new trade ideas')} today.`
  else if (mode === 'NO_NEW_TRADES') first = 'No new trades today: the brain is not buying while the market is this risky.'
  else if (mode === 'DEFENSIVE') first = 'Careful market: no new trades today.'
  else first = 'No new trades today.'
  const rest: string[] = []
  if (counts.WATCH > 0) rest.push(`${plural(counts.WATCH, 'stock', 'stocks')} to watch`)
  if (holdingsToReview > 0) rest.push(`${plural(holdingsToReview, 'holding needs', 'holdings need')} a look`)
  return rest.length ? `${first} ${rest.join(', ')}.` : first
}

/** Ideas the brain liked but the account's safety limits had no room for (the stored "risk check said no" line). */
export function stoppedByRoom(ideas: BrainDecision[]): number {
  return ideas.filter((d) => whyNotTrade(d).some((w) => w.kind === 'risk_no_room')).length
}

/** The one short reason shown on an idea row: the first stored reason in plain words, never a raw score. */
export function oneReason(d: BrainDecision): string {
  const word = finalWord(d)
  if (word !== 'TRADE') {
    const why = whyNotTrade(d)[0]
    if (why) return why.text
  }
  return d.reasons[0] ? withoutScorePercent(d.reasons[0]) : 'No reason was stored.'
}

/** "Good morning" / "Good afternoon" / "Good evening" by the hour in India. */
export function greeting(now: Date = new Date()): string {
  const hour = Number(new Intl.DateTimeFormat('en-GB', { hour: 'numeric', hour12: false, timeZone: 'Asia/Kolkata' }).format(now))
  if (hour < 12) return 'Good morning'
  if (hour < 17) return 'Good afternoon'
  return 'Good evening'
}
