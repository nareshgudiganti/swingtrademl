// The new look's full-analysis page for one stock: opened from the stock page's "Full analysis" and "AI analysis"
// buttons. The same eight steps with every line in full, the score day by day, what the AI sees, the three
// full answers (money, coming up, worked before), the company, what changed since yesterday and the price chart.
// Display only: reads the brain's latest run and stored data.

import { Link, Navigate, useParams, useSearchParams } from 'react-router-dom'

import type { BrainDecision, BrainRun } from '../../api/types'
import { usePlan } from '../../lib/plan'
import { formatDateTime } from '../../lib/format'
import type { StockBriefData } from '../beginner/types'
import { NO_EVENTS } from '../beginner/UpcomingEvents'
import { changeHeadline, rankLine } from '../changes'
import { useSymbolCaps } from '../cap'
import { finalWord, stockSituations, useLatestRun } from '../live'
import { barsFrom } from '../live-stock'
import { scorePoints, SCORE_HINT } from '../scoreText'
import { BrainGate, Candles, inr } from '../ui'
import { wordLabel } from '../vocab'
import {
  BrainFlow,
  buyLevel,
  CompanyCard,
  PlanLadder,
  SafetyInWords,
  StockHeader,
  stepPasses,
  useStockData,
  wordSay,
  wordTone,
  type TrailPoint,
} from '../stockParts'
import { brainSteps, stopOf } from '../brainSteps'
import { CompanyTab } from '../CompanyTab'
import { CaseAnalysis, ModelEvidence } from '../CaseAnalysis'
import { CAP_LABEL } from './StockNew'
import { Overrule } from './StockDetail'

export default function StockAnalysis() {
  return (
    <BrainGate>
      <StockAnalysisBody />
    </BrainGate>
  )
}

function StockAnalysisBody() {
  const symbol = (useParams().symbol ?? '').toUpperCase()
  const run = useLatestRun().data!
  const decision = run.decisions.find((d) => d.symbol.toUpperCase() === symbol)
  if (!decision) return <Navigate to={`/trademind/stock/${encodeURIComponent(symbol)}`} replace />
  return <StockAnalysisView decision={decision} run={run} />
}

