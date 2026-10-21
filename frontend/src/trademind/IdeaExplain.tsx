// ux11: the customer explanation layer for brain ideas. Display only.
//  - "Why not TRADE?": the stored reasons a WATCH / WAIT / AVOID idea is not a TRADE (whyNotTrade.ts).
//  - "What changed since yesterday": today's live nightly decision next to the previous trading day's
//    (changes.ts, GET /brain/changes). Places in the ranking only, never a score as a chance, and never
//    any result of an idea.

import { Link } from 'react-router-dom'

import type { BrainDecision } from '../api/types'
import {
  changeHeadline,
  ideaChange,
  rankLine,
  summarize,
  useChanges,
  type BrainChanges,
  type IdeaChange,
} from './changes'
import { NOTHING_STORED, whyNotTrade, type WhyItem } from './whyNotTrade'
import { Card, CheckItem } from './ui'
import { wordTagColor } from './vocab'

function Word({ word }: { word: string }) {
  return <span className={`tm-tag tm-tag-${wordTagColor(word)}`}>{word}</span>
}

function dayName(day: string): string {
  const d = new Date(`${day}T00:00:00`)
  return Number.isNaN(d.getTime())
    ? day
    : d.toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short' })
}

function WhyList({ items }: { items: WhyItem[] }) {
  return (
    <>
      {items.map((item, i) => (
        <CheckItem key={i} tone="warn">
          {item.detail ? (
            <details>
              <summary style={{ cursor: 'pointer' }}>{item.text}</summary>
              <span className="tm-dim" style={{ fontSize: '0.78rem' }}>
                What the brain recorded: {item.detail}
              </span>
            </details>
          ) : (
            item.text
          )}
        </CheckItem>
      ))}
    </>
  )
}

/** "Why not TRADE?" for one idea. Renders nothing for a TRADE or a holding. */
export function WhyNotTradeView({ decision }: { decision: BrainDecision }) {
  const word = decision.overruled_word ?? decision.word
  if (decision.kind !== 'idea' || !['WATCH', 'WAIT', 'AVOID'].includes(word)) return null
  const items = whyNotTrade(decision)
  return (
    <div data-testid="why-not-trade">
      <div className="tm-strong" style={{ marginBottom: 4 }}>
        Why not TRADE?
      </div>
      <p className="tm-dim" style={{ margin: '0 0 0.4rem', fontSize: '0.78rem' }}>
        The brain says <Word word={word} /> for {decision.symbol}, not TRADE. In plain words, the reasons it
        stored:
      </p>
      {items.length > 0 ? <WhyList items={items} /> : <p className="tm-dim">{NOTHING_STORED}</p>}
    </div>
  )
}

/** "What changed since yesterday" for one idea, from a /brain/changes answer. */
export function IdeaChangeView({ data, symbol }: { data: BrainChanges; symbol: string }) {
  if (!data.comparable || !data.previous) {
    return <p className="tm-dim">{data.note ?? 'There is no earlier nightly run to compare with yet.'}</p>
  }
  const row = data.ideas.find((r) => r.symbol.toUpperCase() === symbol.toUpperCase())
  if (!row) {
    return <p className="tm-dim">The brain did not list {symbol} as an idea on either day.</p>
  }
  const c = ideaChange(row)
  return <ChangeDetail c={c} previousDay={data.previous.day} />
}

function ChangeDetail({ c, previousDay }: { c: IdeaChange; previousDay: string }) {
  const rank = rankLine(c)
  return (
    <div data-testid="idea-change" data-change={c.kind}>
      <p className="tm-dim" style={{ margin: '0 0 0.4rem', fontSize: '0.78rem' }}>
        Compared with the brain's nightly run on {dayName(previousDay)}.
      </p>
      <p className="tm-strong" style={{ margin: '0 0 0.3rem' }}>
        {c.wordBefore && c.wordNow && c.wordBefore !== c.wordNow ? (
          <>
            <Word word={c.wordBefore} /> → <Word word={c.wordNow} />{' '}
          </>
        ) : null}
        {changeHeadline(c)}
      </p>
      {rank && <p style={{ margin: '0 0 0.3rem' }}>{rank}</p>}
      {c.kind === 'reason' && (
        <div className="tm-grid tm-cols-2" style={{ gap: '0.6rem' }}>
          <div>
            <div className="tm-stat-label">Yesterday</div>
            {c.whyBefore.length ? <WhyList items={c.whyBefore} /> : <p className="tm-dim">{NOTHING_STORED}</p>}
          </div>
          <div>
            <div className="tm-stat-label">Today</div>
            {c.whyNow.length ? <WhyList items={c.whyNow} /> : <p className="tm-dim">{NOTHING_STORED}</p>}
          </div>
        </div>
      )}
      {c.kind === 'word' && c.wordBefore !== 'TRADE' && c.whyBefore.length > 0 && (
        <details className="tm-note" style={{ marginTop: '0.3rem' }}>
          <summary style={{ cursor: 'pointer' }}>Why it was {c.wordBefore} yesterday</summary>
          <WhyList items={c.whyBefore} />
        </details>
      )}
      <p className="tm-dim" style={{ margin: '0.4rem 0 0', fontSize: '0.72rem' }}>
        The ranking compares stocks with each other on the same day. It is not a chance of profit.
      </p>
    </div>
  )
}

