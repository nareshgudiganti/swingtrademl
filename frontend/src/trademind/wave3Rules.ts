// New look, wave 3 (Market, Evidence, History, Admin home): the pure rules behind those pages, so they can be
// tested without a browser. Display only: nothing here changes a decision, an order, sizing, stops or limits.
//
// Honesty rules (owner, 2026-10-25):
//   * never invent a number: every figure comes from an API answer, or the line is left out;
//   * the brain's trial is sealed until its review (7 Nov 2026): counts only, never its profit or win rate;
//   * a score is a ranking, never a chance of profit;
//   * Paper and Real are always labelled and never added together.

import type { BrainDecision, BrainProposal, BrainRun, BrainSector, BrainStageName, DetailedPosition, Trade } from '../api/types'
import type { AdminJobs } from './jobs'
import { finalWord } from './live'
import { stopOf } from './brainSteps'
import { stoppedByRoom } from './today/answerRules'

// ------------------------------------------------------------------ trial --

/** The forward trial's first session (brain/trial_journal.py TRIAL_START). */
export const TRIAL_START = '2026-10-14'
/** Sessions the trial needs before it can be judged (trial_journal.MIN_SESSIONS). */
export const TRIAL_SESSIONS = 15
/** The planned review date: results stay sealed until then (owner plan; the server unseals only on approval). */
export const RESULTS_OPEN = '2026-11-07'
export const RESULTS_OPEN_TEXT = '7 Nov 2026'
export const TRIAL_START_TEXT = '14 Oct 2026'
/** Weekday market holidays inside the trial window (NSE). */
export const TRIAL_HOLIDAYS: readonly string[] = ['2026-10-20', '2026-11-10']

const iso = (d: Date) => d.toISOString().slice(0, 10)

/** Trading sessions (weekdays, not holidays) from TRIAL_START up to and including `asOf` (YYYY-MM-DD). */
export function trialSessionsSoFar(asOf: string, holidays: readonly string[] = TRIAL_HOLIDAYS): number {
  const end = asOf.slice(0, 10)
  if (end < TRIAL_START) return 0
  let n = 0
  const d = new Date(`${TRIAL_START}T00:00:00Z`)
  for (let guard = 0; guard < 400 && iso(d) <= end; guard += 1) {
    const day = d.getUTCDay()
    if (day !== 0 && day !== 6 && !holidays.includes(iso(d))) n += 1
    d.setUTCDate(d.getUTCDate() + 1)
  }
  return n
}

export type TrialProgress = { day: number; of: number; pct: number; finished: boolean; line: string }

/** "Trading day 7 of 15", counted on the market calendar up to the last finished trading day. */
export function trialProgress(asOf: string): TrialProgress {
  const n = trialSessionsSoFar(asOf)
  const day = Math.min(n, TRIAL_SESSIONS)
  const finished = n >= TRIAL_SESSIONS
  const line =
    n === 0
      ? 'The trial has not started yet'
      : finished
        ? `All ${TRIAL_SESSIONS} trading days are done. Results open on ${RESULTS_OPEN_TEXT}`
        : `Trading day ${day} of ${TRIAL_SESSIONS}`
  return { day, of: TRIAL_SESSIONS, pct: Math.round((day / TRIAL_SESSIONS) * 100), finished, line }
}

/** The scorecard is locked until the review date; after it, it still waits for the owner's review. */
export function scorecardLockText(today: string): string {
  return today < RESULTS_OPEN ? `Opens on ${RESULTS_OPEN_TEXT}, after the trial` : "Opens once the owner has reviewed the trial"
}

export const SEALED_RESULTS_TITLE = `Results are sealed until ${RESULTS_OPEN_TEXT}`
export const SEALED_RESULTS_TEXT =
  'Until then this page shows counts only: no profit and no win rate. Nobody sees how the brain’s picks did ' +
  'until the trial ends, so the test cannot be tweaked along the way.'

// ----------------------------------------------------------- run counts --

export type EvidenceCounts = { checked: number; passedModel: number; stoppedByRoom: number }

