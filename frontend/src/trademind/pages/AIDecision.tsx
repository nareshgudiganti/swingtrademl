import { useState } from 'react'
import { useParams } from 'react-router-dom'

import type { BrainDecision, BrainTraceEvent } from '../../api/types'
import { useBrainStatus, useWhy } from '../live'
import { BrainOff, Card, CheckItem, Icon, NotConnected, Tabs, inr } from '../ui'

const TABS = ['Summary', 'Evidence', 'Similar Cases', 'Model Output', 'Risk Analysis'] as const
type TabId = (typeof TABS)[number]

const STEP_ICONS = [Icon.Pulse, Icon.Target, Icon.Layers, Icon.Book, Icon.Chart, Icon.Shield, Icon.Bolt]

// Same step names and trace wording as the brain console — see Brain.tsx's
// STEP_LABEL / traceLine. Duplicated rather than imported: neither is
// exported, and this screen must never drift from that wording by hand.
const STEP_LABEL: Record<string, string> = {
  perceive: '1 · Look at the data',
  state: '2 · Read the market',
  recognise: '3 · Recognise the situation',
  remember: '4 · Remember similar times',
  reason: '5 · Form an opinion',
  risk: '6 · Safety check',
  decide: '7 · Decide',
  learn: '8 · Learn from results',
}

function traceLine(e: BrainTraceEvent): string {
  if (e.module_id === 'fallback') return 'Simple built-in answer (no module installed for this step)'
  switch (e.status) {
    case 'used':
      return `${e.module_id} answered`
    case 'shadow':
      return `${e.module_id} ran on trial — recorded, not used`
    case 'skipped':
      return `${e.module_id} is switched off`
    case 'rejected':
      return `${e.module_id}'s answer was refused: ${e.reason}`
    default:
      return `${e.module_id} did not answer (${e.reason}); the simple built-in answer was used`
  }
}

// The owner's overrule, if any, otherwise the brain's own word. Duplicated
// in each TradeMind screen rather than shared, same as Brain.tsx's own copy.
function finalWord(d: BrainDecision): string {
  return d.overruled_word ?? d.word
}

// Positive: TRADE / HOLD. Caution: WATCH / WAIT / MONITOR. Negative: AVOID /
// REDUCE / EXIT. Same mapping as StockDetail.tsx, duplicated rather than
// shared (this screen owns no shared module to put it in).
const WORD_TONE: Record<string, 'pos' | 'warn' | 'neg'> = {
  TRADE: 'pos',
  HOLD: 'pos',
  WATCH: 'warn',
  WAIT: 'warn',
  MONITOR: 'warn',
  AVOID: 'neg',
  REDUCE: 'neg',
  EXIT: 'neg',
}

function wordTone(d: BrainDecision): 'pos' | 'warn' | 'neg' {
  return WORD_TONE[finalWord(d)] ?? 'pos'
}

function wordClass(d: BrainDecision): string {
  return `tm-${wordTone(d)}`
}

function money(n: number): string {
  return `${n < 0 ? '−' : '+'}₹${inr(Math.abs(n), 0)}`
}

