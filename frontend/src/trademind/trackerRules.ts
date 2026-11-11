// Groww Tracker (pages/GrowwTracker.tsx): pure helpers for labels, filters, sorting, the stop-to-target bar and the
// "what to do" sentence. The status of each stock (stop / target / time / weak / ok) comes from the server and is
// never recomputed here. Every number can be null: show a dash, never NaN.

import type { TrackerState, WatchTrackerItem } from '../api/types'

export const STOP_PCT = -4
export const HALF_PCT = 5
export const TARGET_PCT = 8
/** The bar runs from -6% to +10%, so a stock past the stop or target still sits on it. */
export const BAR_LO = -6
export const BAR_HI = 10

export const STATE_LABEL: Record<TrackerState, string> = {
  stop: 'Near stop-loss',
  target: 'Reaching target',
  time: 'Time almost up',
  weak: 'Score falling',
  ok: 'On track',
}

/** The four "act today" cards, in the order of the mockup. */
export const ACT_CARDS: { state: Exclude<TrackerState, 'ok'>; title: string }[] = [
  { state: 'stop', title: 'Near stop-loss' },
  { state: 'target', title: 'Reaching target' },
  { state: 'time', title: 'Days almost done' },
  { state: 'weak', title: 'Score falling' },
]

export type TrackerFilter = 'all' | 'act' | Exclude<TrackerState, 'ok'>

export const FILTERS: { id: TrackerFilter; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'act', label: 'Needs action' },
  { id: 'stop', label: 'Near stop-loss' },
  { id: 'target', label: 'Reaching target' },
  { id: 'time', label: 'Days almost done' },
  { id: 'weak', label: 'Score falling' },
]

export function matchesFilter(item: WatchTrackerItem, filter: TrackerFilter): boolean {
  if (filter === 'all') return true
  if (filter === 'act') return item.state !== 'ok'
  return item.state === filter
}

export function filterItems(items: WatchTrackerItem[], filter: TrackerFilter): WatchTrackerItem[] {
  return items.filter((i) => matchesFilter(i, filter))
}

/** How many stocks need action (anything but "on track"). Drives the menu badge. */
export function needsActionCount(items: readonly WatchTrackerItem[] | undefined): number {
  return (items ?? []).filter((i) => i.state !== 'ok').length
}

export function symbolsIn(items: WatchTrackerItem[], state: TrackerState): string[] {
  return items.filter((i) => i.state === state).map((i) => i.symbol)
}

const URGENCY: Record<TrackerState, number> = { stop: 0, target: 1, time: 2, weak: 3, ok: 4 }

/** Stocks that need action first (stop, target, time, weak), then by most days done, then by symbol. */
export function sortItems(items: WatchTrackerItem[]): WatchTrackerItem[] {
  return [...items].sort(
    (a, b) => URGENCY[a.state] - URGENCY[b.state] || b.days_done - a.days_done || a.symbol.localeCompare(b.symbol),
  )
}

const isNum = (x: number | null | undefined): x is number => typeof x === 'number' && Number.isFinite(x)

/** "+3.2%", "−1.0%" (real minus sign) or "—" when unknown. */
export function fmtPct(x: number | null | undefined, digits = 1): string {
  if (!isNum(x)) return '—'
  const t = Math.abs(x).toFixed(digits)
  const zero = Number(t) === 0
  return `${x < 0 && !zero ? '−' : x > 0 && !zero ? '+' : ''}${t}%`
}

/** "₹4,210" (up to 2 decimals for cheap stocks) or "—". */
export function fmtPrice(x: number | null | undefined): string {
  if (!isNum(x)) return '—'
  return `₹${x.toLocaleString('en-IN', { maximumFractionDigits: x >= 1000 ? 0 : 2 })}`
}

export function signClass(x: number | null | undefined): 'pos' | 'neg' | 'dim' {
  if (!isNum(x) || x === 0) return 'dim'
  return x > 0 ? 'pos' : 'neg'
}

/** Stop and target prices, only when the entry price is known. */
export function stopTarget(entry: number | null | undefined): { stop: number; target: number } | null {
  if (!isNum(entry) || entry <= 0) return null
  return { stop: entry * 0.96, target: entry * 1.08 }
}