/** Did the model like this idea? Only when it reached the safety check: a TRADE, or stopped at the safety step. */
export function passedModelCheck(d: BrainDecision): boolean {
  if (finalWord(d) === 'TRADE' || d.word === 'TRADE') return true
  return stopOf(d)?.step === 6
}

/** Counts from the brain's latest run only. */
export function evidenceCounts(run: BrainRun): EvidenceCounts {
  const ideas = run.decisions.filter((d) => d.kind === 'idea')
  return {
    checked: ideas.length,
    passedModel: ideas.filter(passedModelCheck).length,
    stoppedByRoom: stoppedByRoom(ideas),
  }
}

// ------------------------------------------------------------------ stage --

export const STAGES: { id: BrainStageName; label: string; plain: string }[] = [
  { id: 'shadow', label: 'Practice', plain: 'The brain suggests; nothing is bought with real money.' },
  { id: 'approval', label: 'You approve each buy', plain: 'Every buy waits for your OK.' },
  { id: 'auto', label: 'Automatic', plain: 'The bot buys on its own, inside the safety limits.' },
]

export const STAGE_WORD: Record<BrainStageName, string> = {
  shadow: 'PRACTICE STAGE',
  approval: 'YOU APPROVE EACH BUY',
  auto: 'AUTOMATIC',
}

// ----------------------------------------------------------------- market --

export type MarketMode = 'NORMAL' | 'DEFENSIVE' | 'NO_NEW_TRADES'

export const LADDER: { mode: MarketMode; label: string; line: string; tone: 'green' | 'amber' | 'red' }[] = [
  { mode: 'NORMAL', label: 'Normal', line: 'New ideas at full size', tone: 'green' },
  { mode: 'DEFENSIVE', label: 'Careful', line: 'At most 2 new ideas, half size', tone: 'amber' },
  { mode: 'NO_NEW_TRADES', label: 'No new trades', line: 'No new buys at all', tone: 'red' },
]

/** "What this means for you": the stated rules of the mode (vocab.ts), plus the account's real invested limit. */
export function meansForYou(mode: string | null, investedLimitPct: number | null): string[] {
  const out: string[] = []
  if (mode === 'NORMAL') {
    out.push('Stocks that pass every check can become a TRADE.')
    out.push('Each new buy is the normal size.')
  } else if (mode === 'DEFENSIVE') {
    out.push('Fewer stocks will qualify as TRADE: at most two new ideas.')
    out.push('Each new buy is half the normal size.')
  } else if (mode === 'NO_NEW_TRADES') {
    out.push('No new buys at all until the market mode changes.')
  }
  if (investedLimitPct != null) {
    out.push(`At most ${Math.round(investedLimitPct)}% of the account can be invested right now (the account's safety limit).`)
  }
  out.push('Stocks already held are still watched and sold on their stop as usual.')
  if (mode && mode !== 'NORMAL') out.push('Waiting is often the right decision in this market.')
  return out
}

export type SectorRow = { key: string; name: string; pct: number | null; rotation: string }

/** Sectors strongest first by their 20-day change (sectors without a figure last, never guessed). */
export function sectorRows(sectors: BrainSector[]): SectorRow[] {
  return sectors
    .map((s) => ({ key: s.sector, name: s.name, pct: s.strength_20d == null ? null : s.strength_20d * 100, rotation: s.rotation }))
    .sort((a, b) => (b.pct ?? -Infinity) - (a.pct ?? -Infinity))
}

/** A bar from the centre line: half the track is the biggest move on the list. */
export function sectorBar(pct: number, maxAbs: number): { left: number; width: number } {
  const w = maxAbs > 0 ? Math.min(50, (Math.abs(pct) / maxAbs) * 50) : 0
  return pct >= 0 ? { left: 50, width: w } : { left: 50 - w, width: w }
}

export const pctText = (pct: number, digits = 1) => `${pct > 0 ? '+' : pct < 0 ? '−' : ''}${Math.abs(pct).toFixed(digits)}%`

// ---------------------------------------------------------------- history --

