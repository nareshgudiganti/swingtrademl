// oa5: the holdings part of Today's "Needs you" — the held stocks the brain flagged (MONITOR / REDUCE / EXIT, using
// the owner's overrule when there is one). Moved from Home's "Holdings Needing Attention" card.
//
// It is a slot on purpose: NeedsYou takes it as its `holdings` prop, so the paused "What to do with your stocks
// today" card (branch feature/holdings-daily-read) can replace this one component with a small merge.
//
// The holdings come from the brain's run, which is the bot's paper book, so the card says Paper. Display only.

import { useNavigate } from 'react-router-dom'

import type { BrainDecision, BrainRun } from '../../api/types'
import { withoutScorePercent } from '../beginner/cardText'
import { finalWord, holdingsFrom } from '../live'
import { PageState } from '../PageState'
import { WordTag } from '../term'
import { Card, Tag } from '../ui'

/** Held stocks the brain wants you to look at: MONITOR, REDUCE or EXIT (after any overrule). */
export function holdingsNeedingAttention(run: BrainRun): BrainDecision[] {
  return holdingsFrom(run).filter((d) => ['MONITOR', 'REDUCE', 'EXIT'].includes(finalWord(d)))
}

export function HoldingsNeedsYou({ run }: { run: BrainRun | undefined }) {
  const navigate = useNavigate()
  const holdings = run ? holdingsFrom(run) : []
  const attention = run ? holdingsNeedingAttention(run) : []

  return (
    <Card title="Holdings Needing Attention" sub="Stocks the bot holds that the brain flagged" action={<Tag tone="blue">Paper</Tag>}>
      <div data-feature="holdings-attention">
        {!run ? (
          <PageState kind="empty" reason="No brain run yet, so no holding has been checked." />
        ) : holdings.length === 0 ? (
          <PageState kind="empty" reason="The brain's last run found no shares held, so there is nothing to check." />
        ) : attention.length === 0 ? (
          <p className="tm-dim">Nothing needs attention — your holdings look fine.</p>
        ) : (
          <div className="tm-rows">
            {attention.map((d) => (
              <div
                className="tm-row tm-clickable"
                key={d.id}
                onClick={() => navigate(`/trademind/stock/${encodeURIComponent(d.symbol)}`)}
              >
                <span className="tm-flex" style={{ gap: '0.55rem' }}>
                  <span className="tm-strong">{d.symbol}</span>
                  <span className="tm-dim">{d.reasons[0] ? withoutScorePercent(d.reasons[0]) : ''}</span>
                </span>
                <WordTag word={finalWord(d)} />
              </div>
            ))}
          </div>
        )}
      </div>
    </Card>
  )
}
