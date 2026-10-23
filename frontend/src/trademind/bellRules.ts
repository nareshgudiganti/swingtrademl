// oa8: the top-bar bell and stage chip, the parts that are not drawing. Pure functions, so they are tested without a
// browser; TopBarAlerts.tsx draws them.
//
// "Seen" is kept in this browser only: the newest alert id the owner has opened the bell on. Nothing is written to
// the server or the database. If the browser will not store anything, every alert just counts as new again.

import type { BrainAlertRecord, BrainStageName } from '../api/types'

export const SEEN_KEY = 'tm.alerts.seen.v1'

function browserStorage(): Storage | undefined {
  try {
    return typeof window === 'undefined' ? undefined : window.localStorage
  } catch {
    return undefined
  }
}

/** The newest alert id already seen in this browser (0 = none, or storage blocked). */
export function readSeen(storage: Storage | undefined = browserStorage()): number {
  try {
    const n = Number(storage?.getItem(SEEN_KEY) ?? 0)
    return Number.isFinite(n) && n > 0 ? n : 0
  } catch {
    return 0
  }
}

/** Remember the newest alert seen. Never goes backwards; a blocked browser is silently ignored. */
export function writeSeen(id: number, storage: Storage | undefined = browserStorage()): void {
  try {
    if (!storage || id <= readSeen(storage)) return
    storage.setItem(SEEN_KEY, String(id))
  } catch {
    /* private window or blocked storage: nothing to remember */
  }
}

export function latestId(alerts: BrainAlertRecord[]): number {
  return alerts.reduce((m, a) => Math.max(m, a.id), 0)
}

export function unseenCount(alerts: BrainAlertRecord[], seenId: number): number {
  return alerts.filter((a) => a.id > seenId).length
}

/** The bell's name for a screen reader (and its tooltip). */
export function bellLabel(unseen: number): string {
  return unseen > 0 ? `Alerts, ${unseen} new` : 'Alerts'
}

const STAGES: Record<BrainStageName, { label: string; explain: string }> = {
  shadow: { label: 'Practice', explain: 'Practice: the brain records ideas but buys nothing.' },
  approval: { label: 'Approval', explain: 'Approval: the brain asks you before each buy.' },
  auto: { label: 'Auto', explain: 'Auto: the brain may buy on its own.' },
}

/** The stage chip's word, straight from /brain/stage. An unknown stage shows as-is rather than guessing. */
export function stageChip(stage: string): { label: string; explain: string } {
  return STAGES[stage as BrainStageName] ?? { label: stage, explain: stage }
}
