// The brain chip in the top bar: says, in plain words, whether these screens show the brain's latest run.
// It says nothing about trading. It used to read "LIVE", which, next to the PRACTICE chip, looked like real-money
// trading was switched on. Pure data and one function, so the wording can be tested.

export type BrainStatus = 'live' | 'no-run' | 'off' | 'loading' | 'error'

export type StatusChip = { label: string; title: string; ok: boolean }

const NOT_TRADING = 'This is only about the information on screen; it does not mean real-money trading is on.'

export const STATUS_CHIP: Record<BrainStatus, StatusChip> = {
  live: { label: 'Brain: up to date', title: `The screens show the brain's latest run. ${NOT_TRADING}`, ok: true },
  'no-run': { label: 'Brain: no run yet', title: 'The brain is switched on but has not finished a run yet.', ok: false },
  off: { label: 'Brain is off', title: 'The brain is switched off on this server, so there are no brain results to show.', ok: false },
  loading: { label: 'Brain: checking…', title: 'Checking the connection to the brain.', ok: false },
  error: { label: "Brain: can't connect", title: 'Could not reach the brain. Try again in a minute.', ok: false },
}

/**
 * The chip for this status. `runAt` is the latest run's start time, already written for a person ("23 Oct, 18:05").
 * `refreshFailing`: a run is on screen but the last check for a newer one failed, so it may not be the latest.
 */
export function statusChip(status: BrainStatus, opts: { runAt?: string | null; refreshFailing?: boolean } = {}): StatusChip {
  const chip = STATUS_CHIP[status]
  if (status !== 'live') return chip
  const from = opts.runAt ? `, from ${opts.runAt}` : ''
  if (opts.refreshFailing) {
    return {
      label: "Brain: can't refresh",
      title: `Showing the brain's run${from}. The server can't be reached right now to check for a newer one.`,
      ok: false,
    }
  }
  return { ...chip, title: `The screens show the brain's latest run${from}. ${NOT_TRADING}` }
}