export default function AIDecision() {
  const { symbol: rawSymbol } = useParams()
  const symbol = (rawSymbol ?? '').toUpperCase()

  const status = useBrainStatus()
  const why = useWhy(status === 'live' && symbol ? symbol : undefined)

  const [tab, setTab] = useState<TabId>('Summary')
  const [step, setStep] = useState(0)

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

  if (why.isLoading) {
    return (
      <div className="tm-page">
        <p className="tm-dim">Looking up {symbol || 'this stock'}…</p>
      </div>
    )
  }

  if (why.isError) {
    return (
      <div className="tm-page">
        <Card title="Could not reach the brain">
          <p className="tm-dim">Something went wrong talking to the brain. Try again shortly.</p>
        </Card>
      </div>
    )
  }

  const decision = why.data?.decision
  if (!decision) {
    return (
      <div className="tm-page">
        <Card title={symbol || 'Unknown stock'}>
          <p className="tm-dim">No decision for this stock today.</p>
        </Card>
      </div>
    )
  }

  const trace = why.data?.trace ?? []
  const current = trace[step]
  const riskTrace = trace.filter((e) => e.step === 'risk')

  const ifStopInr =
    decision.stop != null && decision.entry_low != null ? (decision.stop - decision.entry_low) * decision.qty : undefined
  const ifTargetInr =
    decision.target != null && decision.entry_low != null ? (decision.target - decision.entry_low) * decision.qty : undefined

  return (
    <div className="tm-page">
      <div className="tm-grid tm-ai-grid">
        <Card glow>
          <div className="tm-chain">
            {trace.length > 0 ? (
              trace.map((e, i) => {
                const StepIcon = STEP_ICONS[i] ?? Icon.Check
                const last = i === trace.length - 1
                return (
                  <div
                    key={i}
                    className={`tm-chain-step ${last ? 'tm-final' : ''} ${i === step ? 'tm-active' : ''}`}
                    onClick={() => setStep(i)}
                  >
                    <span className="tm-chain-dot">{last ? <Icon.Check /> : <StepIcon />}</span>
                    <div>
                      <div className="tm-chain-title">{STEP_LABEL[e.step] ?? e.step}</div>
                      <div className="tm-chain-sub">{traceLine(e)}</div>
                    </div>
                  </div>
                )
              })
            ) : (
              <p className="tm-dim">No reasoning trace recorded for this decision.</p>
            )}
          </div>
          {current && (
            <div className="tm-callout" style={{ marginTop: '0.4rem' }}>
              <div className="tm-strong" style={{ marginBottom: 4 }}>
                {STEP_LABEL[current.step] ?? current.step}
              </div>
              {current.reason || traceLine(current)}
            </div>
          )}
        </Card>

        <Card glow title="AI Reasoning Details">
          <Tabs tabs={TABS} active={tab} onChange={setTab} />

          {tab === 'Summary' && (
            <>
              <p className="tm-strong" style={{ marginTop: 0 }}>
                TradeMind {decision.kind === 'idea' ? 'recommends' : 'currently has'}{' '}
                <span className={wordClass(decision)}>{finalWord(decision)}</span> for {symbol}
                {decision.confidence != null && (
                  <>
                    {' '}
                    with{' '}
                    <span className="tm-pos" title="A ranking, not a chance — not a probability">
                      {Math.round(decision.confidence * 100)}% model score
                    </span>
                  </>
                )}
                .
              </p>

              <div className="tm-card" style={{ marginTop: '1rem' }}>
                <div className="tm-card-head">
                  <h4 className="tm-card-title" style={{ color: '#8db4ff' }}>
                    Key Factors
                  </h4>
                </div>
                <div className="tm-rows">
                  {decision.reasons.length > 0 ? (
                    decision.reasons.map((r, i) => (
                      <div key={i} className="tm-row">
                        <span>{r}</span>
                      </div>
                    ))
                  ) : (
                    <p className="tm-dim">No reasons recorded for this decision.</p>
                  )}
                </div>
              </div>
            </>
          )}

          {tab === 'Evidence' &&
            (decision.evidence_text ? (
              <p className="tm-dim" style={{ whiteSpace: 'pre-wrap' }}>
                {decision.evidence_text}
              </p>
            ) : (
              <p className="tm-dim">No evidence text recorded for this decision.</p>
            ))}

          {tab === 'Similar Cases' &&
            (decision.evidence_text?.includes('Similar cases') ? (
              <p className="tm-dim">{decision.evidence_text}</p>
            ) : (
              <NotConnected what="Similar cases" reason="The brain hasn't recorded similar-case evidence for this decision." />
            ))}

          {tab === 'Model Output' && (
            <NotConnected
              what="Model output"
              reason="Individual model scores aren't connected yet — the brain reports one combined model score, not per-model votes."
            />
          )}

          {tab === 'Risk Analysis' && (
            <div className="tm-grid tm-cols-2">
              <div>
                {riskTrace.length > 0 ? (
                  riskTrace.map((e, i) => (
                    <CheckItem key={i} tone={e.status === 'rejected' ? 'neg' : e.status === 'skipped' ? 'neutral' : 'pos'}>
                      {traceLine(e)}
                    </CheckItem>
                  ))
                ) : (
                  <p className="tm-dim">No risk-check step recorded for this decision.</p>
                )}
              </div>
              {ifStopInr != null || ifTargetInr != null || decision.qty > 0 ? (
                <dl className="tm-kv">
                  {ifStopInr != null && (
                    <>
                      <dt>If the stop is hit</dt>
                      <dd className="tm-neg">{money(ifStopInr)}</dd>
                    </>
                  )}
                  {ifTargetInr != null && (
                    <>
                      <dt>If the target is hit</dt>
                      <dd className="tm-pos">{money(ifTargetInr)}</dd>
                    </>
                  )}
                  {decision.qty > 0 && (
                    <>
                      <dt>Shares suggested</dt>
                      <dd>{decision.qty}</dd>
                    </>
                  )}
                </dl>
              ) : (
                <NotConnected what="Money at risk" reason="No entry, target or stop recorded for this decision." />
              )}
            </div>
          )}
        </Card>
      </div>
    </div>
  )
}
