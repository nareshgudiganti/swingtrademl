import { useState } from 'react'
import { useParams } from 'react-router-dom'

import { findIdea, keyFactors, modelOutputs, reasoningChain, riskChecks, similarCases, stockAnalysis, technicals } from '../data'
import { Card, CheckItem, Icon, Meter, Tabs, Tag, signed, toneClass } from '../ui'

const TABS = ['Summary', 'Evidence', 'Similar Cases', 'Model Output', 'Risk Analysis'] as const
type TabId = (typeof TABS)[number]

const STEP_ICONS = [Icon.Pulse, Icon.Target, Icon.Layers, Icon.Book, Icon.Chart, Icon.Shield, Icon.Bolt]

export default function AIDecision() {
  const { symbol } = useParams()
  const idea = findIdea(symbol)
  const [tab, setTab] = useState<TabId>('Summary')
  const [step, setStep] = useState(reasoningChain.length - 1)

  return (
    <div className="tm-page">
      <div className="tm-grid tm-ai-grid">
        <Card glow>
          <div className="tm-chain">
            {reasoningChain.map((s, i) => {
              const StepIcon = STEP_ICONS[i] ?? Icon.Check
              const last = i === reasoningChain.length - 1
              return (
                <div
                  key={s.title}
                  className={`tm-chain-step ${last ? 'tm-final' : ''} ${i === step ? 'tm-active' : ''}`}
                  onClick={() => setStep(i)}
                >
                  <span className="tm-chain-dot">{last ? <Icon.Check /> : <StepIcon />}</span>
                  <div>
                    <div className="tm-chain-title">{s.title}</div>
                    <div className={`tm-chain-sub ${last ? 'tm-pos' : ''}`} style={last ? { fontWeight: 600, fontSize: '0.86rem', color: 'var(--tm-green)' } : undefined}>
                      {last ? `${idea.action} — High Confidence` : s.sub}
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
          <div className="tm-callout" style={{ marginTop: '0.4rem' }}>
            <div className="tm-strong" style={{ marginBottom: 4 }}>
              {reasoningChain[step]?.title}
            </div>
            {reasoningChain[step]?.detail}
          </div>
        </Card>

        <Card glow title="AI Reasoning Details">
          <Tabs tabs={TABS} active={tab} onChange={setTab} />

          {tab === 'Summary' && (
            <>
              <p className="tm-strong" style={{ marginTop: 0 }}>
                TradeMind recommends <span className="tm-pos">{idea.action}</span> for {idea.name.toUpperCase()} with{' '}
                <span className="tm-pos">{idea.confidence}% confidence</span>.
              </p>
              <ul className="tm-bullets">
                <li>The stock has broken out from a 3-month range with high volume</li>
                <li>Its sector is showing relative strength in the current market</li>
                <li>Several chart signals agree (momentum, trend and averages)</li>
                <li>The business outlook is positive, with growing profits</li>
                <li>Similar past situations ended in profit 78% of the time</li>
                <li>The reward is good compared with the risk</li>
                <li>Suggested size: 4-6% of the portfolio</li>
              </ul>

              <div className="tm-card" style={{ marginTop: '1rem' }}>
                <div className="tm-card-head">
                  <h4 className="tm-card-title" style={{ color: '#8db4ff' }}>
                    Key Factors
                  </h4>
                </div>
                <div className="tm-rows">
                  {keyFactors.map((f) => (
                    <div key={f.name} className="tm-row">
                      <span>{f.name}</span>
                      <span className={f.impact === 'High' ? 'tm-pos' : 'tm-warn'} style={{ fontWeight: 600 }}>
                        {f.impact} impact
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            </>
          )}

          {tab === 'Evidence' && (
            <div className="tm-grid tm-cols-2">
              <div>
                <div className="tm-card-title" style={{ marginBottom: 6 }}>
                  For the trade
                </div>
                {stockAnalysis.map((s) => (
                  <CheckItem key={s}>{s}</CheckItem>
                ))}
                {technicals
                  .filter((t) => t.tone === 'pos')
                  .slice(0, 3)
                  .map((t) => (
                    <CheckItem key={t.name}>{t.plain}</CheckItem>
                  ))}
              </div>
              <div>
                <div className="tm-card-title" style={{ marginBottom: 6 }}>
                  Against the trade
                </div>
                <CheckItem tone="neg">Analysts flag EV margin pressure</CheckItem>
                <CheckItem tone="warn">Quarterly results in 3 weeks can cause a big move</CheckItem>
                <CheckItem tone="warn">Price is already 6% above the breakout point</CheckItem>
              </div>
            </div>
          )}

          {tab === 'Similar Cases' && (
            <div className="tm-table-wrap">
              <table className="tm-table">
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Stock</th>
                    <th>Situation</th>
                    <th className="tm-right">Outcome</th>
                  </tr>
                </thead>
                <tbody>
                  {similarCases.slice(0, 6).map((c) => (
                    <tr key={c.date + c.symbol}>
                      <td>{c.date}</td>
                      <td className="tm-strong">{c.symbol}</td>
                      <td>{c.situation}</td>
                      <td className={`tm-right tm-num ${toneClass(c.outcomePct)}`}>{signed(c.outcomePct)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {tab === 'Model Output' && (
            <div className="tm-stack">
              {modelOutputs.map((m) => (
                <div key={m.model}>
                  <div className="tm-between" style={{ marginBottom: 4 }}>
                    <span>{m.model}</span>
                    <span className="tm-flex" style={{ gap: '0.5rem' }}>
                      <span className="tm-num tm-strong">{Math.round(m.score * 100)}%</span>
                      <Tag tone={m.vote === 'Up' ? 'green' : 'blue'}>{m.vote}</Tag>
                    </span>
                  </div>
                  <Meter pct={m.score * 100} color={m.vote === 'Up' ? '#2ee68a' : '#4f8cff'} />
                </div>
              ))}
              <p className="tm-note">4 of 5 models point up. Sample figures — real models will report calibrated chances.</p>
            </div>
          )}

          {tab === 'Risk Analysis' && (
            <div className="tm-grid tm-cols-2">
              <div>
                {riskChecks.map((r) => (
                  <CheckItem key={r.name} tone={r.ok ? 'pos' : 'warn'}>
                    {r.name}
                    {r.note && <div className="tm-faint">{r.note}</div>}
                  </CheckItem>
                ))}
              </div>
              <dl className="tm-kv">
                <dt>If the stop is hit</dt>
                <dd className="tm-neg">−₹4,350</dd>
                <dt>If the target is hit</dt>
                <dd className="tm-pos">+₹9,480</dd>
                <dt>Suggested size</dt>
                <dd>5% of portfolio</dd>
                <dt>Auto sector after this</dt>
                <dd>23% (limit 25%)</dd>
              </dl>
            </div>
          )}
        </Card>
      </div>
    </div>
  )
}
