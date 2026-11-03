// The daily read on a stock you hold, shared by the Testing and My Holdings tabs:
// which day of the trade it is, today's model score (and the change since the
// last reading), and one suggestion word. Display only — nothing here sells.

import type { DetailedPosition, Trade } from '../api/types'
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

/** The latest sells of one book, each with its plain label and the book it came from. Display only. */
export function SellList({ trades, book, title = 'Latest sells' }: { trades: Trade[]; book: 'Bot' | 'Testing'; title?: string }) {
  const latest = trades
    .filter((t) => (t.book_label ?? book) === book)
    .sort((a, b) => b.exit_at.localeCompare(a.exit_at))
    .slice(0, 8)
  if (latest.length === 0) return null
  return (
    <div data-testid="sell-list">
      <div className="tm-stat-label">{title}</div>
      <ul style={{ margin: '0.3rem 0 0', paddingLeft: '1.1rem' }}>
        {latest.map((t) => (
          <li key={t.id}>
            <strong>{t.symbol}</strong> · <Tag tone={t.sell_label === 'Partial SELL completed' ? 'blue' : 'green'}>{t.sell_label ?? 'Sold'}</Tag>{' '}
            ({t.book_label ?? book}) · {t.exit_reason_label ?? t.exit_reason ?? 'no reason recorded'} · {t.exit_at.slice(0, 10)}
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
