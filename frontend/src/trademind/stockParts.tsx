// The pieces of the new look's stock page and its full-analysis page (stockpage.css). Display only: everything
// comes from the brain's latest run, the stored candles, the daily score trail and the plain-words brief.

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import { api } from '../api/client'
import type { BrainDecision, BrainRun, PriceSnapshot } from '../api/types'
import { useStockBrief } from './beginner/api'
import { NO_EVENTS } from './beginner/UpcomingEvents'
import type { StockBriefData } from './beginner/types'
import { brainSteps, stopOf, type BrainStep } from './brainSteps'
import { ideaChange, ordinal, useChanges, type IdeaChange } from './changes'
import { useSymbolCaps } from './cap'
import { finalWord } from './live'
import { scorePoints, scoreRank, withoutScorePercent, SCORE_HINT } from './scoreText'
import { dayLabel } from './pricesAge'
import { inr } from './ui'
import { wordTagColor } from './vocab'
import './stockpage.css'

// ------------------------------------------------------------------ data --

export type TrailPoint = { date: string; score: number }

/** Everything the two pages read for one stock, in one place (same query keys as the rest of the app). */
export function useStockData(decision: BrainDecision, run: BrainRun) {
  const symbol = decision.symbol
  const candles = useQuery({ queryKey: ['candles', symbol, 66], queryFn: () => api.candles(symbol, 66) })
  const trail = useQuery({
    queryKey: ['stock-score-trail', symbol],
    queryFn: () => api.stockScoreTrail(symbol),
    retry: false,
  })
  const brief = useStockBrief(symbol)
  const changes = useChanges(decision.kind === 'idea' ? run.run_id : undefined)

  // The current price is its own, separately timestamped read. The brain's decision stays frozen
  // to its run; only this number moves. Without a snapshot we fall back to the stored closes.
  const snap = useQuery({
    queryKey: ['price-snapshot', symbol],
    queryFn: () => api.priceSnapshot(symbol),
    refetchInterval: 60_000,
    retry: false,
  })
  const snapshot = snap.data && snap.data.price != null ? snap.data : undefined

  const rows = candles.data ?? []
  const last = snapshot ? snapshot.price! : rows.at(-1)?.close
  const prev = snapshot ? (snapshot.prev_close ?? undefined) : rows.at(-2)?.close
  const change =
    snapshot ? (snapshot.change_pct != null && prev ? last! - prev : null) : last != null && prev ? last - prev : null
  const row = changes.data?.ideas.find((r) => r.symbol.toUpperCase() === symbol.toUpperCase())
  const idea: IdeaChange | null = row ? ideaChange(row) : null

  return {
    candleRows: rows,
    snapshot,
    last,
    prev,
    change,
    trail: (trail.data?.score_trail ?? []).map((t) => ({ date: t.date, score: t.score })),
    brief: brief.data as StockBriefData | undefined,
    idea,
    changesNote: changes.data && !changes.data.comparable ? changes.data.note : null,
  }
}

/** The buy level the brain stored in its own words ("... against a buy level of 60"), or null. */
export function buyLevel(d: BrainDecision): number | null {
  for (const r of d.reasons) {
    const m = /buy level(?: of| to| is)?\s+(\d+(?:\.\d+)?)/i.exec(r)
    if (m?.[1]) return Math.round(Number(m[1]))
  }
  return null
}

const WORD_SAY: Record<string, string> = {
  TRADE: 'Buy it, with the usual plan.',
  WATCH: 'Good idea. Keep an eye on it, not a buy today.',
  WAIT: 'Nothing to do today.',
  AVOID: 'Stay away for now.',
  HOLD: 'Keep it: the plan is working.',
  MONITOR: 'Keep it, but watch it closely.',
  REDUCE: 'Sell some.',
  EXIT: 'Sell it all.',
}

export const wordSay = (word: string): string => WORD_SAY[word] ?? word

/** Owner decision (ss11): no Buy on ideas the brain says WAIT or AVOID. */
export const brainAllowsBuy = (word: string): boolean => word !== 'AVOID' && word !== 'WAIT'

export function wordTone(word: string): 'green' | 'amber' | 'red' | 'grey' {
  const c = wordTagColor(word)
  return c === 'green' ? 'green' : c === 'amber' ? 'amber' : c === 'red' ? 'red' : 'grey'
}

const SHORT = ['Data', 'Market', 'Situation', 'Memory', 'Opinion', 'Safety check', 'Decide', 'Learn'] as const

type Pass = 'yes' | 'stop' | 'no'

