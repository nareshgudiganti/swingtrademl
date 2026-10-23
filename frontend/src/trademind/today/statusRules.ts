// oa5: the safety half of Today's status strip, as plain lines. Pure (tested); StatusStrip.tsx draws them.
// Display only: nothing here switches anything. Every unknown says so and leans towards caution: a switch that
// could not be read is "treat new buys as paused", never "on".

import type { BrainStage, SystemState } from '../../api/types'
import { stageChip } from '../bellRules'

export type Tone = 'green' | 'amber' | 'red' | 'blue'
export type SafetyLine = { id: 'kill-switch' | 'drawdown' | 'stage'; label: string; value: string; note?: string; tone: Tone; to: string }

export function killSwitchLine(state: SystemState | undefined, failed: boolean): SafetyLine {
  const base = { id: 'kill-switch' as const, label: 'New buys', to: '/trademind/control' }
  if (failed) return { ...base, value: 'Could not check', note: 'The safety switch could not be read. Treat new buys as paused.', tone: 'red' }
  if (!state) return { ...base, value: 'Checking…', tone: 'blue' }
  const exitsOff = state.exits_enabled ? undefined : 'Automatic selling at the stop or target is switched off.'
  if (!state.new_entries_enabled) {
    const why = [state.halt_reason, state.halted_by ? `by ${state.halted_by}` : null].filter(Boolean).join(', ')
    return {
      ...base,
      value: 'Paused by the kill switch',
      note: [why ? `Reason: ${why}.` : 'No reason was given.', exitsOff].filter(Boolean).join(' '),
      tone: 'red',
    }
  }
  return { ...base, value: 'Allowed', note: exitsOff, tone: exitsOff ? 'amber' : 'green' }
}

/**
 * `ddPct`: how far the paper account is below its peak, in % (null when there is no history yet).
 * `haltPct`: the drawdown at which new buys stop, in % (null when the limits could not be read).
 */
export function drawdownLine(ddPct: number | null, haltPct: number | null, failed: boolean): SafetyLine {
  const base = { id: 'drawdown' as const, label: 'Drawdown (paper)', to: '/trademind/risk' }
  if (failed) return { ...base, value: 'Not available', note: 'The account history or the limit could not be loaded.', tone: 'amber' }
  if (ddPct == null || haltPct == null) {
    return { ...base, value: 'Not available', note: ddPct == null ? 'No account history yet.' : 'Checking the limit…', tone: 'blue' }
  }
  const dd = Math.max(0, ddPct)
  if (dd >= haltPct) {
    return {
      ...base,
      value: `${dd.toFixed(1)}% below its peak`,
      note: `At the ${haltPct.toFixed(0)}% halt: new buys are paused until it recovers.`,
      tone: 'red',
    }
  }
  return {
    ...base,
    value: `${dd.toFixed(1)}% below its peak`,
    note: `New buys stop at ${haltPct.toFixed(0)}%.`,
    tone: dd >= haltPct * (2 / 3) ? 'amber' : 'green',
  }
}

export function stageLine(stage: BrainStage | undefined, failed: boolean): SafetyLine {
  const base = { id: 'stage' as const, label: 'Trading stage', to: '/trademind/golive' }
  if (failed) return { ...base, value: 'Not available', note: 'The stage could not be loaded.', tone: 'amber' }
  if (!stage) return { ...base, value: 'Checking…', tone: 'blue' }
  const chip = stageChip(stage.stage)
  return { ...base, value: chip.label, note: stage.plain || chip.explain, tone: stage.stage === 'shadow' ? 'blue' : 'amber' }
}