/** One card for an idea's page: "Why not TRADE?" (WATCH / WAIT / AVOID) and "What changed since yesterday"
 *  (only when the decision comes from a nightly run, `runId`). */
export function IdeaExplain({ decision, runId }: { decision: BrainDecision; runId?: string }) {
  const changes = useChanges(decision.kind === 'idea' ? runId : undefined)
  if (decision.kind !== 'idea') return null
  return (
    <Card title="In plain words" sub="Why the brain decided this, and what changed since yesterday">
      <WhyNotTradeView decision={decision} />
      {runId && (
        <div style={{ marginTop: '0.8rem' }}>
          <div className="tm-strong" style={{ marginBottom: 4 }}>
            What changed since yesterday
          </div>
          {changes.isLoading && <p className="tm-dim">Loading yesterday's decision…</p>}
          {changes.isError && <p className="tm-dim">Could not load yesterday's decision. Try again shortly.</p>}
          {changes.data && <IdeaChangeView data={changes.data} symbol={decision.symbol} />}
        </div>
      )}
    </Card>
  )
}

const MAX_LISTED = 6

function SymbolList({ items, render }: { items: IdeaChange[]; render: (c: IdeaChange) => string }) {
  const shown = items.slice(0, MAX_LISTED)
  return (
    <>
      {shown.map((c) => (
        <div key={c.symbol} className="tm-dim" style={{ fontSize: '0.78rem' }}>
          <Link className="tm-link" to={`/trademind/stock/${encodeURIComponent(c.symbol)}`}>
            {c.symbol}
          </Link>
          : {render(c)}
        </div>
      ))}
      {items.length > shown.length && (
        <div className="tm-dim" style={{ fontSize: '0.72rem' }}>
          and {items.length - shown.length} more
        </div>
      )}
    </>
  )
}

/** The Today page summary of what changed since the previous trading day's nightly run. */
export function ChangesSummaryView({ data }: { data: BrainChanges }) {
  if (!data.comparable || !data.previous) {
    return <p className="tm-dim">{data.note ?? 'There is no earlier nightly run to compare with yet.'}</p>
  }
  const s = summarize(data.ideas.map(ideaChange))
  const nothing =
    s.wordChanged.length + s.newToday.length + s.dropped.length + s.held.length + s.reasonChanged.length + s.bigMoves.length === 0
  return (
    <div data-testid="changes-summary">
      <p className="tm-dim" style={{ margin: '0 0 0.5rem', fontSize: '0.78rem' }}>
        Today's nightly run compared with the one on {dayName(data.previous.day)}.
      </p>
      {nothing ? (
        <p className="tm-dim">No decision changed since then.</p>
      ) : (
        <>
          {s.wordChanged.length > 0 && (
            <CheckItem tone="warn">
              {s.wordChanged.length} {s.wordChanged.length === 1 ? 'decision' : 'decisions'} changed
              <SymbolList items={s.wordChanged} render={(c) => `${c.wordBefore} → ${c.wordNow}`} />
            </CheckItem>
          )}
          {s.newToday.length > 0 && (
            <CheckItem tone="neutral">
              {s.newToday.length} new on the list today
              <SymbolList items={s.newToday} render={(c) => `${c.wordNow}`} />
            </CheckItem>
          )}
          {s.dropped.length > 0 && (
            <CheckItem tone="neutral">
              {s.dropped.length} no longer on the list
              <SymbolList items={s.dropped} render={(c) => `was ${c.wordBefore}`} />
            </CheckItem>
          )}
          {s.held.length > 0 && (
            <CheckItem tone="neutral">
              {s.held.length} now held, so no longer listed as {s.held.length === 1 ? 'an idea' : 'ideas'}
            </CheckItem>
          )}
          {s.reasonChanged.length > 0 && (
            <CheckItem tone="neutral">
              {s.reasonChanged.length} kept the same word for a different reason
            </CheckItem>
          )}
          {s.bigMoves.length > 0 && (
            <CheckItem tone="neutral">
              {s.bigMoves.length} moved 10 or more places in the ranking
              <SymbolList
                items={s.bigMoves}
                render={(c) => `${c.placesMoved! > 0 ? 'up' : 'down'} ${Math.abs(c.placesMoved!)} places`}
              />
            </CheckItem>
          )}
        </>
      )}
      <p className="tm-dim" style={{ margin: '0.4rem 0 0', fontSize: '0.72rem' }}>
        Tap a stock for its details. The ranking compares stocks with each other; it is not a chance of profit.
      </p>
    </div>
  )
}

export function ChangesSummaryCard({ runId }: { runId: string }) {
  const changes = useChanges(runId)
  return (
    <Card title="What changed since yesterday" sub="Decisions compared with the previous trading day's nightly run">
      {changes.isLoading && <p className="tm-dim">Loading…</p>}
      {changes.isError && <p className="tm-dim">Could not load the comparison. Try again shortly.</p>}
      {changes.data && <ChangesSummaryView data={changes.data} />}
    </Card>
  )
}