function StockAnalysisView({ decision: d, run }: { decision: BrainDecision; run: BrainRun }) {
  const caps = useSymbolCaps()
  const { canManage } = usePlan()
  const data = useStockData(d, run)
  const [params, setParams] = useSearchParams()
  const tab = params.get('tab') === 'company' ? 'company' : 'brain'
  const word = finalWord(d)
  const back = `/trademind/stock/${encodeURIComponent(d.symbol)}`
  const cap = caps.get(d.symbol.toUpperCase())
  const steps = brainSteps(d, run, canManage)
  const passes = stepPasses(d, steps, canManage)
  const passed = passes.filter((p) => p === 'yes').length
  const applicable = steps.length
  const stop = stopOf(d, canManage)
  const answer = stop
    ? `Not a BUY today. ${d.symbol} passed ${passed} of ${applicable} steps and stopped at step ${steps.findIndex((x) => x.n === stop.step) + 1}.`
    : word === 'TRADE'
      ? `Every check passed. ${wordSay(word)}`
      : wordSay(word)
  const bars = barsFrom(data.candleRows)

  return (
    <div className="tm-page sp" data-page="stock-analysis">
      <div className="sp-flow-head" style={{ marginBottom: 0 }}>
        <Link to={back} className="sp-back">
          ‹ Back to {d.symbol}
        </Link>
        <span className="sp-label">Full analysis</span>
      </div>
      <StockHeader
        decision={d}
        last={data.last}
        prev={data.prev}
        change={data.change}
        snapshot={data.snapshot}
        cap={cap ? CAP_LABEL[cap] : undefined}
      />

      <div className="sp-tabs" role="tablist" aria-label="Full analysis sections">
        {(
          [
            ['brain', 'Brain’s decision'],
            ['company', 'Company and news'],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={tab === id}
            data-testid={`tab-${id}`}
            className="sp-tab"
            onClick={() => setParams(id === 'brain' ? {} : { tab: id }, { replace: true })}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === 'company' ? (
        <CompanyTab symbol={d.symbol} />
      ) : (
        <>
      <section className="sp-answer" data-tone={wordTone(word)} data-testid="analysis-answer">
        <div className="sp-row" style={{ gap: 16, flexWrap: 'wrap' }}>
          <span className="sp-answer-word">{wordLabel(word)}</span>
          <span className="sp-answer-text">{answer}</span>
        </div>
        <span className="sp-small">Brain’s run on {formatDateTime(run.started_at)}</span>
      </section>

      <CaseAnalysis decision={d} run={run} brief={data.brief} />
      <ModelEvidence decision={d} />

      <BrainFlow decision={d} run={run} full />
      <SafetyInWords decision={d} />

      <div className="sp-split">
        <ScoreChart decision={d} trail={data.trail} />
        <WhatAISees decision={d} run={run} />
      </div>

      <Stories brief={data.brief} />

      <div className="sp-split">
        <PlanLadder decision={d} />
        <CompanyCard brief={data.brief} full />
      </div>

      <section className="sp-card sp-stack" aria-label="What changed since yesterday" data-testid="what-changed">
        <div>
          <h2 className="sp-h2">What changed since yesterday?</h2>
          <div className="sp-sub">Compared with the brain’s previous nightly run.</div>
        </div>
        {data.idea ? (
          <>
            <p className="sp-bigtext" style={{ fontSize: 17 }}>{changeHeadline(data.idea)}</p>
            {rankLine(data.idea) && <p>{rankLine(data.idea)}</p>}
          </>
        ) : (
          <p className="sp-small">{data.changesNote ?? 'There is no earlier nightly run to compare with yet.'}</p>
        )}
        <p className="sp-small">The ranking compares stocks with each other on the same day. It is not a chance of profit.</p>
      </section>

      {bars.length > 0 && (
        <section className="sp-card sp-stack" aria-label="Price chart">
          <h2 className="sp-h2">{d.symbol} · daily price</h2>
          <Candles bars={bars} height={300} target={d.target ?? undefined} stop={d.stop ?? undefined} />
        </section>
      )}

      {canManage && (
        <section className="sp-card sp-stack" aria-label="Change the decision">
          <h2 className="sp-h2">Disagree with the brain?</h2>
          <Overrule decision={d} />
        </section>
      )}
        </>
      )}
    </div>
  )
}

// ------------------------------------------------------------- score chart

function ScoreChart({ decision: d, trail }: { decision: BrainDecision; trail: TrailPoint[] }) {
  const days = trail.slice(-12)
  const level = buyLevel(d)
  return (
    <section className="sp-card sp-stack" style={{ flex: '1 1 560px' }} aria-label="Strength score, day by day" data-testid="score-chart">
      <div>
        <h2 className="sp-h2">Strength score, day by day</h2>
        <div className="sp-sub">{level != null ? 'Above the dashed line, the brain likes it enough to buy.' : 'How strongly the model liked this stock each day.'}</div>
      </div>
      {days.length < 2 ? (
        <p className="sp-small">No daily scores saved for this stock yet. The list starts with the next daily check.</p>
      ) : (
        <>
          <div className="sp-chart">
            {level != null && (
              <div className="sp-chart-line" style={{ bottom: `${level}%` }}>
                <span>Buy level {level}</span>
              </div>
            )}
            {days.map((t, i) => (
              <i key={t.date} style={{ height: `${Math.max(3, Math.round(t.score * 100))}%` }} title={`${t.date}: ${Math.round(t.score * 100)}`}>
                {i === days.length - 1 && <em>{Math.round(t.score * 100)}</em>}
              </i>
            ))}
          </div>
          <div className="sp-between">
            <span>{days.length} days ago</span>
            <span>Today</span>
          </div>
        </>
      )}
    </section>
  )
}

// ----------------------------------------------------------- what AI sees

function WhatAISees({ decision: d, run }: { decision: BrainDecision; run: BrainRun }) {
  const sit = stockSituations(run, d.symbol).find((s) => s.label && s.label !== 'unlabelled')
  const pts = scorePoints(d.confidence)
  const level = buyLevel(d)
  const tr = d.honest_score?.track_record
  const hasRecord = !!(tr?.enough_evidence && tr.n != null && tr.hit_rate != null)
  const hits = hasRecord ? Math.round((tr!.hit_rate ?? 0) * (tr!.n ?? 0)) : 0
  const dial = (pct: number, color: string) => `conic-gradient(${color} 0 ${pct}%, #e4e6f0 ${pct}% 100%)`
  return (
    <section className="sp-card sp-stack" style={{ flex: '1 1 440px' }} aria-label={`What the AI sees in ${d.symbol}`} data-testid="what-ai-sees">
      <h2 className="sp-h2">What the AI sees in {d.symbol}</h2>
      <div className="sp-sees">
        <div className="sp-sees-icon">↔</div>
        <div>
          <div style={{ fontWeight: 700, fontSize: 15 }}>
            {sit ? `Situation: ${sit.label}${sit.is_unknown ? ' (never seen before)' : ''}` : 'No special situation named'}
          </div>
          <div className="sp-small" style={{ fontSize: 13 }}>
            {sit?.evidence[0] ?? 'The brain did not name a special situation for this stock.'}
          </div>
        </div>
      </div>
      <div className="sp-rings">
        <div className="sp-ring">
          <div className="sp-ring-dial" style={{ background: dial(pts ?? 0, '#3f55d6') }}>
            <b>{pts ?? '—'}</b>
          </div>
          <div style={{ fontSize: 13, fontWeight: 700 }}>Model score</div>
          <div className="sp-small">Out of 100</div>
        </div>
        <div className="sp-ring">
          {level != null ? (
            <div className="sp-ring-dial" style={{ background: dial(level, '#e0a72b') }}>
              <b>{level}</b>
            </div>
          ) : (
            <div className="sp-ring-dial sp-ring-empty">–</div>
          )}
          <div style={{ fontSize: 13, fontWeight: 700 }}>Buy level</div>
          <div className="sp-small">Score needed to buy</div>
        </div>
        <div className="sp-ring">
          {hasRecord ? (
            <div className="sp-ring-dial" style={{ background: dial(Math.round((tr!.hit_rate ?? 0) * 100), '#1f9d6b') }}>
              <b>{hits}/{tr!.n}</b>
            </div>
          ) : (
            <div className="sp-ring-dial sp-ring-empty">?</div>
          )}
          <div style={{ fontSize: 13, fontWeight: 700 }}>Past record</div>
          <div className="sp-small">
            {hasRecord ? `${hits} of ${tr!.n} similar cases reached the target` : 'No similar cases yet'}
          </div>
        </div>
      </div>
      <p className="sp-small">{SCORE_HINT}</p>
    </section>
  )
}

// ----------------------------------------------------------- story cards

function Stories({ brief }: { brief?: StockBriefData }) {
  const m = brief?.q4_money
  const loss = m?.available ? Math.abs(m.loss_if_stop ?? 0) : 0
  const gain = m?.available ? Math.abs(m.gain_if_target ?? 0) : 0
  const top = Math.max(loss, gain, 1)
  const events = brief?.q5_events.events ?? []
  const ev = brief?.q6_evidence

  return (
    <div className="sp-grid3" data-testid="story-cards">
      <section className="sp-card sp-stack" aria-label="How much money is at stake?">
        <h3 className="sp-h3">How much money is at stake?</h3>
        {!brief && <p className="sp-small">Loading…</p>}
        {m && !m.available && (
          <>
            <p className="sp-bigtext">{m.answer}</p>
            {m.why && <p className="sp-small">{m.why}</p>}
          </>
        )}
        {m?.available && (
          <>
            <p className="sp-bigtext">
              Risk about ₹{inr(loss, 0)} to make about ₹{inr(gain, 0)}.
            </p>
            <div className="sp-stack" style={{ gap: 8 }}>
              <div className="sp-bar-row">
                <span>If it works</span>
                <div><i style={{ width: `${(gain / top) * 100}%`, background: 'var(--sp-green)' }} /></div>
                <b className="sp-pos">+₹{inr(gain, 0)}</b>
              </div>
              <div className="sp-bar-row">
                <span>If it fails</span>
                <div><i style={{ width: `${(loss / top) * 100}%`, background: 'var(--sp-red)' }} /></div>
                <b className="sp-neg">−₹{inr(loss, 0)}</b>
              </div>
            </div>
            <p className="sp-small">All figures are after charges. Money put in: ₹{inr(m.invested ?? 0, 0)}.</p>
          </>
        )}
      </section>

      <section className="sp-card sp-stack" aria-label="Is anything coming up?">
        <h3 className="sp-h3">Is anything coming up?</h3>
        {!brief && <p className="sp-small">Loading…</p>}
        {brief && events.length === 0 && <p className="sp-bigtext">{brief.q5_events.available ? NO_EVENTS : brief.q5_events.answer}</p>}
        {events.length > 0 && (
          <>
            <p className="sp-bigtext">{events[0]!.plain}</p>
            <div className="sp-eventline" aria-hidden="true">
              <div className="sp-eventline-track" />
              <small style={{ left: 0 }}>Today</small>
              {events.map((e) => (
                <div
                  key={`${e.kind}-${e.date}`}
                  className="sp-eventline-dot"
                  style={{ left: `calc(${Math.min(100, (e.trading_days_away / 15) * 100)}% - 10px)` }}
                />
              ))}
              <small style={{ right: 0 }}>Day 15</small>
            </div>
            {events.slice(1).map((e) => (
              <p key={`${e.kind}-${e.date}`} className="sp-small">{e.plain}</p>
            ))}
          </>
        )}
      </section>

      <section className="sp-card sp-stack" aria-label="Has this kind of idea worked before?">
        <h3 className="sp-h3">Has this kind of idea worked before?</h3>
        {!brief && <p className="sp-small">Loading…</p>}
        {ev && (
          <>
            <p className="sp-bigtext">{ev.answer}</p>
            <div className="sp-boxes" aria-hidden="true">
              <i /><i /><i /><i /><i />
            </div>
            <p className="sp-small">Each box fills in when a similar idea finishes. Not shown as proof unless it says Proven.</p>
          </>
        )}
      </section>
    </div>
  )
}
