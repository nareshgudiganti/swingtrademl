// Plain-English text for the Brain Observatory page (ob15). Display only: nothing here changes what the
// server returns or what the brain stores.
import type { ObsOutcomes, ObsRunDetail, ObsRunSummary } from '../api/types'

const UNFINISHED = new Set(['queued', 'running'])

/** How long the run took. A run that has not finished has no duration yet, never "0 s". */
export function runDuration(run: Pick<ObsRunSummary, 'status' | 'ms' | 'finished_at'>): string {
  if (UNFINISHED.has(run.status) || !run.finished_at) return 'not finished yet'
  if (run.ms == null || run.ms <= 0) return 'time taken not recorded'
  return `${Math.round(run.ms / 1000)} s`
}

/** A stored UTC time shown as India time, e.g. "15:50 IST". */
export function timeIst(iso: string | null | undefined): string {
  if (!iso) return 'time not recorded'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return 'time not recorded'
  const hm = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).format(d)
  return `${hm} IST`
}

const HEADLINE: Record<string, string> = {
  completed: 'Completed',
  degraded: 'Completed with problems',
  completed_unchecked: 'Finished — this run stored no module list, so missing modules cannot be checked',
  failed: 'Started and failed',
  running: 'Not finished yet',
  queued: 'Waiting to start',
}

export function headlineText(headline: string): string {
  return HEADLINE[headline] ?? headline
}

function count(r: ObsRunDetail, key: string): number {
  const v = r.counts[key]
  return typeof v === 'number' ? v : 0
}

/** Why a finished run is "Completed with problems": each cause by name. Empty for any other headline. */
export function problemCauses(r: ObsRunDetail): string[] {
  if (r.headline !== 'degraded') return []
  const out: string[] = []
  const failed = r.modules.filter((m) => m.flags.failed).map((m) => m.module_id)
  const missing = r.modules.filter((m) => m.flags.not_observed).map((m) => m.module_id)
  const conflicting = r.modules.filter((m) => m.flags.conflicting).map((m) => m.module_id)
  if (failed.length) out.push(`${failed.length} module(s) failed: ${failed.join(', ')}`)
  if (missing.length) out.push(`${missing.length} module(s) expected but not seen in the step log: ${missing.join(', ')}`)
  if (conflicting.length) out.push(`${conflicting.length} module(s) with conflicting records: ${conflicting.join(', ')}`)
  if (r.step_fallbacks.length) {
    out.push(`${r.step_fallbacks.length} step(s) fell back to the safe default: ${r.step_fallbacks.map((f) => f.step).join(', ')}`)
  }
  return out
}

/** "N not observed", unless the run stored no module list: then nothing can be called missing. */
export function notObservedText(r: ObsRunDetail): string {
  if (count(r, 'unknown') > 0) return 'not observed: cannot tell (no module list stored)'
  return `${count(r, 'not_observed')} not observed (inferred)`
}

/** A count the server could not work out comes back empty; say so instead of printing "null". */
export function countOrUnknown(n: number | null | undefined, what: string): string {
  return n == null ? `an unknown number of ${what} (could not be read)` : `${n} ${what}`
}

/** The Results tab's figures. "Every stock" is the average of every stock the brain looked at; the random
 *  baseline is "Random 5 a day". */
export const FIGURE_LABELS = {
  candidate: 'Brain TRADE ideas',
  every_stock: 'Every stock the brain looked at (average)',
  random_5: 'Random 5 a day',
  momentum_5: 'Momentum 5 a day',
  nifty_matched: "NIFTY over each idea's own holding days",
  cash: 'Cash',
} as const

export function excludedText(x: NonNullable<ObsOutcomes['excluded']>): string {
  return `Excluded, not mixed in: ${countOrUnknown(x.other_stage_days, 'day(s) in another stage')}, ` +
    `${countOrUnknown(x.other_book_runs, 'run(s) in another book')}.`
}
