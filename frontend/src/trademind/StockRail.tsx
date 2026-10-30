// A sideways-swiping row of stock cards: the app's "slide through the list" layout, so a long list of stocks is a
// few rows you swipe instead of one page you scroll. Display only; every card opens the stock's page.

import { Link } from 'react-router-dom'

import type { BrainDecision } from '../api/types'
import { CapFlag } from './cap'
import { scorePoints, SCORE_HINT } from './scoreText'
import { oneReason } from './today/answerRules'
import { StockLogo } from './ui'

const CARD_LIMIT = 40

export type RailCard = { d: BrainDecision; rank: number | null; tier?: string; sector?: string | null }

export function StockRail({
  title,
  sub,
  tone,
  cards,
  onSeeAll,
}: {
  title: string
  sub?: string
  tone: 'up' | 'wait' | 'down' | 'none'
  cards: RailCard[]
  /** Shown as the last card when the row holds more than CARD_LIMIT stocks. */
  onSeeAll?: () => void
}) {
  const shown = cards.slice(0, CARD_LIMIT)
  const more = cards.length - shown.length
  return (
    <section className="tmn-card tmn-w2-railcard" aria-label={`${title}: ${cards.length} stocks`} data-testid="stock-rail">
      <div className="tmn-card-head tmn-w2-pad">
        <span className="tmn-card-title">
          {title} <span className="tmn-w2-count">{cards.length}</span>
        </span>
        {sub && <span className="tm-dim tmn-small">{sub}</span>}
      </div>
      <div className="tmn-w2-rail" role="region" aria-label={`${title}, swipe sideways to see more`} tabIndex={0}>
        {shown.map(({ d, rank, tier, sector }) => {
          const pts = scorePoints(d.confidence)
          return (
            <Link
              key={d.id}
              to={`/trademind/stock/${encodeURIComponent(d.symbol)}`}
              className="tmn-w2-hcard"
              data-tone={tone === 'wait' ? 'none' : tone}
            >
              <span className="tmn-w2-hcard-top">
                <StockLogo symbol={d.symbol} />
                <span className="tmn-grow">
                  <b>{d.symbol}</b> <CapFlag tier={tier} />
                  {sector && <span className="tmn-small tm-dim tmn-w2-sub">{sector}</span>}
                </span>
                {rank != null && <span className="tm-dim tmn-small">#{rank}</span>}
              </span>
              <span className="tmn-w2-hcard-score" title={SCORE_HINT}>
                <span className="tmn-w2-meter">
                  <span style={{ width: `${Math.min(100, Math.max(0, pts ?? 0))}%` }} />
                </span>
                <b>{pts ?? '—'}</b>
              </span>
              <span className="tmn-w2-hcard-why">{oneReason(d)}</span>
              <span className="tmn-ailink tmn-small">AI analysis →</span>
            </Link>
          )
        })}
        {more > 0 && onSeeAll && (
          <button type="button" className="tmn-w2-hcard tmn-w2-seeall" onClick={onSeeAll}>
            <b>See all {cards.length}</b>
            <span className="tm-dim tmn-small">Show the rest of this row as a table</span>
          </button>
        )}
      </div>
    </section>
  )
}