/** For each of the eight steps: passed, stopped here, or not reached / not recorded. */
export function stepPasses(d: BrainDecision, steps: BrainStep[]): Pass[] {
  const stop = stopOf(d)
  const stopAt = stop?.step ?? 99
  return steps.map((s) => {
    if (s.n === stopAt) return 'stop'
    if (s.n > stopAt) return 'no'
    return s.state === 'none' || s.state === 'later' ? 'no' : 'yes'
  })
}

// ---------------------------------------------------------------- header --

function initials(symbol: string): string {
  return symbol.replace(/[^A-Z]/g, '').slice(0, 3) || symbol.slice(0, 3)
}

export function StockMark({ symbol }: { symbol: string }) {
  return (
    <div className="sp-logo">
      <div className="sp-logo-mark">{initials(symbol)}</div>
    </div>
  )
}

/** The paper Buy: same practice-book buy as Opportunities, for this stock. */
export function BuyBox({ symbol, open, onClose }: { symbol: string; open: boolean; onClose: () => void }) {
  const queryClient = useQueryClient()
  const caps = useSymbolCaps()
  const [qty, setQty] = useState('1')
  const buy = useMutation({
    mutationFn: () =>
      api.testerPaperBuy({ symbol, quantity: Number(qty), cap_tier: caps.get(symbol.toUpperCase()) ?? 'large' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['testerPositions'] })
      queryClient.invalidateQueries({ queryKey: ['testerSummary'] })
    },
  })
  if (!open) return null
  return (
    <form
      className="sp-buyform"
      data-testid="buy-form"
      onSubmit={(e) => {
        e.preventDefault()
        buy.mutate()
      }}
    >
      <b>Paper buy {symbol}</b>
      <input
        type="number"
        min={1}
        value={qty}
        onChange={(e) => setQty(e.target.value)}
        aria-label="Quantity"
      />
      <button className="sp-btn sp-btn-buy" type="submit" disabled={!Number(qty) || buy.isPending}>
        {buy.isPending ? 'Buying…' : 'Confirm buy'}
      </button>
      <button className="sp-btn" type="button" onClick={onClose}>
        Close
      </button>
      {buy.isSuccess && (
        <span className="sp-pos" style={{ fontWeight: 700 }}>
          Bought {buy.data.quantity} × {buy.data.symbol} at ₹{inr(buy.data.entry_price)} (practice money).
        </span>
      )}
      {buy.isError && <span className="sp-err">{(buy.error as Error).message}</span>}
    </form>
  )
}

export function StockHeader({
  decision: d,
  last,
  change,
  prev,
  cap,
  analysisTo,
  snapshot,
  withBuy = true,
}: {
  decision: BrainDecision
  last?: number
  change: number | null
  prev?: number
  cap?: string
  analysisTo?: string
  snapshot?: PriceSnapshot
  withBuy?: boolean
}) {
  const [buying, setBuying] = useState(false)
  const up = (change ?? 0) >= 0
  const buyOk = brainAllowsBuy(finalWord(d))
  return (
    <>
      <div className="sp-head">
        <div className="sp-id">
          <StockMark symbol={d.symbol} />
          <div style={{ minWidth: 0 }}>
            <div className="sp-name">
              <h1 className="sp-sym">{d.symbol}</h1>
              {cap && <span className="sp-cap">{cap}</span>}
            </div>
            <div className="sp-tagline">
              {d.kind === 'holding' ? 'A stock the bot holds (paper)' : 'An idea from tonight’s run'}
            </div>
          </div>
        </div>
        <div className="sp-actions">
          {last != null && (
            <div className="sp-price">
              <b>₹{inr(last)}</b>
              {change != null && prev ? (
                <span className={up ? 'sp-pos' : 'sp-neg'}>
                  {up ? '▲' : '▼'} ₹{inr(Math.abs(change))} ({Math.abs((change / prev) * 100).toFixed(2)}%){snapshot ? '' : ' at last close'}
                </span>
              ) : null}
              {snapshot && (
                <span
                  className={`sp-small${snapshot.state === 'stale' || snapshot.state === 'delayed' ? ' sp-neg' : ''}`}
                  data-testid="price-note"
                  data-state={snapshot.state}
                >
                  {snapshot.note}
                </span>
              )}
            </div>
          )}
          {withBuy && !buyOk && (
            <span className="sp-small" data-testid="no-buy-note" style={{ maxWidth: 190 }}>
              The brain says {finalWord(d)}, so there is no Buy here.
            </span>
          )}
          {withBuy && buyOk && (
            <div className="sp-btnbox">
              <button className="sp-btn sp-btn-buy" type="button" onClick={() => setBuying((v) => !v)} data-testid="buy-button">
                Buy
              </button>
              <span className="sp-small" style={{ textAlign: 'center' }}>
                Paper buy · practice money
              </span>
            </div>
          )}
          {analysisTo && (
            <Link className="sp-btn" to={analysisTo}>
              Full analysis ›
            </Link>
          )}
        </div>
      </div>
      {withBuy && buyOk && <BuyBox symbol={d.symbol} open={buying} onClose={() => setBuying(false)} />}
    </>
  )
}

