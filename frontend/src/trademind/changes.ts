// "What changed since yesterday" (ux11): today's live nightly brain ideas next to the previous trading
// day's (GET /brain/changes, read only). Pure mappers + one query hook.
//
// Scores are shown only as a place in the day's ranking ("3rd of 120"), never as a percentage: the raw
// model score is a ranking, not a chance (honest.tsx). No results of ideas are shown or even sent.

import { useQuery } from '@tanstack/react-query'

import { api } from '../api/client'
import { whyKey, whyNotTrade, type WhyItem } from './whyNotTrade'

export interface BrainChangeSide {
  word: string
  brain_word: string
  overruled_word: string | null
  overrule_reason: string | null
  reasons: string[]
  downgraded_from: string | null
  downgrade_reason: string | null
  rank: number | null
  rank_of: number | null
  score_kind: string | null
}

export interface BrainChangeRow {
  symbol: string
  now: BrainChangeSide | null
  before: BrainChangeSide | null
  held_now: boolean
}

export interface BrainChangeRun {
  run_id: string
  as_of: string
  day: string
  banner_mode: string | null
}

export interface BrainChanges {
  comparable: boolean
  note: string | null
  current: BrainChangeRun | null
  previous: BrainChangeRun | null
  ideas: BrainChangeRow[]
}

export type ChangeKind = 'new' | 'dropped' | 'held' | 'word' | 'reason' | 'rank' | 'same'

export type IdeaChange = {
  symbol: string
  kind: ChangeKind
  wordBefore: string | null
  wordNow: string | null
  whyBefore: WhyItem[]
  whyNow: WhyItem[]
  /** Places moved in the ranking: positive = up. Null when either day has no comparable place. */
  placesMoved: number | null
  rankBefore: { rank: number; of: number } | null
  rankNow: { rank: number; of: number } | null
}

/** A move this many places or more counts as a big move in the Today summary. */
export const BIG_MOVE = 10

function rankOf(side: BrainChangeSide | null): { rank: number; of: number } | null {
  return side && side.rank != null && side.rank_of != null ? { rank: side.rank, of: side.rank_of } : null
}

export function ideaChange(row: BrainChangeRow): IdeaChange {
  const { now, before } = row
  const whyBefore = before ? whyNotTrade(before) : []
  const whyNow = now ? whyNotTrade(now) : []
  const rankBefore = rankOf(before)
  const rankNow = rankOf(now)
  const sameScale = !!(now && before && now.score_kind === before.score_kind)
  const placesMoved = rankBefore && rankNow && sameScale ? rankBefore.rank - rankNow.rank : null

  let kind: ChangeKind
  if (!before) kind = 'new'
  else if (!now) kind = row.held_now ? 'held' : 'dropped'
  else if (now.word !== before.word) kind = 'word'
  else if (now.word !== 'TRADE' && whyKey(whyNow) !== whyKey(whyBefore)) kind = 'reason'
  else if (placesMoved) kind = 'rank'
  else kind = 'same'

  return {
    symbol: row.symbol,
    kind,
    wordBefore: before?.word ?? null,
    wordNow: now?.word ?? null,
    whyBefore,
    whyNow,
    placesMoved,
    rankBefore,
    rankNow,
  }
}

export function ordinal(n: number): string {
  const tens = n % 100
  if (tens >= 11 && tens <= 13) return `${n}th`
  return `${n}${['th', 'st', 'nd', 'rd'][n % 10] ?? 'th'}`
}

/** "Moved up 12 places in the ranking (now 3rd of 120, was 15th)." — or null when there is no move to tell. */
export function rankLine(c: IdeaChange): string | null {
  if (c.placesMoved == null || c.rankNow == null || c.rankBefore == null) return null
  const where = `now ${ordinal(c.rankNow.rank)} of ${c.rankNow.of}, was ${ordinal(c.rankBefore.rank)}`
  if (c.placesMoved === 0) return `Same place in the ranking (${where}).`
  const n = Math.abs(c.placesMoved)
  return `Moved ${c.placesMoved > 0 ? 'up' : 'down'} ${n} ${n === 1 ? 'place' : 'places'} in the ranking (${where}).`
}

/** The main line for one idea, in plain words. */
export function changeHeadline(c: IdeaChange): string {
  switch (c.kind) {
    case 'new':
      return `New today: the brain did not list it yesterday. Today it says ${c.wordNow}.`
    case 'dropped':
      return `No longer on the list today (yesterday it was ${c.wordBefore}).`
    case 'held':
      return `Now one of the stocks held, so it is no longer listed as an idea (yesterday it was ${c.wordBefore}).`
    case 'word':
      return `Changed from ${c.wordBefore} yesterday to ${c.wordNow} today.`
    case 'reason':
      return `Still ${c.wordNow}, but for a different reason than yesterday.`
    case 'rank':
      return `Still ${c.wordNow}, for the same reason as yesterday.`
    case 'same':
      return `No change since yesterday: still ${c.wordNow}.`
  }
}

export type ChangesSummary = {
  wordChanged: IdeaChange[]
  newToday: IdeaChange[]
  dropped: IdeaChange[]
  held: IdeaChange[]
  reasonChanged: IdeaChange[]
  bigMoves: IdeaChange[]
}

export function summarize(changes: IdeaChange[]): ChangesSummary {
  return {
    wordChanged: changes.filter((c) => c.kind === 'word'),
    newToday: changes.filter((c) => c.kind === 'new'),
    dropped: changes.filter((c) => c.kind === 'dropped'),
    held: changes.filter((c) => c.kind === 'held'),
    reasonChanged: changes.filter((c) => c.kind === 'reason'),
    bigMoves: changes.filter((c) => c.placesMoved != null && Math.abs(c.placesMoved) >= BIG_MOVE),
  }
}

/** Changes for the run a screen is showing. Cached per run; read only. */
export function useChanges(runId?: string) {
  return useQuery({
    queryKey: ['brainChanges', runId],
    queryFn: () => api.brainChanges(runId!),
    enabled: !!runId,
    retry: false,
    staleTime: 5 * 60_000,
  })
}
