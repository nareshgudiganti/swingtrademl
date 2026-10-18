// Admin > Jobs: types and plain-English formatting for the scheduled-jobs table. Pure, so it can be tested.
// Every time is shown in India time (IST), whatever the viewer's own clock is set to.

export type JobRow = {
  id: string
  name: string
  about: string
  registered: boolean
  schedule: string | null
  next_run: string | null
  last_started_at: string | null
  last_finished_at: string | null
  last_duration_s: number | null
  last_status: 'ok' | 'failed' | null
  last_error_kind: string | null
  running_since: string | null
  last_missed_at: string | null
  last_skipped_at: string | null
}

export type AdminJobs = {
  generated_at: string
  worker_alive: boolean
  runs_available: boolean
  jobs: JobRow[]
}

export type Tone = 'green' | 'amber' | 'red' | 'blue' | 'violet'

const IST_FORMAT = new Intl.DateTimeFormat('en-IN', {
  timeZone: 'Asia/Kolkata',
  day: '2-digit',
  month: 'short',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
})

/** "2026-10-19T10:10:00Z" -> "19 Oct, 15:40" (IST). Empty or bad input -> "—". */
export function formatIST(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  const parts = Object.fromEntries(IST_FORMAT.formatToParts(d).map((p) => [p.type, p.value]))
  return `${parts.day} ${parts.month}, ${parts.hour === '24' ? '00' : parts.hour}:${parts.minute}`
}

/** Seconds -> "under 1 s", "4.2 s", "3 min 12 s", "1 h 5 min". */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || Number.isNaN(seconds)) return '—'
  if (seconds < 1) return 'under 1 s'
  if (seconds < 60) return `${seconds < 10 ? seconds.toFixed(1) : Math.round(seconds)} s`
  const total = Math.round(seconds)
  if (total < 3600) {
    const m = Math.floor(total / 60)
    const s = total % 60
    return s ? `${m} min ${s} s` : `${m} min`
  }
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  return m ? `${h} h ${m} min` : `${h} h`
}

// Error kinds (Python class names) that have a plainer name. Anything else is shown as it is.
const ERROR_WORDS: Record<string, string> = {
  OperationalError: 'database problem',
  TimeoutError: 'timed out',
  ReadTimeout: 'timed out',
  ConnectTimeout: 'timed out',
  ConnectionError: 'could not connect',
  TokenException: 'Zerodha login expired',
  NetworkException: 'Zerodha not reachable',
  RunBusyError: 'another brain run was busy',
  HTTPError: 'a website refused',
}

export function errorWords(kind: string | null | undefined): string {
  if (!kind) return 'unknown error'
  return ERROR_WORDS[kind] ?? kind
}

const ms = (iso: string | null | undefined) => (iso ? new Date(iso).getTime() : Number.NaN)

/** What the last run means, as a short label and a colour. */
export function jobState(job: JobRow): { label: string; tone: Tone; detail?: string } {
  if (job.running_since) return { label: 'Running', tone: 'blue', detail: `since ${formatIST(job.running_since)}` }
  const started = ms(job.last_started_at)
  if (job.last_missed_at && !(ms(job.last_missed_at) <= started)) {
    return { label: 'Missed', tone: 'amber', detail: `was due ${formatIST(job.last_missed_at)}` }
  }
  if (job.last_skipped_at && !(ms(job.last_skipped_at) <= started)) {
    return { label: 'Skipped', tone: 'amber', detail: 'the previous run was still going' }
  }
  if (job.last_status === 'failed') return { label: 'Failed', tone: 'red', detail: errorWords(job.last_error_kind) }
  if (job.last_status === 'ok') return { label: 'OK', tone: 'green' }
  return { label: 'Not run yet', tone: 'violet', detail: 'no run recorded yet' }
}

/** "due now" when the snapshot's next run time has already passed (the list refreshes about once a minute). */
export function formatNext(iso: string | null | undefined, nowMs: number): string {
  if (!iso) return '—'
  return ms(iso) <= nowMs ? 'due now' : formatIST(iso)
}

export function countFailed(jobs: JobRow[]): number {
  return jobs.filter((j) => jobState(j).label === 'Failed').length
}