export type HistoryKind = 'paper' | 'botReal' | 'own' | 'cancelled'
export type HistoryTab = 'all' | 'bot' | 'own' | 'cancelled'
export type HistoryPeriod = 'month' | '3m' | 'all'
export type Tone = 'green' | 'red' | 'amber' | 'blue' | 'grey'

export type HistoryRow = {
  key: string
  /** When it was bought (or decided, for a cancelled idea): ISO. */
  date: string
  symbol: string
  kind: HistoryKind
  price: number | null
  why: string
  ended: string
  endedTone: Tone
  /** Result after charges, in %, only for a finished trade that is not sealed. */
  resultPct: number | null
  sealed: boolean
}

export const KIND_LABEL: Record<HistoryKind, string> = {
  paper: 'Paper buy',
  botReal: 'Bot buy (Real)',
  own: 'My own (Real)',
  cancelled: 'Cancelled',
}

// The same plain names as the classic Records page; anything else shows its code name without underscores.
const STRATEGY_PLAIN: Record<string, string> = {
  ml_swing_main: 'large companies model',
  ml_swing_midcap: 'mid-size companies model',
  ml_swing_smallcap: 'small companies model',
  sma_crossover_benchmark: 'simple yardstick (moving averages)',
  sma_crossover: 'simple yardstick (moving averages)',
  brain: 'TradeMind brain (practice)',
  long_term_value: 'long-term picks',
}

/** Why the bot bought it: the strategy that picked it (trades do not store a per-trade reason). */
export function botWhy(strategy: string | null): string {
  if (!strategy) return 'Bot pick (strategy not recorded)'
  return `Bot pick · ${STRATEGY_PLAIN[strategy] ?? strategy.replace(/_/g, ' ')}`
}

/** How a finished trade ended, from its stored exit reason only. */
export function endedText(reason: string | null, label: string | null, own: boolean): { text: string; tone: Tone } {
  switch (reason) {
    case 'TARGET_HIT':
      return { text: 'Target hit', tone: 'green' }
    case 'SCALE_OUT':
      return { text: 'Half sold at the first target', tone: 'green' }
    case 'STOP_LOSS_HIT':
      return { text: 'Stop hit', tone: 'red' }
    case 'TIME_STOP':
      return { text: 'Time exit (held too long)', tone: 'amber' }
    case 'SIGNAL_EXIT':
      return { text: 'Sold: the model changed its mind', tone: 'amber' }
    case 'RISK_LIMIT':
      return { text: 'Sold by a safety limit', tone: 'amber' }
    case 'MANUAL':
      return { text: own ? 'Sold by you' : 'Closed by hand', tone: 'grey' }
    default:
      return { text: label ?? reason ?? 'Not recorded', tone: 'grey' }
  }
}

/** A brain trade from the trial: its result is sealed like every other trial result. */
export function isSealedTrade(strategy: string | null, entryAt: string): boolean {
  return strategy === 'brain' && entryAt.slice(0, 10) >= TRIAL_START
}

export function tradeRow(t: Trade, own: boolean): HistoryRow {
  const sealed = !own && isSealedTrade(t.strategy_name, t.entry_at)
  const end = endedText(t.exit_reason, t.exit_reason_label, own)
  return {
    key: `${own ? 'own' : 'bot'}-t-${t.id}`,
    date: t.entry_at,
    symbol: t.symbol,
    kind: own ? 'own' : t.mode === 'paper' ? 'paper' : 'botReal',
    price: t.entry_price,
    why: own ? 'Your own pick' : botWhy(t.strategy_name),
    ended: `${end.text} · sold ${shortDate(t.exit_at)}`,
    endedTone: end.tone,
    resultPct: sealed ? null : t.return_pct * 100,
    sealed,
  }
}

export function openRow(p: DetailedPosition, own: boolean, paper: boolean): HistoryRow {
  const day = p.day_number && p.trade_limit_days ? ` · day ${p.day_number} of ${p.trade_limit_days}` : ''
  return {
    key: `${own ? 'own' : 'bot'}-p-${p.id}`,
    date: p.entry_at,
    symbol: p.symbol,
    kind: own ? 'own' : paper ? 'paper' : 'botReal',
    price: p.entry_price,
    why: own ? 'Your own pick' : botWhy(p.strategy_name),
    ended: `Still open${day}`,
    endedTone: 'blue',
    resultPct: null,
    sealed: !own && isSealedTrade(p.strategy_name, p.entry_at),
  }
}

