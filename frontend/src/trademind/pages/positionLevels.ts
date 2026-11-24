// Where an open position sits between its stop, half-profit mark and target.
// Display only: nothing here sells or changes a stop. The levels are the app's trading plan, read from the
// server (trademind/tradingRules.ts), never written here.

import { halfText, plan, stopText, targetText } from '../tradingRules'

/** The three lines in percent: stop (negative), half-profit, target. */
export function levels(): { stop: number; half: number; target: number } {
  const p = plan()
  return { stop: -p.stopPct, half: p.halfPct, target: p.targetPct }
}
/** "Near" means within this many percentage points of a line. */
const NEAR_PTS = 1

export type LevelState = 'stop' | 'near_stop' | 'target' | 'near_target' | 'half' | 'near_half' | 'watch' | 'hold'

export type Level = {
  state: LevelState
  /** Short tag for the table, e.g. "Near stop". */
  tag: string
  /** Headline for the Act Today card, e.g. "Near stop". */
  title: string
  /** One plain sentence on what to consider. */
  advice: string
  tone: 'red' | 'amber' | 'green' | 'blue' | 'grey'
  /** True when the owner may need to act today. */
  act: boolean
}

const pts = (n: number) => n.toFixed(1)

/** `retPct` is the return since purchase in percent (e.g. -3.5). */
export function levelFor(retPct: number, watch = false): Level {
  const { stop: STOP_PCT, half: HALF_PCT, target: TARGET_PCT } = levels()
  const days = plan().days
  if (retPct <= STOP_PCT)
    return { state: 'stop', tag: 'Stop reached', title: 'Stop reached', advice: `It hit your ${stopText()} stop. Consider selling now.`, tone: 'red', act: true }
  if (retPct >= TARGET_PCT)
    return { state: 'target', tag: 'Target reached', title: 'Target reached', advice: `It hit the ${targetText()} target of the app's ${days}-day plan. Consider booking profit.`, tone: 'green', act: true }
  if (retPct >= TARGET_PCT - NEAR_PTS)
    return { state: 'near_target', tag: 'Near target', title: 'Near target', advice: `${pts(TARGET_PCT - retPct)}% from your ${targetText()} target (${days}-day plan). Consider booking profit at the target.`, tone: 'green', act: true }
  if (retPct >= HALF_PCT)
    return { state: 'half', tag: 'Sell half', title: 'Half-profit reached', advice: `At or above ${halfText()}. Review selling half of your position.`, tone: 'amber', act: true }
  if (retPct <= STOP_PCT + NEAR_PTS)
    return { state: 'near_stop', tag: 'Near stop', title: 'Near stop', advice: `${pts(retPct - STOP_PCT)}% from your ${stopText()} stop. Consider selling if it falls further.`, tone: 'red', act: true }
  if (retPct >= HALF_PCT - NEAR_PTS)
    return { state: 'near_half', tag: 'Near half-profit', title: 'Near half-profit', advice: `${pts(HALF_PCT - retPct)}% from ${halfText()}. Be ready to sell half.`, tone: 'amber', act: true }
  if (watch) return { state: 'watch', tag: 'Watch', title: 'Watch', advice: 'The brain says watch this one.', tone: 'blue', act: false }
  return { state: 'hold', tag: 'Hold', title: 'Hold', advice: 'Nothing to do. Keep holding.', tone: 'grey', act: false }
}

/** Position of a return on the stop…target bar, 0–100. */
export function barPercent(retPct: number): number {
  const { stop, target } = levels()
  const v = ((retPct - stop) / (target - stop)) * 100
  return Math.max(0, Math.min(100, v))
}

export const priceAt = (entry: number, pct: number) => entry * (1 + pct / 100)
