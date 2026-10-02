import { useState } from 'react'

import { keyLearnings, memoryStats, outcomeMix, similarCases } from '../data'
import { Card, Donut, Icon, Ring, inr, signed, toneClass } from '../ui'

const LEARN_ICONS = [Icon.Pulse, Icon.Shield, Icon.Layers, Icon.Clock]

export default function Learn() {
  const [showAll, setShowAll] = useState(false)
  const rows = showAll ? similarCases : similarCases.slice(0, 4)

  return (
    <div className="tm-page tm-grid">
      <div className="tm-grid tm-cols-3">
        <Card glow title="Similar Situations Found">
          <div style={{ display: 'grid', placeItems: 'center', padding: '0.3rem 0' }}>
            <Ring
              value={memoryStats.successRate}
              size={150}
              stroke={11}
              color="blue"
              center={
                <>
                  <span className="tm-ring-value" style={{ fontSize: 40 }}>
                    {memoryStats.cases}
                  </span>
                  <span className="tm-ring-label">similar cases</span>
                </>
              }
            />
          </div>
          <div style={{ textAlign: 'center', marginTop: '0.5rem' }}>
            <div className="tm-strong" style={{ fontSize: '1rem' }}>
              Similar cases
            </div>
            <div className="tm-pos" style={{ fontWeight: 600 }}>
              {memoryStats.successRate}% Success Rate
            </div>
          </div>
        </Card>

        <Card title="Outcome Distribution">
          <div className="tm-flex" style={{ gap: '1.4rem' }}>
            <Donut size={150} stroke={24} segments={outcomeMix} />
            <div className="tm-legend" style={{ flex: 1 }}>
              {outcomeMix.map((o) => (
                <div key={o.name} className="tm-legend-row" style={{ color: o.color }}>
                  <span>
                    <span className="tm-swatch" />
                    <span style={{ color: 'var(--tm-text)' }}>{o.name}</span>
                  </span>
                  <span className="tm-strong">{o.pct}%</span>
                </div>
              ))}
            </div>
          </div>
          <div className="tm-between tm-note">
            <span>
              Avg gain <span className="tm-pos">{signed(memoryStats.avgGainPct)}</span>
            </span>
            <span>
              Avg loss <span className="tm-neg">{signed(memoryStats.avgLossPct)}</span>
            </span>
          </div>
        </Card>

        <Card title="Key Learnings">
          <div className="tm-stack" style={{ gap: '0.75rem' }}>
            {keyLearnings.map((k, i) => {
              const I = LEARN_ICONS[i % LEARN_ICONS.length] ?? Icon.Check
              return (
                <div key={k} className="tm-flex">
                  <span className="tm-icon-badge">
                    <I />
                  </span>
                  <span>{k}</span>
                </div>
              )
            })}
          </div>
          <p className="tm-note">From {inr(memoryStats.totalMemories, 0)} past trades and situations the brain remembers.</p>
        </Card>
      </div>

      <Card
        glow
        title="Historical Similar Cases"
        action={
          <button className="tm-btn" style={{ padding: '0.35rem 0.8rem' }} onClick={() => setShowAll((v) => !v)}>
            {showAll ? 'Show Fewer' : 'View All Cases'}
          </button>
        }
      >
        <div className="tm-table-wrap">
          <table className="tm-table">
            <thead>
              <tr>
                <th>Date</th>
                <th>Stock</th>
                <th>Situation</th>
                <th>Market Regime</th>
                <th className="tm-right">Outcome</th>
                <th className="tm-right" title="Result measured in units of the risk taken">
                  R Multiple
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.date + c.symbol}>
                  <td>{c.date}</td>
                  <td className="tm-strong">{c.symbol}</td>
                  <td>{c.situation}</td>
                  <td className={c.regime === 'Bullish' ? 'tm-pos' : 'tm-warn'}>{c.regime}</td>
                  <td className={`tm-right tm-num ${toneClass(c.outcomePct)}`}>{signed(c.outcomePct)}</td>
                  <td className={`tm-right tm-num ${toneClass(c.r)}`}>{signed(c.r, 1, 'R')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  )
}