/** Where a value (in percent) sits on the stop-to-target bar, 0..100 (clamped). Null when unknown. */
export function barPosition(ret: number | null | undefined): number | null {
  if (!isNum(ret)) return null
  const x = Math.max(BAR_LO, Math.min(BAR_HI, ret))
  return ((x - BAR_LO) / (BAR_HI - BAR_LO)) * 100
}

export type DeltaView = { arrow: '▲' | '▼' | '–'; text: string; tone: 'pos' | 'neg' | 'dim' }

/** The up/down change in score since the day before. */
export function deltaView(delta: number | null | undefined): DeltaView {
  if (!isNum(delta)) return { arrow: '–', text: '—', tone: 'dim' }
  const r = Math.round(Math.abs(delta))
  if (delta > 0 && r > 0) return { arrow: '▲', text: String(r), tone: 'pos' }
  if (delta < 0 && r > 0) return { arrow: '▼', text: String(r), tone: 'neg' }
  return { arrow: '–', text: '0', tone: 'dim' }
}

export function scoreText(x: number | null | undefined): string {
  return isNum(x) ? String(Math.round(x)) : '—'
}

/** The day the stock is on: the day it was added is Day 1. */
export function dayNumber(item: Pick<WatchTrackerItem, 'days_done' | 'day_number'>): number {
  return item.day_number ?? item.days_done + 1
}

/** One dot per trading day of the plan; the last three are "late" (amber). */
export function pips(daysDone: number, horizon: number): { filled: boolean; late: boolean }[] {
  const n = Math.max(1, Math.round(horizon))
  const done = Math.max(0, Math.min(n, Math.round(daysDone)))
  return Array.from({ length: n }, (_, i) => ({ filled: i + 1 <= done, late: i + 1 > n - 3 }))
}

/** Plain-English "what to do", by the server's status. */
export function whatToDo(item: WatchTrackerItem, horizon: number): string {
  const ret = fmtPct(item.return_pct)
  const left = Math.max(0, horizon - item.days_done)
  switch (item.state) {
    case 'stop':
      return `${item.symbol} is ${ret} since you added it. The stop-loss is at −4%. If your Groww price is lower than this, sell in Groww to protect your money.`
    case 'target':
      return `${item.symbol} is ${ret}. The plan says sell half at +5% and the rest at +8%. Check Groww and book profit.`
    case 'time':
      return `Day ${dayNumber(item)} of ${horizon}. The plan is to exit by day ${horizon}, so decide this week.`
    case 'weak':
      return `The model score fell from ${scoreText(item.score_first)} to ${scoreText(item.score_today)} since you added it. The model likes it less each day. Price is ${ret}.`
    default:
      return `No action needed. Price is ${ret}, the score is ${scoreText(item.score_today)}, and ${left} trading days remain.`
  }
}

/** Parse the buy-price box. Empty text clears the price (null); anything unusable returns undefined. */
export function parseBuyPrice(text: string): number | null | undefined {
  const t = text.replace(/[₹,\s]/g, '')
  if (t === '') return null
  const n = Number(t)
  return Number.isFinite(n) && n > 0 ? n : undefined
}

/** Shares: empty clears (null); a number above 0 is kept; anything else is unusable (undefined). */
export function parseQuantity(text: string): number | null | undefined {
  const t = text.replace(/[,\s]/g, '')
  if (t === '') return null
  const n = Number(t)
  return Number.isFinite(n) && n > 0 && n <= 1e9 ? n : undefined
}

/** Signed rupees: "+₹1,250", "−₹300", or "—" when unknown. */
export function fmtMoney(x: number | null | undefined): string {
  if (!isNum(x)) return '—'
  const t = `₹${Math.abs(x).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
  return x <= -0.5 ? `−${t}` : x >= 0.5 ? `+${t}` : t
}

/** Plain rupees without a sign (for "invested"), or "—". */
export function fmtRupees(x: number | null | undefined): string {
  if (!isNum(x)) return '—'
  return `₹${x.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
}

/** A buy date (YYYY-MM-DD) as "28 Oct 2026", or "—" when missing or not a date. */
export function fmtBoughtOn(iso: string | null | undefined): string {
  if (!iso || !/^\d{4}-\d{2}-\d{2}$/.test(iso)) return '—'
  const d = new Date(`${iso}T00:00:00Z`)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })
}

/** The server refuses a buy date further back than this. */
export const MAX_BACKDATE_DAYS = 120

