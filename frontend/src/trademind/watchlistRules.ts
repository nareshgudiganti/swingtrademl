// "My Watchlist" (new look, pages/WatchlistNew.tsx): each person's own list joined with the brain's latest run.
// Pure functions, no hooks. The list itself comes from GET /me/watchlist; tonight's word, score and "what it is
// waiting for" come only from the brain's stored decision for that stock. A stock the brain did not check tonight
// says so — nothing is guessed. This list never changes which stocks the bot trades.

import type { BrainDecision, BrainRun, MyWatchlistItem } from '../api/types'
import { stopOf } from './brainSteps'
import { finalWord, ideasFrom } from './live'
import { scoreRank, type ScoreRank } from './scoreText'
import { oneReason } from './today/answerRules'
import { changeLines } from './WhatWouldChange'

export type WatchTab = 'all' | 'watching' | 'close' | 'removed'

export type WatchRow = {
  item: MyWatchlistItem
  /** The brain's decision for this stock on its latest run, if it checked it. */
  decision: BrainDecision | null
  word: string | null
  rank: ScoreRank | null
  waitingFor: string
  close: boolean
  removed: boolean
}

export const NOT_CHECKED = 'The brain did not check this stock on its last run.'

/** A TRADE tonight, or an idea that passed every check up to the account's safety limits (stopped at step 6 only). */
export function isCloseToTrade(d: BrainDecision | null): boolean {
  if (!d || d.kind !== 'idea') return false
  if (finalWord(d) === 'TRADE') return true
  return stopOf(d)?.step === 6
}

/** "What it is waiting for": the first stored "what would change" line, else the one short reason. */
export function waitingFor(d: BrainDecision | null): string {
  if (!d) return NOT_CHECKED
  const word = finalWord(d)
  if (word === 'TRADE') return 'Nothing: it is a BUY on the brain’s last run.'
  const first = changeLines(d)[0]
  return first ? first.text : oneReason(d)
}

/** One row per stock on the list, with tonight's read from the run (when there is a run). */
export function watchRows(items: MyWatchlistItem[], run: BrainRun | undefined): WatchRow[] {
  const ideas = run ? ideasFrom(run) : []
  const dayScores = ideas.map((d) => d.confidence)
  const bySymbol = new Map((run?.decisions ?? []).map((d) => [d.symbol.toUpperCase(), d] as const))
  return items.map((item) => {
    const decision = bySymbol.get(item.symbol.toUpperCase()) ?? null
    return {
      item,
      decision,
      word: decision ? finalWord(decision) : null,
      rank: decision && decision.kind === 'idea' ? scoreRank(decision.confidence, dayScores) : null,
      waitingFor: run ? waitingFor(decision) : 'The brain’s last run could not be loaded.',
      close: isCloseToTrade(decision),
      removed: item.removed_at != null,
    }
  })
}

/** The rows for a tab. All = on the list now (Watching + Close to a TRADE); Removed = taken off. */
export function rowsFor(rows: WatchRow[], tab: WatchTab): WatchRow[] {
  switch (tab) {
    case 'all':
      return rows.filter((r) => !r.removed)
    case 'watching':
      return rows.filter((r) => !r.removed && !r.close)
    case 'close':
      return rows.filter((r) => !r.removed && r.close)
    case 'removed':
      return rows.filter((r) => r.removed)
  }
}

export function tabCounts(rows: WatchRow[]): Record<WatchTab, number> {
  return {
    all: rowsFor(rows, 'all').length,
    watching: rowsFor(rows, 'watching').length,
    close: rowsFor(rows, 'close').length,
    removed: rowsFor(rows, 'removed').length,
  }
}

/** "12 Oct" in India time. */
export function addedDate(iso: string): string {
  return new Intl.DateTimeFormat('en-IN', { day: 'numeric', month: 'short', timeZone: 'Asia/Kolkata' }).format(new Date(iso))
}
