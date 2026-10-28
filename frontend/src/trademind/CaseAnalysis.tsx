// "The AI's case" for one stock, on the AI Analysis tab: one headline for the brain's word, then four small charts
// that answer what a customer asks before acting on it: where does the score stand, what do I stand to make or
// lose, did similar cases work before, and what could go wrong. Display only: every number is the brain's stored
// decision, its stored plan or the stock brief. Nothing here is a chance of profit and nothing places an order.

import type { BrainDecision, BrainRun } from '../api/types'
import type { StockBriefData } from './beginner/types'
import { finalWord } from './live'
import { rankText, scorePoints, scoreRank, SCORE_HINT } from './scoreText'
import { buyLevel, wordSay } from './stockParts'
import { MARKET_PLAIN } from './vocab'
import { inr } from './ui'

export type Scenario = { label: string; price: number; pct: number; perShare: number; tone: 'pos' | 'neg' }

export type CaseFigures = {
  score: number | null
  level: number | null
  /** Points above (+) or below (−) the buy level, or null when either is missing. */
  gap: number | null
  rank: string | null
  entry: number | null
  scenarios: Scenario[]
  /** Reward divided by risk at the stored target and stop, or null without a plan. */
  rewardToRisk: number | null
  record: { n: number; hits: number } | null
}

/** Pure: the numbers the four charts draw, from the stored decision only. */
export function caseFigures(d: BrainDecision, run: BrainRun): CaseFigures {
  const score = scorePoints(d.confidence)
  const level = buyLevel(d)
  const scores = run.decisions.filter((x) => x.kind === 'idea').map((x) => x.confidence)
  const rank = d.kind === 'idea' ? scoreRank(d.confidence, scores) : null
  const hasPlan = d.entry_low != null && d.target != null && d.stop != null
  const entry = hasPlan ? ((d.entry_low as number) + ((d.entry_high ?? d.entry_low) as number)) / 2 : null
  const scenarios: Scenario[] = []
  let rewardToRisk: number | null = null
  if (entry != null && d.target != null && d.stop != null) {
    const at = (label: string, price: number): Scenario => ({
      label,
      price,
      pct: (price / entry - 1) * 100,
      perShare: price - entry,
      tone: price >= entry ? 'pos' : 'neg',
    })
    scenarios.push(at('Target', d.target), at('Sell half', entry * 1.05), at('Stop', d.stop))
    const risk = entry - d.stop
    rewardToRisk = risk > 0 ? (d.target - entry) / risk : null
  }
  const tr = d.honest_score?.track_record
  const record =
    tr?.enough_evidence && tr.n != null && tr.hit_rate != null ? { n: tr.n, hits: Math.round(tr.hit_rate * tr.n) } : null
  return {
    score,
    level,
    gap: score != null && level != null ? score - level : null,
    rank: rank ? rankText(rank) : null,
    entry,
    scenarios,
    rewardToRisk,
    record,
  }
}

const HEADLINE: Record<string, string> = {
  TRADE: 'Why the AI says BUY',
  WATCH: 'Why the AI says WATCH, not BUY',
  WAIT: 'Why the AI says WAIT',
  AVOID: 'Why the AI says stay away',
}

