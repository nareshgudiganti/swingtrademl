// Stock Compare: the plain-words rules, kept apart from the screen so they can be tested. Display only: price
// changes from stored daily closes. Nothing here tells anyone to buy or sell.

import type { CompareStock } from '../api/types'

export const MAX_COMPARE = 3

/** "How far back", in the words a person would say. */
export const PERIOD_WORDS: Record<string, string> = {
  '1W': 'last week',
  '1M': 'last month',
  '3M': 'last 3 months',
  '6M': 'last 6 months',
  '1Y': 'last year',
  '2Y': 'last 2 years',
  '3Y': 'last 3 years',
  '5Y': 'last 5 years',
}

/** "?s=suzlon,eternal,suzlon" -> ['SUZLON', 'ETERNAL']: upper-case, repeats dropped, at most three. */
export function parseSelection(raw: string | null | undefined): string[] {
  const seen = (raw ?? '')
    .split(',')
    .map((s) => s.trim().toUpperCase())
    .filter(Boolean)
  return [...new Set(seen)].slice(0, MAX_COMPARE)
}

/** "+8.94%", "-5.83%", or a plain "Not enough history" when we do not have that far back. */
export function fmtPct(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return 'Not enough history'
  return `${v > 0 ? '+' : ''}${v.toFixed(2)}%`
}

export type Tone = 'up' | 'down' | 'flat' | 'none'
export function toneOf(v: number | null | undefined): Tone {
  if (v === null || v === undefined || Number.isNaN(v)) return 'none'
  return v > 0 ? 'up' : v < 0 ? 'down' : 'flat'
}

/** One sentence on who moved most over a period, only when at least two stocks have that period. */
export function leaderLine(stocks: CompareStock[], period: string): string | null {
  const have = stocks.filter((s) => s.state === 'ok' && typeof s.returns[period] === 'number')
  if (have.length < 2) return null
  const sorted = [...have].sort((a, b) => (b.returns[period] as number) - (a.returns[period] as number))
  const best = sorted[0]!
  const worst = sorted[sorted.length - 1]!
  const when = PERIOD_WORDS[period] ?? period
  if (best.returns[period] === worst.returns[period]) return `Over the ${when}, they moved by the same amount.`
  const b = best.returns[period] as number
  const w = worst.returns[period] as number
  return `Over the ${when}, ${best.symbol} did best (${fmtPct(b)}) and ${worst.symbol} did worst (${fmtPct(w)}).`
}

/** What to say for a stock that has no numbers to show. */
export function noNumbersText(s: CompareStock): string {
  return s.state === 'unknown'
    ? `${s.symbol} is not a stock we know. Check the spelling.`
    : `We do not hold price history for ${s.symbol} yet. Only stocks on our watchlist or scanned by a strategy have it.`
}
