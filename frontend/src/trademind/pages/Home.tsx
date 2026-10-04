import { useNavigate, Link } from 'react-router-dom'

import type { Action } from '../types'
import type { IdeaWord } from '../../api/types'
import { formatDateTime } from '../../lib/format'
import { finalWord, ideasFrom, holdingsFrom, marketSituation, useLatestRun, useLearning } from '../live'
import { MARKET_LABEL, MARKET_PLAIN, MARKET_TONE, wordTagColor } from '../vocab'
import { ActionPill, BrainArt, BrainGate, Card, CheckItem, Icon, Tag } from '../ui'

const IDEA_WORDS: IdeaWord[] = ['TRADE', 'WATCH', 'WAIT', 'AVOID']

export default function Home() {
  return (
    <BrainGate>
      <HomeBody />
    </BrainGate>
  )
}

function HomeBody() {
  const navigate = useNavigate()
  const latest = useLatestRun()
  const learning = useLearning()

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
          <p className="tm-dim" style={{ fontSize: '0.72rem', margin: '-0.6rem 0 0.9rem' }}>
            From the brain's run on {formatDateTime(run.started_at)}
          </p>
          <div className="tm-hero-state">
            <span
              className="tm-state-icon"
              style={
                run.banner.mode && MARKET_TONE[run.banner.mode] !== 'green'
                  ? MARKET_TONE[run.banner.mode] === 'red'
                    ? { borderColor: 'var(--tm-red)', color: 'var(--tm-red)', boxShadow: '0 0 24px rgba(255,77,106,.5)' }
                    : { borderColor: 'var(--tm-amber)', color: 'var(--tm-amber)', boxShadow: '0 0 24px rgba(255,181,71,.5)' }
                  : undefined
              }
            >
              {run.banner.mode === 'NO_NEW_TRADES' ? <Icon.X /> : run.banner.mode === 'DEFENSIVE' ? <Icon.Alert /> : <Icon.Check />}
            </span>
            <div>
              <div className="tm-state-word">{run.banner.mode ? MARKET_LABEL[run.banner.mode] : 'Unknown'}</div>
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
          {holdings.length === 0 ? (
            <p className="tm-dim">The brain's last run saw no holdings.</p>
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
                    <span className="tm-dim">{d.reasons[0]}</span>
                  </span>
                  <Tag tone={wordTagColor(finalWord(d))}>{finalWord(d)}</Tag>
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
            <div className="tm-table-wrap">
              <table className="tm-table">
                <tbody>
                  {top.map((i) => (
                    <tr key={i.id} className="tm-clickable" onClick={() => navigate(`/trademind/stock/${encodeURIComponent(i.symbol)}`)}>
                      <td className="tm-strong">{i.symbol}</td>
                      <td>
                        <ActionPill action={finalWord(i) as Action} />
                      </td>
                      <td className="tm-num tm-right" title="Model score — a ranking, not a chance">
                        <span style={{ display: 'inline-flex', gap: '0.3rem', alignItems: 'center' }}>
                          {i.confidence != null ? Math.round(i.confidence * 100) : '—'}
                          <span className="tm-dim">model score</span>
                        </span>
                      </td>
                      <td className="tm-dim">{i.reasons[0]}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
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