// ---------------------------------------------------------------- glance --

export function Glance({
  decision: d,
  run,
  last,
  change,
  prev,
  trail,
  idea,
  runAt,
  snapshot,
}: {
  decision: BrainDecision
  run: BrainRun
  last?: number
  change: number | null
  prev?: number
  trail: TrailPoint[]
  idea: IdeaChange | null
  runAt?: string
  snapshot?: PriceSnapshot
}) {
  const word = finalWord(d)
  const pts = scorePoints(d.confidence)
  const level = buyLevel(d)
  const week = trail.slice(-5)
  const first = week[0]?.score
  const latest = week.at(-1)?.score
  const delta = first != null && latest != null ? Math.round((latest - first) * 100) : null
  const scores = run.decisions.filter((x) => x.kind === 'idea').map((x) => x.confidence)
  const rank = d.kind === 'idea' ? scoreRank(d.confidence, scores) : null
  const moved = idea?.placesMoved ?? null
  const pctMove = change != null && prev ? (change / prev) * 100 : null

  return (
    <div className="sp-glance" data-testid="stock-glance">
      <div className="sp-card sp-stat">
        <div className="sp-label">Strength score</div>
        <div className="sp-row">
          <span className="sp-big">{pts ?? '—'}</span>
          {pts != null && <span className="sp-small" style={{ fontSize: 14 }}>out of 100</span>}
          {delta != null && Math.abs(delta) >= 2 && (
            <span className={`sp-pill ${delta > 0 ? 'sp-pill-up' : 'sp-pill-down'}`} style={{ marginLeft: 'auto' }}>
              {delta > 0 ? '▲ rising' : '▼ easing'}
            </span>
          )}
        </div>
        {week.length >= 2 ? (
          <div className="sp-bars" aria-label="Strength score over the last days">
            {week.map((t) => (
              <i key={t.date} style={{ height: `${Math.max(6, Math.round(t.score * 100))}%` }} title={`${t.date}: ${Math.round(t.score * 100)}`} />
            ))}
          </div>
        ) : (
          <p className="sp-small">The day-by-day list starts with the next daily check.</p>
        )}
        <div className="sp-between">
          <span>{week.length >= 2 ? `Last ${week.length} days` : ' '}</span>
          {level != null && <span>Buy level: {level}</span>}
        </div>
      </div>

      <div className="sp-card sp-stat">
        <div className="sp-label">Rank today</div>
        <div className="sp-row">
          <span className="sp-big">{rank ? `#${rank.rank}` : '—'}</span>
          {rank && <span className="sp-small" style={{ fontSize: 14 }}>of {rank.of} stocks</span>}
        </div>
        {moved != null && moved !== 0 && (
          <span className={`sp-pill ${moved > 0 ? 'sp-pill-up' : 'sp-pill-down'}`}>
            {moved > 0 ? '▲' : '▼'} {Math.abs(moved)} {Math.abs(moved) === 1 ? 'place' : 'places'} since yesterday
          </span>
        )}
        <div className="sp-small">
          {idea?.rankBefore ? `Was ${ordinal(idea.rankBefore.rank)} yesterday. ` : ''}A ranking, not a chance of profit.
        </div>
      </div>

      <div className="sp-card sp-stat">
        <div className="sp-label">Price</div>
        <div className="sp-big" style={{ fontSize: 34 }}>{last != null ? `₹${inr(last)}` : '—'}</div>
        {pctMove != null && (
          <span className={`sp-pill ${pctMove >= 0 ? 'sp-pill-up' : 'sp-pill-down'}`}>
            {pctMove >= 0 ? '▲' : '▼'} {Math.abs(pctMove).toFixed(2)}%{snapshot ? '' : ' at last close'}
          </span>
        )}
        {d.entry_low != null && (
          <div className="sp-small">
            Plan buys between ₹{inr(d.entry_low, 0)}
            {d.entry_high != null && d.entry_high !== d.entry_low ? ` and ₹${inr(d.entry_high, 0)}` : ''}.
          </div>
        )}
      </div>

      <div className="sp-card sp-stat sp-word" data-tone={wordTone(word)}>
        <div className="sp-label">The brain says</div>
        <div className="sp-big">{word}</div>
        <div className="sp-say">{wordSay(word)}</div>
        {runAt && <div className="sp-small">{runAt}</div>}
      </div>
    </div>
  )
}

