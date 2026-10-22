// oa11 Insights: the wording rules, kept pure so they can be tested.
// Rule 1: the brain is never called "improving" unless a FROZEN test has passed. Until then the answer is
// "Not proven", whatever any count or gate says.
// Rule 2: practice and real money are never added together: these helpers only ever format one book.

import type { ObsClaim } from '../api/types'
import type { InsightsBenchmark, InsightsBook } from './beginner/types'
import { inr } from './ui'

export const NOT_PROVEN = 'Not proven'
export const PROVEN = 'Proven'
export const NA = 'Not available'
export const LEARNING_CLAIM = 'learning_changes'

/** Is the brain getting better? Only a frozen test's "Proven" on the learning claim can say yes. */
export function improvingAnswer(claims: readonly ObsClaim[] | undefined): { word: string; why: string } {
  const c = claims?.find((x) => x.claim === LEARNING_CLAIM)
  if (c && c.word === PROVEN) {
    return { word: 'Proven by a frozen test', why: `${c.label}: ${c.word}.` }
  }
  const record = c ? `The frozen-test record says: "${c.word}".` : 'No frozen-test record could be read.'
  return {
    word: NOT_PROVEN,
    why: `No frozen test has shown that the brain's learning makes it better. ${record}`,
  }
}

export const money = (n: number) => `${n < 0 ? '−' : n > 0 ? '+' : ''}₹${inr(Math.abs(n))}`
export const pct = (n: number) => `${n < 0 ? '−' : n > 0 ? '+' : ''}${Math.abs(n).toFixed(2)}%`

/** One book's result for one period, in words. No trades is said plainly, never shown as ₹0 profit. */
export function bookCell(b: InsightsBook): { main: string; detail: string } {
  if (!b.finished) return { main: 'No finished trades', detail: '' }
  const trades = `${b.finished} ${b.finished === 1 ? 'trade' : 'trades'}, ${b.wins} made money`
  const ret = b.return_pct === null ? '' : ` · ${pct(b.return_pct)} on money used`
  return { main: money(b.net_pnl), detail: `${trades}${ret} · costs ₹${inr(b.charges)}` }
}

/** A benchmark for one period: the % after costs, or "Not available" with the reason. */
export function benchCell(b: InsightsBenchmark): string {
  return b.pct === null ? `${NA} — ${b.why ?? 'no prices'}` : pct(b.pct)
}