export function CaseAnalysis({
  decision: d,
  run,
  brief,
}: {
  decision: BrainDecision
  run: BrainRun
  brief?: StockBriefData
}) {
  if (d.kind !== 'idea') return null
  const word = finalWord(d)
  const f = caseFigures(d, run)
  const mode = run.banner.mode
  const events = brief?.q5_events.events ?? []
  const changes = (d.what_would_change ?? []).filter((c) => c.text.trim() !== '')
  const worst = Math.max(...f.scenarios.map((s) => Math.abs(s.pct)), 1)
  const risks: string[] = []
  if (mode && MARKET_PLAIN[mode] && mode !== 'NORMAL') risks.push(MARKET_PLAIN[mode]!)
  if (events[0]) risks.push(events[0].plain)
  if (d.stop != null && f.entry != null) {
    risks.push(`If the price falls to ₹${inr(d.stop)} the plan is to sell: about ₹${inr(f.entry - d.stop)} lost per share.`)
  }
  if (word !== 'TRADE') for (const c of changes.slice(0, 3)) risks.push(c.text)

  return (
    <section className="sp-card sp-stack" aria-label={`The AI's case for ${d.symbol}`} data-testid="case-analysis" data-word={word}>
      <div>
        <h2 className="sp-h2">{HEADLINE[word] ?? 'What the AI says'}</h2>
        <div className="sp-sub">{wordSay(word)}</div>
      </div>

      <div className="sp-grid2">
        <div className="sp-card sp-card-flat sp-stack" data-testid="case-score">
          <h3 className="sp-h3">Where the score stands</h3>
          {f.score == null ? (
            <p className="sp-small">No score was stored for this stock.</p>
          ) : (
            <>
              <div className="sp-track" role="img" aria-label={`Score ${f.score} out of 100${f.level != null ? `, buy level ${f.level}` : ''}`}>
                {f.level != null && <i className="sp-track-zone" style={{ left: `${f.level}%` }} />}
                {f.level != null && <i className="sp-track-level" style={{ left: `${f.level}%` }}><em>Buy level {f.level}</em></i>}
                <i className="sp-track-score" style={{ left: `${f.score}%` }}><em>{f.score}</em></i>
              </div>
              <p className="sp-bigtext" style={{ fontSize: 16 }}>
                {f.gap == null
                  ? `Score ${f.score} out of 100.`
                  : f.gap >= 0
                    ? `Score ${f.score}: ${f.gap} ${f.gap === 1 ? 'point' : 'points'} above the buy level.`
                    : `Score ${f.score}: ${-f.gap} ${f.gap === -1 ? 'point' : 'points'} below the buy level.`}
              </p>
              {f.rank && <p className="sp-small">{f.rank}. {SCORE_HINT}</p>}
            </>
          )}
        </div>

        <div className="sp-card sp-card-flat sp-stack" data-testid="case-scenarios">
          <h3 className="sp-h3">{word === 'TRADE' ? 'If it works, and if it does not' : 'If it became a BUY'}</h3>
          {f.scenarios.length === 0 ? (
            <p className="sp-small">The brain stores a plan only for a stock it wants to buy.</p>
          ) : (
            <>
              <div className="sp-stack" style={{ gap: 8 }}>
                {f.scenarios.map((s) => (
                  <div key={s.label} className="sp-bar-row">
                    <span>{s.label}</span>
                    <div><i style={{ width: `${(Math.abs(s.pct) / worst) * 100}%`, background: s.tone === 'pos' ? 'var(--sp-green)' : 'var(--sp-red)' }} /></div>
                    <b className={s.tone === 'pos' ? 'sp-pos' : 'sp-neg'}>
                      {s.pct >= 0 ? '+' : '−'}{Math.abs(s.pct).toFixed(0)}% · ₹{inr(s.price)}
                    </b>
                  </div>
                ))}
              </div>
              {f.rewardToRisk != null && (
                <p className="sp-small">
                  Aim to make about {f.rewardToRisk.toFixed(1)}× what is risked. Out within {d.horizon_days} trading days.
                </p>
              )}
            </>
          )}
        </div>

        <div className="sp-card sp-card-flat sp-stack" data-testid="case-record">
          <h3 className="sp-h3">Did similar cases work before?</h3>
          {f.record ? (
            <>
              <div className="sp-record" role="img" aria-label={`${f.record.hits} of ${f.record.n} similar cases reached the target`}>
                <i style={{ width: `${(f.record.hits / f.record.n) * 100}%` }} />
              </div>
              <p className="sp-bigtext" style={{ fontSize: 16 }}>
                {f.record.hits} of {f.record.n} similar past cases reached the target.
              </p>
              <p className="sp-small">Measured on past months. It is history, not a promise.</p>
            </>
          ) : (
            <p className="sp-small">Not enough similar past cases to measure yet, so no record is shown.</p>
          )}
        </div>

        <div className="sp-card sp-card-flat sp-stack" data-testid="case-risks">
          <h3 className="sp-h3">{word === 'TRADE' ? 'What could go wrong' : 'What would have to change'}</h3>
          {risks.length === 0 ? (
            <p className="sp-small">Nothing unusual was recorded for this stock.</p>
          ) : (
            <ul className="sp-list">
              {risks.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          )}
        </div>
      </div>
      <p className="sp-small">AI research signal, not investment advice. Past results are not a promise.</p>
    </section>
  )
}

// ------------------------------------------------------------------ model evidence --

export type EvidenceFigures =
  | { kind: 'none'; text: string }
  | {
      kind: 'record'
      hitPct: number
      n: number
      windows: number | null
      lowPct: number | null
      highPct: number | null
      period: string | null
      rule: string
      enough: boolean
    }

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
function monthYear(iso: string): string {
  const [y, m] = iso.split('-')
  const i = Number(m) - 1
  return MONTHS[i] ? `${MONTHS[i]} ${y}` : iso
}

/** Pure: the model's measured record for scores like this one, from the stored `honest_score` only. */
export function evidenceFigures(d: BrainDecision): EvidenceFigures {
  const h = d.honest_score
  const tr = h?.track_record
  if (!h || h.status === 'no_score') return { kind: 'none', text: 'No score was stored for this stock, so there is no record to show.' }
  if (h.status === 'not_measured' || !tr || tr.hit_rate == null || tr.n == null) {
    return {
      kind: 'none',
      text: h.note ?? 'This score has not been measured against the +8% / −4% question yet, so no record is shown.',
    }
  }
  return {
    kind: 'record',
    hitPct: Math.round(tr.hit_rate * 100),
    n: tr.n,
    windows: tr.windows ?? null,
    lowPct: tr.lowest_window != null ? Math.round(tr.lowest_window * 100) : null,
    highPct: tr.highest_window != null ? Math.round(tr.highest_window * 100) : null,
    period: h.period ? `${monthYear(h.period.from)} to ${monthYear(h.period.to)}` : null,
    rule: h.rule ?? '+8% target before the −4% stop, within 15 trading days',
    enough: tr.enough_evidence,
  }
}

/** "How far can the AI's score be trusted?": the model's measured record on past months it had not seen. Not the
 * sealed live trial (its results stay hidden until its review): this is the earlier walk-forward test. */
export function ModelEvidence({ decision: d }: { decision: BrainDecision }) {
  if (d.kind !== 'idea') return null
  const e = evidenceFigures(d)
  return (
    <section className="sp-card sp-stack" aria-label="How far the AI's score can be trusted" data-testid="model-evidence">
      <div>
        <h2 className="sp-h2">How far can the AI’s score be trusted?</h2>
        <div className="sp-sub">The model’s record on past months it had not seen when it scored them.</div>
      </div>
      {e.kind === 'none' ? (
        <p className="sp-small">{e.text}</p>
      ) : (
        <>
          <p className="sp-bigtext">
            In {e.n.toLocaleString('en-IN')} past cases with a score like this, {e.hitPct} in 100 reached the goal.
          </p>
          <div className="sp-range" role="img" aria-label={`Hit rate ${e.hitPct}%${e.lowPct != null && e.highPct != null ? `, between ${e.lowPct}% and ${e.highPct}% across market periods` : ''}`}>
            {e.lowPct != null && e.highPct != null && (
              <i className="sp-range-span" style={{ left: `${e.lowPct}%`, width: `${Math.max(1, e.highPct - e.lowPct)}%` }} />
            )}
            <i className="sp-range-mark" style={{ left: `${e.hitPct}%` }}><em>{e.hitPct}%</em></i>
          </div>
          <div className="sp-between">
            <span>0 in 100</span>
            <span>100 in 100</span>
          </div>
          <ul className="sp-list">
            <li>The goal: {e.rule}.</li>
            {e.period && <li>Tested on {e.period}{e.windows != null ? `, across ${e.windows} market periods` : ''}.</li>}
            {e.lowPct != null && e.highPct != null && (
              <li>It moved between {e.lowPct} and {e.highPct} in 100 from one market period to another, so treat it as a rough guide.</li>
            )}
            {!e.enough && <li>There are few cases for this score range, so the record is weak.</li>}
          </ul>
        </>
      )}
      <p className="sp-small">Past results do not guarantee future results. The score is a ranking, not a chance of profit.</p>
    </section>
  )
}