const addDaysIso = (iso: string, days: number): string => {
  const d = new Date(`${iso}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() + days)
  return d.toISOString().slice(0, 10)
}

/** Today's calendar date in India (YYYY-MM-DD), whatever the browser's time zone. */
export function todayIst(now: Date = new Date()): string {
  return new Date(now.getTime() + 5.5 * 3600 * 1000).toISOString().slice(0, 10)
}

export type EditForm = { boughtOn: string; price: string; quantity: string; note: string }
export type EditPatch = { buy_price?: number | null; quantity?: number | null; bought_on?: string; note?: string | null }
export type EditResult = { patch: EditPatch; errors: Partial<Record<keyof EditForm, string>>; changed: boolean }

export function formFromItem(item: WatchTrackerItem): EditForm {
  return {
    boughtOn: item.bought_on ?? '',
    price: isNum(item.buy_price) ? String(item.buy_price) : '',
    quantity: isNum(item.quantity) ? String(item.quantity) : '',
    note: item.note ?? '',
  }
}

/**
 * Check the edit form and build the request. Only fields the person changed are sent, so an old buy date is never
 * re-sent (the server refuses dates more than 120 days back) unless the person edited it.
 */
export function buildPatch(item: WatchTrackerItem, form: EditForm, today: string = todayIst()): EditResult {
  const errors: EditResult['errors'] = {}
  const patch: EditPatch = {}
  const orig = formFromItem(item)

  if (form.boughtOn !== orig.boughtOn) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(form.boughtOn)) errors.boughtOn = 'Pick the day you bought it.'
    else if (form.boughtOn > today) errors.boughtOn = 'The buy date cannot be in the future.'
    else if (form.boughtOn < addDaysIso(today, -MAX_BACKDATE_DAYS)) errors.boughtOn = `The buy date cannot be more than ${MAX_BACKDATE_DAYS} days ago.`
    else patch.bought_on = form.boughtOn
  }
  if (form.price.trim() !== orig.price.trim()) {
    const p = parseBuyPrice(form.price)
    if (p === undefined) errors.price = 'Type a number above 0, like 4210 or 182.4.'
    else patch.buy_price = p
  }
  if (form.quantity.trim() !== orig.quantity.trim()) {
    const q = parseQuantity(form.quantity)
    if (q === undefined) errors.quantity = 'Type the number of shares, above 0, like 10.'
    else patch.quantity = q
  }
  if (form.note.trim() !== orig.note.trim()) patch.note = form.note.trim() === '' ? null : form.note.trim()

  return { patch, errors, changed: Object.keys(patch).length > 0 }
}

export function entryNote(item: WatchTrackerItem): string {
  if (item.entry_source === 'your_price') return 'Your Groww price'
  if (item.entry_source === 'added_close') return 'Close on the day you added it'
  return 'Not known yet'
}

export interface PortfolioSummary {
  /** Money put in, rupees: only stocks with an entry price and shares count. */
  invested: number
  /** Gain or loss since buying, rupees, and as a % of the money put in. */
  totalReturn: number
  totalReturnPct: number | null
  /** Change since yesterday's close, rupees, and as a % of yesterday's value. */
  dayReturn: number
  dayReturnPct: number | null
  /** How many stocks had shares + prices entered (the rest are left out of the sums). */
  counted: number
}

/** Totals for the strip above the table. Display only: stocks without shares or prices are left out, never guessed. */
export function portfolioSummary(items: readonly WatchTrackerItem[]): PortfolioSummary | null {
  let invested = 0
  let totalReturn = 0
  let dayReturn = 0
  let yesterday = 0
  let counted = 0
  for (const i of items) {
    if (!isNum(i.invested) || !isNum(i.profit_amount)) continue
    counted += 1
    invested += i.invested
    totalReturn += i.profit_amount
    if (isNum(i.last_price) && isNum(i.today_pct) && isNum(i.quantity) && i.today_pct > -100) {
      const prev = i.last_price / (1 + i.today_pct / 100)
      dayReturn += (i.last_price - prev) * i.quantity
      yesterday += prev * i.quantity
    }
  }
  if (counted === 0) return null
  return {
    invested,
    totalReturn,
    totalReturnPct: invested > 0 ? (totalReturn / invested) * 100 : null,
    dayReturn,
    dayReturnPct: yesterday > 0 ? (dayReturn / yesterday) * 100 : null,
    counted,
  }
}
