// The new look's stock page: answer first, then the brain's eight steps for this stock ("AI analysis"), what would
// change it, the plan if it becomes a TRADE, and last the classic page's chart, company and news, unchanged.
// Display only: reads the brain's latest run and the stored candles; changes nothing.

import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'

import { api } from '../../api/client'
import type { BrainDecision } from '../../api/types'
import { formatDateTime } from '../../lib/format'
import { brainSteps, stopOf } from '../brainSteps'
import { CapFlag, useSymbolCaps } from '../cap'
import { finalWord, useLatestRun } from '../live'
import { rankText, scoreRank, SCORE_HINT, withoutScorePercent } from '../scoreText'
import { BrainGate, inr, StockLogo } from '../ui'
import { wordTagColor } from '../vocab'
import { WhatWouldChange } from '../WhatWouldChange'
import StockDetail from './StockDetail'

export default function StockNew() {
  return (
    <BrainGate>
      <StockNewBody />
    </BrainGate>
  )
}

function StockNewBody() {
  const symbol = (useParams().symbol ?? '').toUpperCase()
  const run = useLatestRun().data!
  const decision = run.decisions.find((d) => d.symbol.toUpperCase() === symbol)
  // Nothing from tonight's run for this stock: the classic page asks the brain on demand and says so.
  if (!decision) return <StockDetail />

  return (
    <div className="tm-page tmn-stock" data-page="stock-new">
      <Link to="/trademind/opportunities" className="tmn-small">
        ← Back to Discover
      </Link>
      <Header decision={decision} />
      <Answer decision={decision} runAt={run.started_at} />
      <section className="tmn-card" aria-label={`How the brain thought about ${symbol}`} data-testid="brain-steps">
        <div className="tmn-card-head">
          <span className="tmn-card-title">How the brain thought about {symbol}</span>
          <span className="tmn-ai">AI analysis · 8 steps</span>
        </div>
        <ol className="tmn-steps">
          {brainSteps(decision, run).map((s) => (
            <li key={s.n} className="tmn-step" data-state={s.state}>
              <span className="tmn-step-n">{s.n}</span>
              <b>{s.title}</b>
              <span className="tm-dim">{s.line}</span>
              <span className="tmn-step-tag" data-state={s.state}>
                {s.tag}
              </span>
            </li>
          ))}
        </ol>
        <p className="tmn-small tm-dim">
          Past cases are history, not a promise. {SCORE_HINT}
        </p>
      </section>
      <WhatWouldChange decision={decision} />
      <Plan decision={decision} />
      <h2 className="tmn-h2">Chart, company and news</h2>
      <div className="tmn-embed">
        <StockDetail />
      </div>
    </div>
  )
}

function Header({ decision: d }: { decision: BrainDecision }) {
  const caps = useSymbolCaps()
  // Same cache key as the classic page's default 3-month chart, so the candles load once.
  const candles = useQuery({ queryKey: ['candles', d.symbol, 66], queryFn: () => api.candles(d.symbol, 66) })
  const rows = candles.data ?? []
  const last = rows.at(-1)?.close
  const prev = rows.at(-2)?.close
  const change = last != null && prev ? last - prev : null

  return (
    <div className="tmn-stock-head">
      <StockLogo symbol={d.symbol} />
      <div className="tmn-stock-name">
        <span className="tmn-stock-sym">
          {d.symbol} <CapFlag tier={caps.get(d.symbol.toUpperCase())} />
        </span>
        <span className="tm-dim tmn-small">{d.kind === 'holding' ? 'A stock the bot holds (paper)' : 'An idea from tonight’s run'}</span>
      </div>
      {last != null && (
        <div className="tmn-stock-price">
          <b>₹{inr(last)}</b>
          {change != null && prev ? (
            <span className={change >= 0 ? 'tm-pos' : 'tm-neg'}>
              {change >= 0 ? '+' : '−'}₹{inr(Math.abs(change))} ({change >= 0 ? '+' : '−'}
              {Math.abs((change / prev) * 100).toFixed(2)}%) last close
            </span>
          ) : null}
        </div>
      )}
    </div>
  )
}

function Answer({ decision: d, runAt }: { decision: BrainDecision; runAt: string }) {
  const run = useLatestRun().data!
  const word = finalWord(d)
  const scores = run.decisions.filter((x) => x.kind === 'idea').map((x) => x.confidence)
  const rank = d.kind === 'idea' ? scoreRank(d.confidence, scores) : null
  const stop = stopOf(d)
  const why = stop ? stop.why.text : d.reasons[0] ? withoutScorePercent(d.reasons[0]) : 'The brain stored no reason.'

  return (
    <section className="tmn-card" aria-label="The brain's answer" data-testid="stock-answer">
      <div className="tmn-answer-row">
        <span className={`tmn-bigword tmn-bigword-${wordTagColor(word)}`}>{word}</span>
        {rank && (
          <span className="tm-dim" title={SCORE_HINT}>
            {rankText(rank)}
          </span>
        )}
        <span className="tmn-grow" />
        <span className="tm-dim tmn-small">Brain’s run on {formatDateTime(runAt)}</span>
      </div>
      <p className="tmn-why">
        <b>{word === 'TRADE' ? 'Why TRADE' : `Why ${word}, not TRADE`}:</b> {why}
      </p>
    </section>
  )
}

/** The plan the rules give an idea (+5% half out, +8% target, −4% stop, 15 trading days). Only from stored prices. */
function Plan({ decision: d }: { decision: BrainDecision }) {
  if (d.kind !== 'idea' || d.entry_low == null || d.target == null || d.stop == null) return null
  const mid = d.entry_high != null ? (d.entry_low + d.entry_high) / 2 : d.entry_low
  const word = finalWord(d)
  return (
    <section className="tmn-card" aria-label="The plan">
      <div className="tmn-card-head">
        <span className="tmn-card-title">{word === 'TRADE' ? 'The plan' : 'The plan if it becomes a TRADE'}</span>
        <span className="tm-dim tmn-small">Same rules for every trade</span>
      </div>
      <div className="tmn-plan">
        <div>
          <span className="tm-dim tmn-small">Buy around</span>
          <b>
            ₹{inr(d.entry_low)}
            {d.entry_high != null && d.entry_high !== d.entry_low ? ` – ₹${inr(d.entry_high)}` : ''}
          </b>
        </div>
        <div>
          <span className="tm-dim tmn-small">Sell half at</span>
          <b className="tm-pos">+5% · ₹{inr(mid * 1.05)}</b>
        </div>
        <div>
          <span className="tm-dim tmn-small">Target</span>
          <b className="tm-pos">₹{inr(d.target)}</b>
        </div>
        <div>
          <span className="tm-dim tmn-small">Stop loss</span>
          <b className="tm-neg">₹{inr(d.stop)}</b>
        </div>
      </div>
      <p className="tmn-small tm-dim">Sold within {d.horizon_days} trading days at the latest.</p>
    </section>
  )
}
