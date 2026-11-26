// The list of the brain's ideas as ONE table with its own scroll bar (up/down and sideways), so a long list does
// not make the whole page scroll. Shared by Discover and Today: same columns, same words. Display only.

import { Link } from 'react-router-dom'

import type { BrainDecision } from '../api/types'
import { CapFlag } from './cap'
import { whereItStopped } from './discoverRules'
import { shownWord } from './live'
import { scorePoints, SCORE_HINT } from './scoreText'
import { SortTh, useSort, type Sorter } from './sort'
import { WordTag } from './term'
import { IdeaFigures } from './stockParts'
import { oneReason } from './today/answerRules'
import { halfText, planDays, stopText, targetText } from './tradingRules'
import { inr, StockLogo } from './ui'

export type IdeaSortKey = 'rank' | 'stock' | 'decision' | 'score' | 'stopped'

/** Click-to-sort for the ideas table (best score first until a column header is clicked). */
export function useIdeaSort(rows: BrainDecision[]) {
  return useSort<BrainDecision, IdeaSortKey>(
    rows,
    {
      rank: (d) => d.confidence,
      stock: (d) => d.symbol,
      decision: (d) => shownWord(d),
      score: (d) => d.confidence,
      stopped: (d) => whereItStopped(d).label,
    },
    { key: null },
    { stock: 'asc', decision: 'asc', stopped: 'asc' },
  )
}

export function IdeasTable({
  rows,
  sorter,
  rankOf,
  tierOf,
  sectorOf,
  withFigures = false,
  withPlan = false,
  testId = 'discover-table',
}: {
  rows: BrainDecision[]
  sorter: Sorter<IdeaSortKey>
  rankOf: (d: BrainDecision) => number | null
  tierOf: (d: BrainDecision) => string | undefined
  sectorOf?: Record<string, string | null> | undefined
  /** Today: add the last close and the score's last days (two small reads per row, so only for a short list). */
  withFigures?: boolean
  /** Discover: a compact plan (buy zone, target, stop) on BUY rows, from the stored decision. */
  withPlan?: boolean
  testId?: string
}) {
  return (
    <div className="tmn-w2-tablebox tmn-w2-tablebox-tall" role="region" aria-label="Table, scroll to see more" tabIndex={0}>
      <table className="tmn-w2-table" data-testid={testId}>
        <thead>
          <tr>
            <SortTh sorter={sorter} k="rank" title="Place in today's ranking by score">#</SortTh>
            <SortTh sorter={sorter} k="stock">Stock</SortTh>
            <SortTh sorter={sorter} k="decision">Decision</SortTh>
            <SortTh sorter={sorter} k="score" title={SCORE_HINT}>Score</SortTh>
            {withFigures && <th>Last close and score trend</th>}
            <th>Why, in a few words</th>
            {withPlan && <th>Plan for a BUY</th>}
            <SortTh sorter={sorter} k="stopped">Where it stopped</SortTh>
            <th>
              <span className="tmn-w2-sr">AI analysis</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((d) => (
            <IdeaRow
              key={d.id}
              d={d}
              rank={rankOf(d)}
              tier={tierOf(d)}
              sector={sectorOf?.[d.symbol.toUpperCase()] ?? null}
              withFigures={withFigures}
              withPlan={withPlan}
            />
          ))}
        </tbody>
      </table>
    </div>
  )
}

function IdeaRow({
  d,
  rank,
  tier,
  sector,
  withFigures,
  withPlan,
}: {
  d: BrainDecision
  rank: number | null
  tier?: string
  sector: string | null
  withFigures: boolean
  withPlan: boolean
}) {
  const stop = whereItStopped(d)
  const pts = scorePoints(d.confidence)
  const to = `/trademind/stock/${encodeURIComponent(d.symbol)}`
  return (
    <tr>
      <td className="tm-dim tmn-w2-num">{rank ?? '—'}</td>
      <td>
        <Link to={to} className="tmn-w2-stock">
          <StockLogo symbol={d.symbol} />
          <span>
            <b>{d.symbol}</b> <CapFlag tier={tier} />
            {sector && <span className="tm-dim tmn-small tmn-w2-sub">{sector}</span>}
          </span>
        </Link>
      </td>
      <td>
        <WordTag word={shownWord(d)} />
      </td>
      <td title={SCORE_HINT}>
        <b>{pts ?? '—'}</b>
      </td>
      {withFigures && (
        <td>
          <IdeaFigures d={d} />
        </td>
      )}
      <td className="tmn-w2-why">{oneReason(d)}</td>
      {withPlan && (
        <td>
          <IdeaPlanCell d={d} />
        </td>
      )}
      <td>
        <span className="tmn-w2-stop" data-tone={stop.tone} title={stop.why ?? undefined}>
          <span className="tmn-w2-dot" aria-hidden="true" />
          {stop.label}
        </span>
      </td>
      <td>
        <Link to={to} className="tmn-ailink tmn-w2-ai">
          AI analysis →
        </Link>
      </td>
    </tr>
  )
}

/** The plan of a BUY row, from the stored decision: buy zone, target, stop. Any other row gets a dash (it keeps
 *  "Where it stopped"). The rules (percentages, days) are in the tooltip, read from the served trading rules. */
export function IdeaPlanCell({ d }: { d: BrainDecision }) {
  if (d.kind !== 'idea' || shownWord(d) !== 'TRADE' || d.entry_low == null || d.target == null || d.stop == null) {
    return <span className="tm-dim">—</span>
  }
  const high = d.entry_high ?? d.entry_low
  const zone = high !== d.entry_low ? `₹${inr(d.entry_low, 0)} – ₹${inr(high, 0)}` : `₹${inr(d.entry_low, 0)}`
  const rules = `Target ${targetText()}, stop ${stopText()}, sell half at ${halfText()}, sold within ${planDays()} trading days.`
  return (
    <span className="tmn-w2-plan" data-testid="idea-plan" title={rules}>
      <span>Buy {zone}</span>
      <span className="sp-pos">Target ₹{inr(d.target, 0)}</span>
      <span className="sp-neg">Stop ₹{inr(d.stop, 0)}</span>
    </span>
  )
}
