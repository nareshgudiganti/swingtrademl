// oa5: Today's ideas (moved from Home): the horizon selector, the idea counts and the top 5 ideas drawn with the one
// recommendation card (beginner/LiveIdeaCard, oa12), then what changed and today's insights.
// The selector is the shared one with its honest states: only 15 days has a strategy ("Experimental, unproven");
// choosing any other window shows that no idea exists for it, never the 15-day ideas under its name.

import { Link } from 'react-router-dom'

import type { BrainRun, IdeaWord } from '../../api/types'
import LiveIdeaCard from '../beginner/LiveIdeaCard'
import { withoutScorePercent } from '../beginner/cardText'
import { CapFlag, useSymbolCaps } from '../cap'
import { noTradeReason } from '../emptyReasons'
import { HorizonSelector, HorizonUnavailable } from '../HorizonSelector'
import { horizonById, type HorizonId } from '../horizons'
import { ChangesSummaryCard } from '../IdeaExplain'
import { finalWord, ideasFrom, marketSituation, useLearning } from '../live'
import { PageState } from '../PageState'
import { Card, CheckItem } from '../ui'
import { holdingsNeedingAttention } from './HoldingsNeedsYou'

const IDEA_WORDS: IdeaWord[] = ['TRADE', 'WATCH', 'WAIT', 'AVOID']
export const TOP_IDEAS = 5

/** How many of the run's ideas got each word (the owner's overrule wins), the same counts Home showed. */
export function ideaCounts(run: BrainRun): Record<IdeaWord, number> {
  const counts: Record<IdeaWord, number> = { TRADE: 0, WATCH: 0, WAIT: 0, AVOID: 0 }
  for (const d of ideasFrom(run)) {
    const w = finalWord(d)
    if (w in counts) counts[w as IdeaWord] += 1
  }
  return counts
}

export function TodayIdeas({ run, win, onWin }: { run: BrainRun; win: HorizonId; onWin: (h: HorizonId) => void }) {
  const caps = useSymbolCaps()
  const ideas = ideasFrom(run)
  const top = ideas.slice(0, TOP_IDEAS)
  // Every idea score in the run, so each card can say "Rank 2 of 9 today" instead of a bare number.
  const dayScores = ideas.map((d) => d.confidence)
  const counts = ideaCounts(run)
  // Why there are no TRADE ideas, from the run's own banner only (null when there are some).
  const noTrade = noTradeReason(run.banner, ideas.length, counts.TRADE)
  const active = horizonById(win)

  return (
    <>
      <Card
        title="Today's Ideas"
        sub="Pick a time window, then see how many stocks got each decision"
        action={<Link className="tm-link" to="/trademind/opportunities">View All</Link>}
      >
        <div data-feature="horizon-cards" style={{ marginBottom: '0.9rem' }}>
          <HorizonSelector value={win} onChange={onWin} />
        </div>
        <div className="tm-grid tm-cols-4" data-feature="idea-counts" aria-label="15-day ideas by decision">
          {IDEA_WORDS.map((w) => (
            <div key={w} style={{ textAlign: 'center' }}>
              <div className="tm-stat-value" style={{ fontSize: '1.4rem' }}>
                {counts[w]}
              </div>
              <div className="tm-stat-label">{w}</div>
            </div>
          ))}
        </div>
        <p className="tm-dim" style={{ fontSize: '0.72rem', margin: '0.4rem 0 0' }}>
          These counts are the 15-day ideas, the only window with a strategy.
        </p>
        {noTrade && (
          <p className="tm-note" data-testid="no-trade-reason" data-feature="no-trade-reason">
            {noTrade}
          </p>
        )}
      </Card>

      <Card title="Top Ideas" sub={`The brain's first ${TOP_IDEAS}, best first`} action={<Link className="tm-link" to="/trademind/opportunities">View All</Link>}>
        <div data-feature="top-ideas">
          {!active.available ? (
            <div data-feature="horizon-unavailable">
              <HorizonUnavailable horizon={active} />
            </div>
          ) : top.length === 0 ? (
            <PageState kind="empty" reason={noTrade ?? "No ideas in the brain's last run."} />
          ) : (
            <div className="bx-cards" data-testid="top-ideas">
              {top.map((i) => (
                <LiveIdeaCard
                  key={i.id}
                  decision={i}
                  compact
                  dayScores={dayScores}
                  tags={<CapFlag tier={caps.get(i.symbol.toUpperCase())} />}
                />
              ))}
            </div>
          )}
        </div>
      </Card>
    </>
  )
}

/** "Today's insights", built only from lines the brain actually returned (moved from Home). Nothing is invented. */
export function TodayInsights({ run }: { run: BrainRun }) {
  const learning = useLearning()
  const situation = marketSituation(run)
  type Insight = { text: string; tone: 'pos' | 'neg' | 'warn' | 'neutral' }
  const insights: Insight[] = []
  for (const d of holdingsNeedingAttention(run)) {
    if (d.reasons[0]) {
      insights.push({ text: `${d.symbol}: ${withoutScorePercent(d.reasons[0])}`, tone: finalWord(d) === 'MONITOR' ? 'warn' : 'neg' })
    }
  }
  if (situation && situation.label !== 'unlabelled') {
    for (const e of situation.evidence) insights.push({ text: e, tone: 'neutral' })
  }
  for (const f of learning.data?.failures ?? []) insights.push({ text: withoutScorePercent(f), tone: 'warn' })
  if (learning.data?.note) insights.push({ text: withoutScorePercent(learning.data.note), tone: 'neutral' })

  return (
    <Card title="Today's Insights">
      <div data-feature="insights">
        {learning.isLoading && <PageState kind="loading" what="the learning report" />}
        {learning.isError && learning.data === undefined && (
          <PageState kind="error" what="the learning report" error={learning.error} onRetry={learning.refetch} />
        )}
        {insights.length === 0 && !learning.isLoading && !learning.isError ? (
          <PageState kind="empty" reason="Nothing to report today: no holding needs attention and the brain flagged nothing new." />
        ) : (
          insights.slice(0, 6).map((x, idx) => (
            <CheckItem key={idx} tone={x.tone}>
              {x.text}
            </CheckItem>
          ))
        )}
      </div>
    </Card>
  )
}

export function TodayChanges({ run }: { run: BrainRun }) {
  return (
    <div data-feature="changes-summary">
      <ChangesSummaryCard runId={run.run_id} />
    </div>
  )
}