export function cancelledRow(a: { id: number; symbol: string; decision_day: string; price: number; reason: string; status: string; status_plain: string }): HistoryRow {
  return {
    key: `c-${a.id}`,
    date: a.decision_day,
    symbol: a.symbol,
    kind: 'cancelled',
    price: a.price,
    why: a.reason,
    ended: `Not bought · ${a.status_plain || a.status}`,
    endedTone: 'grey',
    resultPct: null,
    sealed: false,
  }
}

export function inTab(r: HistoryRow, tab: HistoryTab): boolean {
  if (tab === 'all') return true
  if (tab === 'bot') return r.kind === 'paper' || r.kind === 'botReal'
  if (tab === 'own') return r.kind === 'own'
  return r.kind === 'cancelled'
}

/** `today` is YYYY-MM-DD in India. "This month" = the calendar month; "3 months" = the last 92 days. */
export function inPeriod(r: HistoryRow, period: HistoryPeriod, today: string): boolean {
  if (period === 'all') return true
  const d = istDate(r.date)
  if (period === 'month') return d.slice(0, 7) === today.slice(0, 7)
  const from = new Date(`${today}T00:00:00Z`)
  from.setUTCDate(from.getUTCDate() - 92)
  return d >= iso(from)
}

/** Newest first. */
export function sortRows(rows: HistoryRow[]): HistoryRow[] {
  return [...rows].sort((a, b) => istDate(b.date).localeCompare(istDate(a.date)) || b.key.localeCompare(a.key))
}