// ---------------------------------------------------------- score monitor --

const MONITOR_DAYS = 7

const dayMonth = (iso: string) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })

/** Whole calendar days between two ISO dates. */
function daysBetween(a: string, b: string): number {
  return Math.round((Date.parse(`${b}T00:00:00Z`) - Date.parse(`${a}T00:00:00Z`)) / 86_400_000)
}

/** The last few daily scores with their dates, so a falling or rising score is visible at a glance.
 *  Days the model did not run are left out, and a longer-than-a-weekend jump is marked, never filled in. */
export function ScoreMonitor({ trail, level }: { trail: TrailPoint[]; level?: number | string | null }) {
  const days = trail.slice(-MONITOR_DAYS)
  return (
    <section className="sp-card sp-monitor" aria-label="Strength score, day by day" data-testid="score-monitor">
      <div className="sp-flow-head" style={{ marginBottom: 0 }}>
        <div>
          <h2 className="sp-h2">Is the score holding up?</h2>
          <div className="sp-sub">The strength score on each of the last days the model checked this stock.</div>
        </div>
        {level != null && <span className="sp-pill sp-pill-amber">Buy level: {level}</span>}
      </div>
      {days.length === 0 ? (
        <p className="sp-small">No daily scores saved for this stock yet. The list starts with the next daily check.</p>
      ) : (
        <div className="sp-scroll">
          <ol className="sp-monitor-days">
            {days.map((t, i) => {
              const before = days[i - 1]
              const move = before ? Math.round((t.score - before.score) * 100) : null
              const gap = before ? daysBetween(before.date, t.date) > 3 : false
              return (
                <li key={t.date} data-testid="score-monitor-day" className={i === days.length - 1 ? 'sp-monitor-now' : undefined}>
                  <span className="sp-small">{dayMonth(t.date)}</span>
                  <strong>{Math.round(t.score * 100)}</strong>
                  {move != null && move !== 0 ? (
                    <span className={move > 0 ? 'sp-pos' : 'sp-neg'}>
                      {move > 0 ? '▲' : '▼'} {Math.abs(move)}
                    </span>
                  ) : (
                    <span className="sp-small">{before ? 'same' : ' '}</span>
                  )}
                  {gap && <span className="sp-small">after a gap</span>}
                </li>
              )
            })}
          </ol>
        </div>
      )}
    </section>
  )
}

// ------------------------------------------------------------------ flow --

export function BrainFlow({
  decision: d,
  run,
  analysisTo,
  full = false,
}: {
  decision: BrainDecision
  run: BrainRun
  analysisTo?: string
  full?: boolean
}) {
  const steps = brainSteps(d, run)
  const pass = stepPasses(d, steps)
  const stop = stopOf(d)
  const passed = pass.filter((p) => p === 'yes').length
  const lastIdx = pass.reduce((acc, p, i) => (p === 'yes' || p === 'stop' ? i : acc), 0)
  const changes = (d.what_would_change ?? []).filter((c) => c.text.trim() !== '')
  const [openStep, setOpenStep] = useState<number | null>(null)

  return (
    <section className="sp-card" aria-label={`How the brain thought about ${d.symbol}`} data-testid="brain-steps">
      <div className="sp-flow-head">
        <div>
          <h2 className="sp-h2">What does the brain say today, and why?</h2>
          <div className="sp-sub">
            {stop
              ? `${d.symbol} passed ${passed} of 8 steps and stopped at step ${stop.step}.`
              : `${d.symbol} passed ${passed} of 8 steps.`}
          </div>
        </div>
        <div className="sp-legend">
          <span><span className="sp-dot" style={{ background: 'var(--sp-green)' }} />Passed</span>
          <span><span className="sp-dot" style={{ background: 'var(--sp-red)' }} />Stopped here</span>
          <span><span className="sp-dot" style={{ background: '#c3c7d8' }} />Not reached</span>
        </div>
        {analysisTo && (
          <Link className="sp-btn sp-btn-ai" to={analysisTo} data-testid="ai-analysis-button">
            ✦ AI analysis ›
          </Link>
        )}
      </div>
      <div className="sp-scroll">
        <ol className={`sp-flow${full ? ' sp-flow-full' : ''}`}>
          <li className="sp-flow-done" style={{ width: `${lastIdx * 12.5}%` }} aria-hidden="true" />
          {steps.map((s, i) => (
            <li key={s.n} className="sp-step" data-pass={pass[i]} data-state={s.state}>
              <span className="sp-step-n">{s.n}</span>
              <b className="sp-step-t">{SHORT[i]}</b>
              {full ? (
                <span className="sp-step-l">{withoutScorePercent(s.line)}</span>
              ) : (
                <button
                  type="button"
                  className="sp-step-l sp-step-tap"
                  data-open={openStep === s.n}
                  aria-expanded={openStep === s.n}
                  onClick={() => setOpenStep(openStep === s.n ? null : s.n)}
                >
                  {withoutScorePercent(s.line)}
                </button>
              )}
              <span className="sp-chip" data-state={s.state}>{s.tag}</span>
            </li>
          ))}
        </ol>
      </div>
      {stop ? (
        <div className="sp-why" data-testid="why-stopped">
          <div className="sp-why-main">
            <div className="sp-why-kicker">Why it stopped · step {stop.step}, {SHORT[stop.step - 1]}</div>
            <div className="sp-why-text">{withoutScorePercent(stop.why.text)}</div>
            {stop.why.detail && <p className="sp-small" style={{ marginTop: 6 }}>What the brain recorded: {withoutScorePercent(stop.why.detail)}</p>}
          </div>
          {stop.why.kind === 'risk_no_room' && <MoneyMeter />}
          {changes.length > 0 && (
            <div className="sp-why-more">
              <b>What would change it</b>
              <ul>
                {changes.slice(0, full ? 6 : 3).map((c) => (
                  <li key={`${c.key}:${c.text}`}>{c.text}</li>
                ))}
              </ul>
            </div>
          )}
          {analysisTo && !full && (
            <Link to={analysisTo} style={{ fontWeight: 700, fontSize: 14, textDecoration: 'none', whiteSpace: 'nowrap' }}>
              See the details ›
            </Link>
          )}
        </div>
      ) : (
        <p className="sp-small" style={{ marginTop: 16 }}>
          Past cases are history, not a promise. {SCORE_HINT}
        </p>
      )}
    </section>
  )
}

