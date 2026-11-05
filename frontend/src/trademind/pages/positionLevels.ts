// Where an open position sits between its stop (-4%), half-profit mark (+5%) and target (+8%).
// Display only: nothing here sells or changes a stop. Levels are the settled trading rules (CLAUDE.md).

export const STOP_PCT = -4
export const HALF_PCT = 5
export const TARGET_PCT = 8
/** "Near" means within this many percentage points of a line. */
export const NEAR_PTS = 1

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
  if (retPct <= STOP_PCT)
    return { state: 'stop', tag: 'Stop reached', title: 'Stop reached', advice: 'It hit your −4% stop. Consider selling now.', tone: 'red', act: true }
  if (retPct >= TARGET_PCT)
    return { state: 'target', tag: 'Target reached', title: 'Target reached', advice: 'It hit the +8% target. Consider booking profit.', tone: 'green', act: true }
  if (retPct >= TARGET_PCT - NEAR_PTS)
    return { state: 'near_target', tag: 'Near target', title: 'Near target', advice: `${pts(TARGET_PCT - retPct)}% from your +8% target. Consider booking profit at the target.`, tone: 'green', act: true }
  if (retPct >= HALF_PCT)
    return { state: 'half', tag: 'Sell half', title: 'Half-profit reached', advice: 'At or above +5%. Review selling half of your position.', tone: 'amber', act: true }
  if (retPct <= STOP_PCT + NEAR_PTS)
    return { state: 'near_stop', tag: 'Near stop', title: 'Near stop', advice: `${pts(retPct - STOP_PCT)}% from your −4% stop. Consider selling if it falls further.`, tone: 'red', act: true }
  if (retPct >= HALF_PCT - NEAR_PTS)
    return { state: 'near_half', tag: 'Near half-profit', title: 'Near half-profit', advice: `${pts(HALF_PCT - retPct)}% from +5%. Be ready to sell half.`, tone: 'amber', act: true }
  if (watch) return { state: 'watch', tag: 'Watch', title: 'Watch', advice: 'The brain says watch this one.', tone: 'blue', act: false }
  return { state: 'hold', tag: 'Hold', title: 'Hold', advice: 'Nothing to do. Keep holding.', tone: 'grey', act: false }
}

/** Position of a return on the −4%…+8% bar, 0–100. */
export function barPercent(retPct: number): number {
  const v = ((retPct - STOP_PCT) / (TARGET_PCT - STOP_PCT)) * 100
  return Math.max(0, Math.min(100, v))
}

export const priceAt = (entry: number, pct: number) => entry * (1 + pct / 100)
