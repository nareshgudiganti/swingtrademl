// The new look's Discover (pages/DiscoverNew.tsx): counts, filters and "Where it stopped" for every idea in the
// brain's latest run. Pure functions, no hooks, built only from what the brain stored.
//
// Honesty rules: "Where it stopped" is the step whose STORED reason holds the idea back (stopOf in brainSteps.ts).
// A TRADE passed every check. When nothing stored says why, it says "Not recorded", never a guessed step.
// The score is a ranking among tonight's ideas, never a chance of profit.

import type { BrainDecision, IdeaWord } from '../api/types'
import { stopOf } from './brainSteps'
import { finalWord } from './live'

export type DiscoverFilter = 'ALL' | IdeaWord
export const DISCOVER_FILTERS: DiscoverFilter[] = ['ALL', 'TRADE', 'WATCH', 'WAIT', 'AVOID']

/** The short label for each of the brain's first seven steps (brainSteps.ts STEP_TITLES), as a stopping point. */
export const STOP_LABEL: Record<number, string> = {
  1: 'Data check',
  2: 'Market',
  3: 'Situation',
  4: 'Similar cases',
  5: 'Model check',
  6: 'Safety check',
  7: 'Decision',
}

export type StopTone = 'pass' | 'early' | 'late' | 'none'
export type WhereStopped = { label: string; step: number | null; tone: StopTone; why: string | null }

/** Where the brain stopped this idea: "Passed" for a TRADE, else the step its stored reason points to. */
export function whereItStopped(d: BrainDecision): WhereStopped {
  if (finalWord(d) === 'TRADE') return { label: 'Passed', step: null, tone: 'pass', why: null }
  const stop = stopOf(d)
  if (!stop) return { label: 'Not recorded', step: null, tone: 'none', why: null }
  // Steps 6-7 come after the model liked it (the account's safety limits, the final word): "late" = nearly there.
  return { label: STOP_LABEL[stop.step] ?? 'Decision', step: stop.step, tone: stop.step >= 6 ? 'late' : 'early', why: stop.why.text }
}

/** How many ideas carry each word (after any owner overrule), plus the total. */
export function discoverCounts(ideas: BrainDecision[]): Record<DiscoverFilter, number> {
  const c: Record<DiscoverFilter, number> = { ALL: ideas.length, TRADE: 0, WATCH: 0, WAIT: 0, AVOID: 0 }
  for (const d of ideas) {
    const w = finalWord(d) as IdeaWord
    if (w in c) c[w] += 1
  }
  return c
}

/** The ideas to list for a word filter, a sector (null = all) and a search box. `sectorOf` maps SYMBOL → sector. */
export function filterIdeas(
  ideas: BrainDecision[],
  opts: { filter: DiscoverFilter; sector?: string | null; query?: string; sectorOf?: Record<string, string | null> },
): BrainDecision[] {
  const q = (opts.query ?? '').trim().toUpperCase()
  return ideas.filter(
    (d) =>
      (opts.filter === 'ALL' || finalWord(d) === opts.filter) &&
      (!opts.sector || opts.sectorOf?.[d.symbol.toUpperCase()] === opts.sector) &&
      (q === '' || d.symbol.toUpperCase().includes(q)),
  )
}

/** The sectors present among these ideas, alphabetically; [] when no sector is known (the filter is then hidden). */
export function sectorsIn(ideas: BrainDecision[], sectorOf: Record<string, string | null> | undefined): string[] {
  if (!sectorOf) return []
  const set = new Set<string>()
  for (const d of ideas) {
    const s = sectorOf[d.symbol.toUpperCase()]
    if (s) set.add(s)
  }
  return [...set].sort((a, b) => a.localeCompare(b))
}

/** The footer line under the table: the checks in order, and what the score is not. */
export const DISCOVER_FOOT =
  'Each stock goes through the brain’s checks in order: data check → market → situation → similar cases → model ' +
  'check → safety check → decision. “Where it stopped” is the first check that held it back, from the reason the ' +
  'brain stored. The score ranks tonight’s stocks against each other; it is not a chance of profit.'