/** "Room left to invest" against the smallest buy, from today's limits (not the 15:50 run's), so it says "right now". */
export function MoneyMeter() {
  const limits = useQuery({ queryKey: ['riskLimits'], queryFn: api.riskLimits, retry: false })
  const l = limits.data
  if (!l || !l.min_position_inr) return null
  const room = Math.max(0, l.room_inr)
  const need = l.min_position_inr
  const short = Math.max(0, need - room)
  const pct = Math.min(100, Math.round((room / need) * 100))
  return (
    <div className="sp-money" data-testid="money-meter">
      <div className="sp-between">
        <span>Room left to invest, right now</span>
        <span>smallest buy needs ₹{inr(need, 0)}</span>
      </div>
      <div className="sp-meter" role="img" aria-label={`₹${inr(room, 0)} free of ₹${inr(need, 0)} needed`}>
        <i style={{ width: `${pct}%` }} />
      </div>
      <div className="sp-between">
        <span><b>₹{inr(room, 0)}</b> free</span>
        {short > 0 ? <b className="sp-neg">₹{inr(short, 0)} short</b> : <b className="sp-pos">Enough room now</b>}
      </div>
      <p className="sp-small">
        Today’s limits (₹{inr(l.invested_inr, 0)} of ₹{inr(l.deployable_ceiling_inr, 0)} allowed is already invested). The brain’s 15:50 run may have seen different numbers.
      </p>
    </div>
  )
}

/** Step 6 in plain words (full-analysis page): the four money figures behind "no room", from today's limits. */
export function SafetyInWords({ decision: d }: { decision: BrainDecision }) {
  const limits = useQuery({ queryKey: ['riskLimits'], queryFn: api.riskLimits, retry: false })
  const l = limits.data
  if (stopOf(d)?.why.kind !== 'risk_no_room' || !l) return null
  const pct = Math.round(l.deployable_fraction * 100)
  const figures: [string, number, boolean][] = [
    ['Allowed to invest', l.deployable_ceiling_inr, false],
    ['Already invested', l.invested_inr, false],
    ['Room left', Math.max(0, l.room_inr), l.room_inr < l.min_position_inr],
    ['Smallest buy', l.min_position_inr, false],
  ]
  return (
    <section className="sp-card sp-stack" aria-label="Step 6 in plain words" data-testid="safety-in-words">
      <h2 className="sp-h2">Step 6 in plain words</h2>
      <p className="sp-bigtext" style={{ fontSize: 17 }}>
        {l.plain_regime ? `${l.plain_regime}: ` : ''}only {pct}% of your money may be invested right now.
      </p>
      <div className="sp-figs">
        {figures.map(([k, v, bad]) => (
          <div key={k} className="sp-card sp-card-flat">
            <span className="sp-small">{k}</span>
            <b className={bad ? 'sp-neg' : undefined} style={{ fontSize: 20 }}>₹{inr(v, 0)}</b>
          </div>
        ))}
      </div>
      <p className="sp-small">Today’s limits, not the 15:50 run’s. They change when the account or the market changes.</p>
    </section>
  )
}

