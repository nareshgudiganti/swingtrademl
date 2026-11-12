// The daily read on a stock you hold, shared by the Testing and My Holdings tabs:
// which day of the trade it is, today's model score (and the change since the
// last reading), and one suggestion word. Display only — nothing here sells.

import { useState } from 'react'

import type { DetailedPosition, Trade } from '../api/types'
import StockLink from './StockLink'
import { Tag } from './ui'

export type Suggestion = NonNullable<DetailedPosition['suggestion']>

export const SUGGESTION: Record<Suggestion, { label: string; tone: 'red' | 'green' | 'amber' | 'blue'; rank: number }> = {
  SELL: { label: 'Sell', tone: 'red', rank: 0 },
  SELL_PARTIALLY: { label: 'Sell half', tone: 'green', rank: 1 },
  WATCH: { label: 'Watch', tone: 'amber', rank: 2 },
  HOLD: { label: 'Hold', tone: 'blue', rank: 3 },
}

/** Sort key: Sell first, then Sell half, Watch, Hold. */
export const suggestionRank = (p: DetailedPosition) => (p.suggestion ? SUGGESTION[p.suggestion].rank : null)

export function SuggestionTag({ p }: { p: DetailedPosition }) {
  if (!p.suggestion) return <span className="tm-dim">—</span>
  const s = SUGGESTION[p.suggestion]
  return (
    <span title={p.suggestion_reason ?? undefined}>
      <Tag tone={s.tone}>{s.label}</Tag>
    </span>
  )
}

/** "SELL review required" (past its stop, target or time limit) or "Exit check unavailable". Display only. */
export function SellStatusTag({ p }: { p: DetailedPosition }) {
  if (!p.sell_status) return null
  const review = p.sell_status === 'SELL review required'
  return (
    <div>
      <Tag tone={review ? 'red' : 'amber'}>{p.sell_status}</Tag>
    </div>
  )
}

export type SellFilter = string // 'all' | 'type:<sell label>' | 'reason:<exit reason label>'

const reasonOf = (t: Trade) => t.exit_reason_label ?? t.exit_reason ?? 'No reason recorded'
const typeOf = (t: Trade) => t.sell_label ?? 'Sold'

/** The choices for the title dropdown, with how many sells each one matches. Only choices that match something. */
export function sellFilterOptions(trades: Trade[]) {
  const count = (keyOf: (t: Trade) => string) => {
    const m = new Map<string, number>()
    for (const t of trades) m.set(keyOf(t), (m.get(keyOf(t)) ?? 0) + 1)
    return [...m.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
  }
  return { total: trades.length, types: count(typeOf), reasons: count(reasonOf) }
}

export function filterSells(trades: Trade[], filter: SellFilter): Trade[] {
  if (filter.startsWith('type:')) return trades.filter((t) => typeOf(t) === filter.slice(5))
  if (filter.startsWith('reason:')) return trades.filter((t) => reasonOf(t) === filter.slice(7))
  return trades
}

/** The sells of one book, newest first. The title is a dropdown: all sells, or only one type (PAPER SELL executed,
 *  Partial SELL completed) or one reason (Stop-loss hit, Target reached ...). Display only. */
export function SellList({ trades, book, title = 'Sells' }: { trades: Trade[]; book: 'Bot' | 'Testing'; title?: string }) {
  const [filter, setFilter] = useState<SellFilter>('all')
  const mine = trades.filter((t) => (t.book_label ?? book) === book).sort((a, b) => b.exit_at.localeCompare(a.exit_at))
  if (mine.length === 0) return null
  const opts = sellFilterOptions(mine)
  const shown = filterSells(mine, filter).slice(0, 12)
  const matching = filterSells(mine, filter).length
  return (
    <div data-testid="sell-list">
      <label className="tm-stat-label" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
        <select
          aria-label={`${title}: choose which sells to show`}
          data-testid="sell-filter"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          style={{ font: 'inherit', fontWeight: 600, padding: '0.2rem 0.4rem', borderRadius: 6, maxWidth: '24rem' }}
        >
          <option value="all">{`${title}: all (${opts.total})`}</option>
          <optgroup label="By type">
            {opts.types.map(([name, n]) => (
              <option key={`type:${name}`} value={`type:${name}`}>
                {`${name} (${n})`}
              </option>
            ))}
          </optgroup>
          <optgroup label="By reason">
            {opts.reasons.map(([name, n]) => (
              <option key={`reason:${name}`} value={`reason:${name}`}>
                {`${name} (${n})`}
              </option>
            ))}
          </optgroup>
        </select>
        {matching > shown.length && <span className="tm-dim">showing the latest {shown.length} of {matching}</span>}
      </label>
      <ul style={{ margin: '0.3rem 0 0', paddingLeft: '1.1rem' }}>
        {shown.map((t) => (
          <li key={t.id}>
            <StockLink symbol={t.symbol} withScore={false} /> · <Tag tone={typeOf(t) === 'Partial SELL completed' ? 'blue' : 'green'}>{typeOf(t)}</Tag>{' '}
            ({t.book_label ?? book}) · {reasonOf(t)} · {t.exit_at.slice(0, 10)}
          </li>
        ))}
      </ul>
    </div>
  )
}

export function DayCell({ p }: { p: DetailedPosition }) {
  if (p.day_number == null) return <span className="tm-dim">—</span>
  const limit = p.trade_limit_days ?? 15
  const over = p.day_number > limit
  return (
    <span
      className={over ? 'tm-neg' : undefined}
      title={`Trading day ${p.day_number} since you bought it. A trade is planned to finish within ${limit} trading days.`}
    >
      Day {p.day_number} <span className="tm-dim">of {limit}</span>
    </span>
  )
}

/** Today's model score, 0-1: the newest daily reading, else the last one on the position. */
export function scoreNow(p: DetailedPosition): number | null {
  const trail = p.score_trail ?? []
  if (trail.length > 0) return trail[trail.length - 1]!.score
  return p.score_from_trail ? null : p.last_confidence
}

/** Change since the previous daily reading, in points out of 100. */
export function scoreChange(p: DetailedPosition): number | null {
  const trail = p.score_trail ?? []
  if (trail.length < 2) return null
  return Math.round(trail[trail.length - 1]!.score * 100) - Math.round(trail[trail.length - 2]!.score * 100)
}

export function ScoreToday({ p }: { p: DetailedPosition }) {
  const now = scoreNow(p)
  if (now == null) return <span className="tm-dim">No score yet</span>
  const change = scoreChange(p)
  return (
    <span className="tm-num" title="How strongly the model likes this stock today, out of 100. Change is since the last daily check.">
      <span className="tm-strong">{Math.round(now * 100)}</span>
      {change != null && change !== 0 && (
        <span className={change > 0 ? 'tm-pos' : 'tm-neg'} style={{ marginLeft: '0.35rem' }}>
          {change > 0 ? '▲' : '▼'}
          {Math.abs(change)}
        </span>
      )}
    </span>
  )
}