/** The India date of a timestamp (a bare YYYY-MM-DD is already one). */
export function istDate(ts: string): string {
  if (/^\d{4}-\d{2}-\d{2}$/.test(ts)) return ts
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return ts.slice(0, 10)
  return new Date(d.getTime() + 330 * 60_000).toISOString().slice(0, 10)
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
/** "22 Oct" (IST). */
export function shortDate(ts: string): string {
  const d = istDate(ts)
  return `${Number(d.slice(8, 10))} ${MONTHS[Number(d.slice(5, 7)) - 1]}`
}

/** "Step 8 · What the brain learned": counts and the sealed state only, never a hit rate or result. */
export function learnedLine(
  learning: { n_scored: number; n_scored_sealed?: number; sealed?: boolean } | undefined,
  proposals: BrainProposal[] | undefined,
): string {
  const parts: string[] = []
  if (learning) {
    const sealedN = learning.n_scored_sealed ?? 0
    parts.push(
      `${learning.n_scored} finished ${learning.n_scored === 1 ? 'idea has' : 'ideas have'} been scored against what the brain expected` +
        (learning.sealed && sealedN > 0 ? `, plus ${sealedN} from the trial that are counted only (sealed).` : '.'),
    )
  }
  if (proposals) {
    const open = proposals.filter((p) => p.status === 'open')
    const sealed = open.filter((p) => p.sealed).length
    if (open.length === 0) parts.push('No suggested changes are waiting.')
    else {
      const head = `${open.length} suggested ${open.length === 1 ? 'change is' : 'changes are'} waiting`
      const tail =
        sealed === 0
          ? '.'
          : sealed === open.length
            ? ', sealed until the trial ends.'
            : ` (${sealed} of them sealed until the trial ends).`
      parts.push(head + tail)
    }
  }
  parts.push('Nothing changes by itself: a change happens only when the owner accepts it.')
  return parts.join(' ')
}

// ------------------------------------------------------------------ admin --

export type StatusTone = 'green' | 'red' | 'amber' | 'blue' | 'grey'
export type StatusRow = { id: string; label: string; value: string; tone: StatusTone; note?: string }

/** The nightly jobs in one word: stopped worker or a failed job first. */
export function jobsWord(jobs: AdminJobs | undefined): { value: string; tone: StatusTone; note?: string } {
  if (!jobs) return { value: 'COULD NOT CHECK', tone: 'grey' }
  if (!jobs.worker_alive) return { value: 'WORKER STOPPED', tone: 'red', note: 'The job runner is not running.' }
  const failed = jobs.jobs.filter((j) => j.last_status === 'failed')
  if (failed.length > 0)
    return { value: `${failed.length} FAILED`, tone: 'red', note: `Last run failed: ${failed.map((j) => j.name).join(', ')}.` }
  if (jobs.jobs.some((j) => j.running_since)) return { value: 'RUNNING NOW', tone: 'blue' }
  return { value: 'ALL FINISHED', tone: 'green' }
}

export type AdminInput = {
  status?: { trading_mode: string; live_trading_enabled: boolean; broker_authenticated: boolean; scheduler_running: boolean }
  pricesTone?: 'fresh' | 'stale'
  pricesLabel?: string
  jobs?: AdminJobs
  jobsError?: boolean
  stage?: BrainStageName
  brainLastOk?: string | null
  brainFailed7d?: number
}

/** The status rows, each from a real answer; "COULD NOT CHECK" when that answer is missing. */
export function adminStatusRows(i: AdminInput): StatusRow[] {
  const unknown = (id: string, label: string): StatusRow => ({ id, label, value: 'COULD NOT CHECK', tone: 'grey' })
  const rows: StatusRow[] = []
  const s = i.status
  if (s) {
    const paper = s.trading_mode === 'paper'
    rows.push({
      id: 'mode',
      label: 'App mode',
      value: paper ? 'PRACTICE (PAPER)' : 'REAL MONEY',
      tone: paper ? 'green' : 'red',
      note: paper ? 'Every bot trade uses practice money.' : 'The server is NOT in paper mode.',
    })
    const realOrders = !paper || s.live_trading_enabled
    rows.push({
      id: 'real-orders',
      label: 'Real-money orders by the bot',
      value: realOrders ? 'ON' : 'OFF',
      tone: realOrders ? 'red' : 'green',
      note: realOrders ? 'The bot may place real orders.' : 'Going live is the owner’s decision only.',
    })
    rows.push({
      id: 'zerodha',
      label: 'Zerodha login',
      value: s.broker_authenticated ? 'CONNECTED' : 'NOT LOGGED IN',
      tone: s.broker_authenticated ? 'green' : 'amber',
    })
  } else {
    rows.push(unknown('mode', 'App mode'), unknown('real-orders', 'Real-money orders by the bot'), unknown('zerodha', 'Zerodha login'))
  }
  rows.push(
    i.pricesTone
      ? {
          id: 'prices',
          label: 'Prices',
          value: i.pricesTone === 'fresh' ? 'UP TO DATE' : 'OUT OF DATE',
          tone: i.pricesTone === 'fresh' ? 'green' : 'amber',
          note: i.pricesLabel,
        }
      : unknown('prices', 'Prices'),
  )
  if (s && !s.scheduler_running) {
    rows.push({ id: 'jobs', label: 'Nightly jobs', value: 'SCHEDULER OFF', tone: 'red', note: 'Scheduled jobs are not running.' })
  } else if (i.jobsError || i.jobs) {
    rows.push({ id: 'jobs', label: 'Nightly jobs', ...jobsWord(i.jobs) })
  } else {
    rows.push(unknown('jobs', 'Nightly jobs'))
  }
  const brainNote =
    i.brainLastOk !== undefined
      ? `${i.brainLastOk ? 'Last good nightly run recorded.' : 'No good nightly run recorded yet.'}${i.brainFailed7d ? ` ${i.brainFailed7d} failed run${i.brainFailed7d === 1 ? '' : 's'} in the last 7 days.` : ''}`
      : undefined
  rows.push(
    i.stage
      ? { id: 'brain', label: 'Brain', value: STAGE_WORD[i.stage], tone: i.stage === 'shadow' ? 'blue' : 'amber', note: brainNote }
      : { ...unknown('brain', 'Brain'), note: brainNote },
  )
  return rows
}
