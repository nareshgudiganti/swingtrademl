import { useState } from 'react'
import { useParams } from 'react-router-dom'

import { finalWord, ideasFrom, useBrainStatus, useLatestRun, useRunTrace, useWhy } from '../live'
import { MODULE_PLAIN, STEP_LABEL, moduleName, traceLine, wordClassName, wordTone } from '../vocab'
import { BrainGate, Card, CheckItem, Icon, NotConnected, Tabs, inr } from '../ui'

const TABS = ['Summary', 'Evidence', 'Similar Cases', 'Model Output', 'Risk Analysis'] as const
type TabId = (typeof TABS)[number]

const STEP_ICONS = [Icon.Pulse, Icon.Target, Icon.Layers, Icon.Book, Icon.Chart, Icon.Shield, Icon.Bolt]

function money(n: number): string {
  return `${n < 0 ? '−' : '+'}₹${inr(Math.abs(n), 0)}`
}

export default function AIDecision() {
  return (
    <BrainGate>
      <AIDecisionBody />
    </BrainGate>
  )
}

function AIDecisionBody() {
  const { symbol: rawSymbol } = useParams()
  const status = useBrainStatus()
  const latest = useLatestRun()
  const run = latest.data
  // No symbol in the URL (/trademind/ai): default to today's top idea,
  // same as Positions defaults to holdings[0] (F3).
  const defaultIdea = run && !rawSymbol ? ideasFrom(run)[0] : undefined
  const symbol = (rawSymbol ?? defaultIdea?.symbol ?? '').toUpperCase()
  const fromRun = run?.decisions.find((d) => d.symbol.toUpperCase() === symbol)
  // The symbol is already in the latest nightly run: read that run's stored
  // trace (fast) instead of asking the brain to reason about it again
  // (api.brainWhy triggers a fresh ~15s run). Only fall back to brainWhy
  // when the symbol isn't in the latest run.
  const runTrace = useRunTrace(fromRun ? run?.run_id : undefined)
  const why = useWhy(status === 'live' && !fromRun && symbol ? symbol : undefined)

  const [tab, setTab] = useState<TabId>('Summary')
  const [step, setStep] = useState(0)

  const stillLookingUp = fromRun ? runTrace.isLoading : why.isLoading
  if (stillLookingUp) {
    return (
      <div className="tm-page">
        <p className="tm-dim">Looking up {symbol || 'this stock'}…</p>
      </div>
    )
  }

  const lookupFailed = fromRun ? runTrace.isError : why.isError
  if (lookupFailed) {
    return (
      <div className="tm-page">
        <Card title="Could not reach the brain">
          <p className="tm-dim">Something went wrong talking to the brain. Try again shortly.</p>
        </Card>
      </div>
    )
  }

  const decision = fromRun ?? why.data?.decision
  if (!decision) {
    const noSymbolGiven = !rawSymbol
    return (
      <div className="tm-page">
        <Card title={noSymbolGiven ? 'No ideas yet' : symbol || 'Unknown stock'}>
          <p className="tm-dim">
            {noSymbolGiven ? 'The brain has no ideas to show right now.' : 'No decision for this stock today.'}
          </p>
        </Card>
      </div>
    )
  }

  const trace = (fromRun ? runTrace.data?.trace : why.data?.trace) ?? []
  const current = trace[step]
  const riskTrace = trace.filter((e) => e.step === 'risk')

  const ifStopInr =
    decision.stop != null && decision.entry_low != null ? (decision.stop - decision.entry_low) * decision.qty : undefined
  const ifTargetInr =
    decision.target != null && decision.entry_low != null ? (decision.target - decision.entry_low) * decision.qty : undefined

  return (
    <div className="tm-page">
      <div className="tm-grid tm-ai-grid">
        <Card
          glow
          title="How the brain worked through this run"
          sub="The steps are the same for every stock in a run."
        >
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
              <p className="tm-dim">No reasoning trace recorded for this run.</p>
            )}
          </div>
          {current && (
            <div className="tm-callout" style={{ marginTop: '0.4rem' }}>
              <div className="tm-dim" style={{ fontSize: '0.72rem' }}>
                Selected: {STEP_LABEL[current.step] ?? current.step}
              </div>
              <div className="tm-strong" style={{ marginBottom: 4 }} title={current.module_id}>
                {moduleName(current.module_id)}
              </div>
              <div>{MODULE_PLAIN[current.module_id]?.does}</div>
              <div className="tm-dim" style={{ marginTop: 4 }}>
                {current.reason && current.status !== 'shadow' && current.module_id !== 'fallback'
                  ? current.reason
                  : traceLine(current)}
              </div>
            </div>
          )}
        </Card>

        <Card glow title="AI Reasoning Details">
          <Tabs tabs={TABS} active={tab} onChange={setTab} />

          {tab === 'Summary' && (
            <>
              <p className="tm-strong" style={{ marginTop: 0 }}>
                TradeMind {decision.kind === 'idea' ? 'recommends' : 'currently has'}{' '}
                <span className={wordClassName(finalWord(decision))}>{finalWord(decision)}</span> for {symbol}
                {decision.confidence != null && (
                  <>
                    {' '}
                    with{' '}
                    <span title="A ranking, not a chance — not a probability">
                      {Math.round(decision.confidence * 100)} model score
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
                {/* The verdict for THIS stock comes from the decision itself
                 * (did the risk gate bring its word down, and to what) —
                 * never from whether a shared run-level module "answered". */}
                <CheckItem tone={decision.downgraded_from != null ? 'warn' : wordTone(finalWord(decision))}>
                  {decision.downgraded_from != null
                    ? `Brought down from ${decision.downgraded_from} to ${finalWord(decision)}${
                        decision.downgrade_reason ? ` — ${decision.downgrade_reason}` : ''
                      }`
                    : `Passed the brain's risk check — stayed at ${finalWord(decision)}.`}
                </CheckItem>
                {riskTrace.length > 0 ? (
                  riskTrace.map((e, i) => (
                    <CheckItem key={i} tone="neutral">
                      {traceLine(e)}
                    </CheckItem>
                  ))
                ) : (
                  <p className="tm-dim">No risk-check step recorded for this run.</p>
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
