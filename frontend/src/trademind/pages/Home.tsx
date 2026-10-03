import { useNavigate, Link } from 'react-router-dom'

import type { Action } from '../types'
import type { BrainDecision, IdeaWord } from '../../api/types'
import { ideasFrom, holdingsFrom, marketSituation, useBrainStatus, useLatestRun, useLearning } from '../live'
import { ActionPill, BrainArt, BrainOff, Card, CheckItem, Icon, Tag } from '../ui'

// The owner's overrule, if any, otherwise the brain's own word. Duplicated
// in each TradeMind screen rather than shared, same as Brain.tsx's own copy.
function finalWord(d: BrainDecision): string {
  return d.overruled_word ?? d.word
}

const MARKET_PLAIN: Record<string, string> = {
  NORMAL: 'New ideas are allowed at full size.',
  DEFENSIVE: 'Careful market: at most two new ideas, at half size.',
  NO_NEW_TRADES: 'No new buys today. Stocks you hold are still watched and sold as usual.',
}

const MARKET_TONE: Record<string, 'green' | 'amber' | 'red'> = {
  NORMAL: 'green',
  DEFENSIVE: 'amber',
  NO_NEW_TRADES: 'red',
}

const IDEA_WORDS: IdeaWord[] = ['TRADE', 'WATCH', 'WAIT', 'AVOID']

const HOLDING_TONE: Record<string, 'green' | 'blue' | 'amber' | 'red'> = {
  HOLD: 'green',
  MONITOR: 'blue',
  REDUCE: 'amber',
  EXIT: 'red',
}

export default function Home() {
  const navigate = useNavigate()
  const status = useBrainStatus()
  const latest = useLatestRun()
  const learning = useLearning()

  if (status === 'off') return <div className="tm-page"><BrainOff /></div>

  if (status === 'loading') {
    return (
      <div className="tm-page">
        <p className="tm-dim">Connecting to the brain…</p>
      </div>
    )
  }

  if (status === 'error') {
    return (
      <div className="tm-page">
        <Card title="Could not reach the brain">
          <p className="tm-dim">Something went wrong talking to the brain. Try again shortly.</p>
        </Card>
      </div>
    )
  }

  if (status === 'no-run') {
    return (
      <div className="tm-page">
        <Card title="No run yet">
          <p className="tm-dim">The brain has not run yet.</p>
        </Card>
      </div>
    )
  }

  const run = latest.data!
  const ideas = ideasFrom(run)
  const holdings = holdingsFrom(run)
  const situation = marketSituation(run)
  const attention = holdings.filter((d) => ['MONITOR', 'REDUCE', 'EXIT'].includes(finalWord(d)))
  const top = ideas.slice(0, 5)

  const ideaCounts: Record<IdeaWord, number> = { TRADE: 0, WATCH: 0, WAIT: 0, AVOID: 0 }
  for (const d of ideas) {
    const w = finalWord(d)
    if (w in ideaCounts) ideaCounts[w as IdeaWord] += 1
  }

  // "Today's insights", built only from lines the brain actually returned:
  // the first reason behind each holding that needs attention, the market
  // situation's own evidence, and what the learning report says about
  // failures and drift. Nothing here is invented.
  type Insight = { text: string; tone: 'pos' | 'neg' | 'warn' | 'neutral' }
  const insights: Insight[] = []
  for (const d of attention) {
    if (d.reasons[0]) {
      insights.push({ text: `${d.symbol}: ${d.reasons[0]}`, tone: finalWord(d) === 'MONITOR' ? 'warn' : 'neg' })
    }
  }
  if (situation && situation.label !== 'unlabelled') {
    for (const e of situation.evidence) insights.push({ text: e, tone: 'neutral' })
  }
  for (const f of learning.data?.failures ?? []) insights.push({ text: f, tone: 'warn' })
  if (learning.data?.note) insights.push({ text: learning.data.note, tone: 'neutral' })

  return (
    <div className="tm-page tm-grid">
      {/* Hero: market mode · headline · situation */}
      <Card glow className="tm-hero">
        <div>
          <div className="tm-card-title" style={{ marginBottom: '0.9rem' }}>
            Market Mode
          </div>
          <div className="tm-hero-state">
            <span className="tm-state-icon">
              <Icon.Check />
            </span>
            <div>
              <div className="tm-state-word">{run.banner.mode ?? 'Unknown'}</div>
              {run.banner.mode && (
                <Tag tone={MARKET_TONE[run.banner.mode] ?? 'blue'}>{MARKET_PLAIN[run.banner.mode]}</Tag>
              )}
            </div>
          </div>
          {run.banner.headline && (
            <p className="tm-dim" style={{ fontSize: '0.78rem', margin: '0.9rem 0 0', maxWidth: 420 }}>
              {run.banner.headline}
            </p>
          )}
          {situation && situation.label !== 'unlabelled' && (
            <p className="tm-note" style={{ marginTop: '0.6rem' }}>
              Situation: {situation.label}
              {situation.is_unknown ? ' — never seen before' : ''}
              {situation.evidence[0] ? ` — ${situation.evidence[0]}` : ''}
            </p>
          )}
        </div>

        <div className="tm-brain">
          <BrainArt />
          <div className="tm-brain-title">TradeMind Brain</div>
        </div>
      </Card>

      <div className="tm-grid tm-cols-2">
        <Card title="Today's Ideas" sub="How many stocks got each decision" action={<Link className="tm-link" to="/trademind/opportunities">View All</Link>}>
          <div className="tm-grid tm-cols-4">
            {IDEA_WORDS.map((w) => (
              <div key={w} style={{ textAlign: 'center' }}>
                <div className="tm-stat-value" style={{ fontSize: '1.4rem' }}>
                  {ideaCounts[w]}
                </div>
                <div className="tm-stat-label">{w}</div>
              </div>
            ))}
          </div>
        </Card>

        <Card title="Holdings Needing Attention" sub="Stocks you hold that the brain flagged">
          {attention.length === 0 ? (
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
                    <span className="tm-dim">{d.reasons[0]}</span>
                  </span>
                  <Tag tone={HOLDING_TONE[finalWord(d)] ?? 'blue'}>{finalWord(d)}</Tag>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      <div className="tm-grid tm-cols-2">
        <Card title="Top Ideas" action={<Link className="tm-link" to="/trademind/opportunities">View All</Link>}>
          {top.length === 0 ? (
            <p className="tm-dim">No ideas to show right now.</p>
          ) : (
            <table className="tm-table">
              <tbody>
                {top.map((i) => (
                  <tr key={i.id} className="tm-clickable" onClick={() => navigate(`/trademind/stock/${encodeURIComponent(i.symbol)}`)}>
                    <td className="tm-strong">{i.symbol}</td>
                    <td>
                      <ActionPill action={finalWord(i) as Action} />
                    </td>
                    <td className="tm-num tm-right" title="Model score — a ranking, not a chance">
                      {i.confidence != null ? Math.round(i.confidence * 100) : '—'}
                    </td>
                    <td className="tm-dim">{i.reasons[0]}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>

        <Card title="Today's Insights">
          {learning.isLoading && <p className="tm-dim">Loading…</p>}
          {insights.length === 0 && !learning.isLoading ? (
            <p className="tm-dim">Nothing to report today.</p>
          ) : (
            insights.slice(0, 6).map((x, idx) => (
              <CheckItem key={idx} tone={x.tone}>
                {x.text}
              </CheckItem>
            ))
          )}
        </Card>
      </div>
    </div>
  )
}