// ----------------------------------------------------------------- plan ---

export function PlanLadder({ decision: d }: { decision: BrainDecision }) {
  if (d.kind !== 'idea' || d.entry_low == null || d.target == null || d.stop == null) return null
  const low = d.entry_low
  const high = d.entry_high ?? d.entry_low
  const mid = (low + high) / 2
  const half = mid * 1.05
  const word = finalWord(d)
  const pad = (d.target - d.stop) * 0.04
  const lo = d.stop - pad
  const hi = d.target + pad
  const at = (p: number) => `${(((p - lo) / (hi - lo)) * 100).toFixed(1)}%`
  const stopPct = ((d.stop / mid - 1) * 100).toFixed(0)
  const targetPct = ((d.target / mid - 1) * 100).toFixed(0)

  return (
    <section className="sp-card" aria-label="The plan" data-testid="plan-ladder" style={{ flex: '2 1 600px', display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div className="sp-flow-head" style={{ marginBottom: 0 }}>
        <div>
          <h2 className="sp-h2">What is the plan?</h2>
          <div className="sp-sub">{word === 'TRADE' ? 'The plan for this trade.' : 'If it becomes a TRADE. Same rules every time.'}</div>
        </div>
        <span className="sp-pill sp-pill-amber">Sold within {d.horizon_days} trading days</span>
      </div>
      <div className="sp-scroll">
        <div className="sp-ladder">
          <div className="sp-ladder-track" />
          <div className="sp-ladder-zone" style={{ left: at(low), width: `max(8px, calc(${at(high)} - ${at(low)}))` }} />
          <div className="sp-ladder-tick" style={{ left: at(d.stop), background: 'var(--sp-red)' }} />
          <div className="sp-ladder-tick" style={{ left: at(half), background: 'var(--sp-green)' }} />
          <div className="sp-ladder-tick" style={{ left: at(d.target), background: 'var(--sp-green-ink)' }} />
          <div className="sp-ladder-label" style={{ left: at(d.stop), top: 68 }}>
            <span className="sp-neg">Stop loss</span><b>₹{inr(d.stop)}</b><small>{stopPct}% · get out</small>
          </div>
          <div className="sp-ladder-label" style={{ left: `calc((${at(low)} + ${at(high)}) / 2)`, top: 0, width: 150 }}>
            <span style={{ color: 'var(--sp-blue-ink)' }}>Buy zone</span>
            <b>₹{inr(low, 0)}{high !== low ? ` – ₹${inr(high, 0)}` : ''}</b>
          </div>
          <div className="sp-ladder-label" style={{ left: at(half), top: 68 }}>
            <span className="sp-pos">Sell half</span><b>₹{inr(half)}</b><small>+5% · lock in</small>
          </div>
          <div className="sp-ladder-label" style={{ left: at(d.target), top: 68, transform: 'translateX(-72%)' }}>
            <span className="sp-pos">Target</span><b>₹{inr(d.target)}</b><small>+{targetPct}% · sell rest</small>
          </div>
        </div>
      </div>
    </section>
  )
}

// -------------------------------------------------------------- company ---

export function CompanyCard({ brief, full = false }: { brief?: StockBriefData; full?: boolean }) {
  const c = brief?.q1_company
  return (
    <section className="sp-card" aria-label="What is this company?" data-testid="company-card" style={{ flex: '1 1 320px', display: 'flex', flexDirection: 'column', gap: 12 }}>
      <h2 className="sp-h2">What is this company?</h2>
      {!brief && <p className="sp-small">Loading…</p>}
      {c && (
        <>
          <p style={{ fontSize: full ? 16 : 15, lineHeight: 1.55, fontWeight: 500 }}>{c.answer}</p>
          {!c.available && c.why && <p className="sp-small">{c.why}</p>}
          <div className="sp-tags">
            {c.size && <span className="sp-tag sp-tag-violet">{c.size}</span>}
            {c.sector && <span className="sp-tag sp-tag-blue">{c.sector}</span>}
            {c.name && <span className="sp-tag">{c.name}</span>}
          </div>
        </>
      )}
    </section>
  )
}

// ---------------------------------------------------------- quick answers -

const rupees = (n: number | null | undefined) => (n == null ? null : `₹${inr(Math.abs(n), 0)}`)

export function moneyLine(brief?: StockBriefData): string {
  const m = brief?.q4_money
  if (!m) return 'Loading…'
  if (!m.available) return m.answer || 'Not available yet.'
  const loss = rupees(m.loss_if_stop)
  const gain = rupees(m.gain_if_target)
  return loss && gain ? `Risk about ${loss} to make about ${gain}` : m.answer
}

export function eventLine(brief?: StockBriefData): string {
  const e = brief?.q5_events
  if (!e) return 'Loading…'
  const first = e.events?.[0]
  return first ? first.plain : e.available ? NO_EVENTS : e.answer
}

export function evidenceLine(brief?: StockBriefData): string {
  return brief ? brief.q6_evidence.answer : 'Loading…'
}

export function QuickAnswers({ brief }: { brief?: StockBriefData }) {
  const items = [
    { icon: '₹', bg: 'var(--sp-green-bg)', fg: 'var(--sp-green-ink)', label: 'Money at stake', text: moneyLine(brief) },
    { icon: '◷', bg: 'var(--sp-blue-bg)', fg: 'var(--sp-blue-ink)', label: 'Coming up', text: eventLine(brief) },
    { icon: '↺', bg: 'var(--sp-amber-bg)', fg: 'var(--sp-amber-ink)', label: 'Worked before?', text: evidenceLine(brief) },
  ]
  return (
    <div className="sp-quick" data-testid="quick-answers">
      {items.map((it) => (
        <div key={it.label} className="sp-card sp-card-flat sp-q">
          <div className="sp-q-icon" style={{ background: it.bg, color: it.fg }}>{it.icon}</div>
          <div>
            <div className="sp-label" style={{ fontSize: 12 }}>{it.label}</div>
            <div className="sp-q-text">{it.text}</div>
          </div>
        </div>
      ))}
    </div>
  )
}

export function FullCta({ to }: { to: string }) {
  return (
    <Link className="sp-cta" to={to} data-testid="full-analysis-cta">
      <span>
        <b>Want the full story?</b>
        <span>The step-by-step details, the score day by day, what the AI sees, and more.</span>
      </span>
      <span className="sp-cta-btn">Open full analysis ›</span>
    </Link>
  )
}

// ------------------------------------------------- Today: figures + peek --

/** "up 3 days in a row", "down 2 points over 5 days" or null, from the last few daily scores. */
export function trendText(week: TrailPoint[]): string | null {
  if (week.length < 2) return null
  let run = 0
  for (let i = week.length - 1; i > 0 && week[i]!.score > week[i - 1]!.score; i--) run++
  if (run >= 2) return `▲ up ${run} days in a row`
  const delta = Math.round((week[week.length - 1]!.score - week[0]!.score) * 100)
  if (delta >= 2) return `▲ up ${delta} points over ${week.length} days`
  if (delta <= -2) return `▼ down ${Math.abs(delta)} points over ${week.length} days`
  return 'steady over the last days'
}

/** Score (with its last-5-days bars) and price for one idea row, so a row says more than name and rank. */
export function IdeaFigures({ d }: { d: BrainDecision }) {
  const candles = useQuery({ queryKey: ['candles', d.symbol, 66], queryFn: () => api.candles(d.symbol, 66) })
  const trail = useQuery({
    queryKey: ['stock-score-trail', d.symbol],
    queryFn: () => api.stockScoreTrail(d.symbol),
    retry: false,
  })
  const rows = candles.data ?? []
  const last = rows.at(-1)?.close
  const prev = rows.at(-2)?.close
  const pct = last != null && prev ? ((last - prev) / prev) * 100 : null
  // Daily candles are stamped IST midnight (18:30 UTC the day before): read the date in India, not UTC.
  const lastTs = rows.at(-1)?.ts
  const closeDay = lastTs ? dayLabel(new Date(lastTs).toLocaleDateString('en-CA', { timeZone: 'Asia/Kolkata' })) : null
  const week = (trail.data?.score_trail ?? []).slice(-5)
  const pts = scorePoints(d.confidence)
  const first = week[0]?.score
  const latest = week.at(-1)?.score
  const delta = first != null && latest != null ? Math.round((latest - first) * 100) : 0
  return (
    <span className="spf" data-testid="idea-figures">
      <span className="spf-col">
        <span className="spf-k">SCORE</span>
        <span className="spf-v">
          {pts ?? '—'}
          {week.length >= 2 && Math.abs(delta) >= 2 && (
            <span className={`spf-d ${delta > 0 ? 'sp-pos' : 'sp-neg'}`}>{delta > 0 ? '▲' : '▼'}</span>
          )}
        </span>
        {week.length >= 2 && (
          <span className="spf-bars" aria-hidden="true">
            {week.map((t, i) => (
              <i key={t.date} style={{ background: i === 0 || t.score >= week[i - 1]!.score ? '#1f9d6b' : '#d93a49' }} />
            ))}
          </span>
        )}
      </span>
      <span className="spf-col">
        <span className="spf-k" title="The stock's last closing price, not a live price">
          {closeDay ? `CLOSE · ${closeDay}` : 'LAST CLOSE'}
        </span>
        <span className="spf-v">{last != null ? `₹${inr(last)}` : '—'}</span>
        {pct != null && (
          <span className={`spf-s ${pct >= 0 ? 'sp-pos' : 'sp-neg'}`} title="Change on that day, not today">
            {pct >= 0 ? '▲' : '▼'} {Math.abs(pct).toFixed(2)}%
          </span>
        )}
      </span>
    </span>
  )
}

const CAP_NAME: Record<string, string> = { large: 'LARGE', midcap: 'MID', smallcap: 'SMALL' }

/** The quick look at one idea: the main figures without leaving Today, with Buy and a way into the full analysis. */
export function PeekCard({ decision: d, run, reason }: { decision: BrainDecision; run: BrainRun; reason: string }) {
  const caps = useSymbolCaps()
  const data = useStockData(d, run)
  const [buying, setBuying] = useState(false)
  const word = finalWord(d)
  const pts = scorePoints(d.confidence)
  const scores = run.decisions.filter((x) => x.kind === 'idea').map((x) => x.confidence)
  const rank = d.kind === 'idea' ? scoreRank(d.confidence, scores) : null
  const moved = data.idea?.placesMoved ?? null
  const pct = data.change != null && data.prev ? (data.change / data.prev) * 100 : null
  const trend = trendText(data.trail.slice(-5))
  const cap = caps.get(d.symbol.toUpperCase())
  const to = `/trademind/stock/${encodeURIComponent(d.symbol)}/analysis`
  const tone = wordTone(word)

  return (
    <aside className="sp spf-peek" aria-label={`Quick look at ${d.symbol}`} data-testid="idea-peek">
      <div className="sp-id">
        <StockMark symbol={d.symbol} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="sp-name">
            <b style={{ fontSize: 18 }}>{d.symbol}</b>
            {cap && <span className="sp-cap">{CAP_NAME[cap]}</span>}
          </div>
          <div className="sp-small">{d.kind === 'holding' ? 'A stock the bot holds' : 'An idea from tonight’s run'}</div>
        </div>
        <span className="sp-chip" data-state={tone === 'green' ? 'ok' : tone === 'red' ? 'stop' : 'warn'}>
          {word}
        </span>
      </div>
      <div className="spf-tiles">
        <div>
          <span className="sp-label">Score</span>
          <b>{pts ?? '—'}</b>
          {trend && <small className={trend.startsWith('▼') ? 'sp-neg' : trend.startsWith('▲') ? 'sp-pos' : ''}>{trend}</small>}
        </div>
        <div>
          <span className="sp-label">Rank</span>
          <b>{rank ? `#${rank.rank}` : '—'}</b>
          {moved != null && moved !== 0 && (
            <small className={moved > 0 ? 'sp-pos' : 'sp-neg'}>
              {moved > 0 ? '▲' : '▼'} {Math.abs(moved)} places
            </small>
          )}
        </div>
        <div>
          <span className="sp-label">Price</span>
          <b>{data.last != null ? `₹${inr(data.last)}` : '—'}</b>
          {pct != null && (
            <small className={pct >= 0 ? 'sp-pos' : 'sp-neg'}>
              {pct >= 0 ? '▲' : '▼'} {Math.abs(pct).toFixed(2)}%
            </small>
          )}
        </div>
        <div>
          <span className="sp-label">Buy zone</span>
          <b style={{ fontSize: 14 }}>
            {d.entry_low != null
              ? `₹${inr(d.entry_low, 0)}${d.entry_high != null && d.entry_high !== d.entry_low ? ` – ₹${inr(d.entry_high, 0)}` : ''}`
              : '—'}
          </b>
          {d.stop != null && <small>Stop ₹{inr(d.stop, 0)}</small>}
        </div>
      </div>
      <p className="spf-reason">{reason}</p>
      <div className="spf-btns">
        <Link className="sp-btn sp-btn-ai" to={to}>
          Full analysis ›
        </Link>
        {brainAllowsBuy(word) && (
          <button className="sp-btn sp-btn-buy" type="button" onClick={() => setBuying((v) => !v)}>
            Buy
          </button>
        )}
      </div>
      {brainAllowsBuy(word) && <BuyBox symbol={d.symbol} open={buying} onClose={() => setBuying(false)} />}
    </aside>
  )
}
