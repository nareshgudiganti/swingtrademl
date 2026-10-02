import { useMemo, useState } from 'react'
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

import { backtests, featureImportance, mlModels, modelPerf, recentPredictions, series, strategyEquity } from '../data'
import { Card, GlowArea, HBar, Seg, Tabs, Tag, signed, toneClass } from '../ui'

const TABS = ['Model Overview', 'Backtesting', 'Live Predictions', 'Feature Importance', 'Model Comparison'] as const
type TabId = (typeof TABS)[number]

const accuracyTrend = series(93, 12, 76, 0.006, 0.03)

const RANGES = ['1M', '6M', '1Y', '3Y', 'All'] as const
type Range = (typeof RANGES)[number]
const RANGE_N: Record<Range, number> = { '1M': 8, '6M': 20, '1Y': 32, '3Y': 60, All: 80 }

function EquityChart({ range, height }: { range: Range; height: number }) {
  const data = useMemo(() => strategyEquity.slice(-RANGE_N[range]), [range])
  return (
    <div className="tm-chart" style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 6, right: 6, left: -14, bottom: 0 }}>
          <CartesianGrid vertical={false} />
          <XAxis dataKey="t" tickLine={false} axisLine={false} interval={0} />
          <YAxis domain={['dataMin', 'dataMax']} tickLine={false} axisLine={false} width={44} tickFormatter={(v: number) => v.toFixed(0)} />
          <Tooltip
            content={({ active, payload }) =>
              active && payload?.length ? (
                <div className="tm-tooltip">
                  <div style={{ color: '#a78bfa' }}>Strategy: {Number(payload[0]?.value).toFixed(1)}</div>
                  <div style={{ color: '#8f97c0' }}>Nifty: {Number(payload[1]?.value ?? 0).toFixed(1)}</div>
                </div>
              ) : null
            }
          />
          <Line dataKey="v" stroke="#a78bfa" strokeWidth={2.2} dot={false} isAnimationActive={false} style={{ filter: 'drop-shadow(0 0 5px #8b5cf6)' }} />
          <Line dataKey="bench" stroke="#5d6590" strokeDasharray="4 4" strokeWidth={1.4} dot={false} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

function PredictionsTable() {
  return (
    <div className="tm-table-wrap">
      <table className="tm-table">
        <thead>
          <tr>
            <th>Stock</th>
            <th>Prediction</th>
            <th className="tm-right">Confidence</th>
            <th className="tm-right">Actual</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {recentPredictions.map((p) => (
            <tr key={p.symbol}>
              <td className="tm-strong">{p.symbol}</td>
              <td className={p.prediction === 'UP' ? 'tm-pos' : 'tm-neg'} style={{ fontWeight: 600 }}>
                {p.prediction}
              </td>
              <td className="tm-right tm-num">{p.confidence}%</td>
              <td className={`tm-right tm-num ${p.actualPct === null ? 'tm-dim' : toneClass(p.actualPct)}`}>
                {p.actualPct === null ? '—' : signed(p.actualPct)}
              </td>
              <td>
                <Tag tone={p.status === 'Correct' ? 'green' : p.status === 'Incorrect' ? 'red' : 'blue'}>{p.status}</Tag>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Features() {
  const max = Math.max(...featureImportance.map((f) => f.pct))
  return (
    <>
      {featureImportance.map((f) => (
        <HBar key={f.name} label={<span style={{ fontSize: '0.74rem' }}>{f.name}</span>} value={f.pct} max={max} tone="violet" right={`${f.pct}%`} labelWidth={130} />
      ))}
    </>
  )
}

export default function System() {
  const [tab, setTab] = useState<TabId>('Model Overview')
  const [range, setRange] = useState<Range>('1Y')

  return (
    <div className="tm-page">
      <Tabs tabs={TABS} active={tab} onChange={setTab} />

      {tab === 'Model Overview' && (
        <div className="tm-grid">
          <div className="tm-grid tm-cols-4">
            <Card glow title="Model Performance">
              <div className="tm-grid tm-cols-2" style={{ gap: '0.9rem' }}>
                <div>
                  <div className="tm-big tm-pos">{modelPerf.accuracy}%</div>
                  <div className="tm-stat-label">Accuracy</div>
                </div>
                <div>
                  <div className="tm-big" style={{ color: '#8db4ff' }}>
                    {modelPerf.profitFactor}
                  </div>
                  <div className="tm-stat-label" title="Money won ÷ money lost">
                    Profit Factor
                  </div>
                </div>
                <div>
                  <div className="tm-big tm-pos" style={{ fontSize: '1.5rem' }}>
                    +{modelPerf.annualReturn}%
                  </div>
                  <div className="tm-stat-label">Annual Return</div>
                </div>
                <div>
                  <div className="tm-big tm-neg" style={{ fontSize: '1.5rem' }}>
                    {modelPerf.maxDrawdown}%
                  </div>
                  <div className="tm-stat-label">Peak Drawdown</div>
                </div>
              </div>
              <div className="tm-stat-label" style={{ marginTop: '0.9rem' }}>
                Accuracy, last 12 weeks
              </div>
              <GlowArea data={accuracyTrend} height={56} formatter={(v) => `${v.toFixed(0)}%`} />
            </Card>
            <Card
              className="tm-span-2"
              title="Strategy Equity Curve"
              action={<Seg<Range> small active={range} onChange={setRange} options={RANGES.map((r) => ({ id: r, label: r }))} />}
            >
              <EquityChart range={range} height={170} />
            </Card>
            <Card title="ML Models">
              <div className="tm-rows">
                {mlModels.map((m) => (
                  <div key={m.name} className="tm-row">
                    <span>{m.name}</span>
                    <span className="tm-flex" style={{ gap: '0.5rem' }}>
                      <span className="tm-num">{m.accuracy}%</span>
                      <Tag tone={m.status === 'Active' ? 'green' : 'blue'}>{m.status}</Tag>
                    </span>
                  </div>
                ))}
              </div>
            </Card>
          </div>
          <div className="tm-grid tm-cols-3">
            <Card className="tm-span-2" title="Recent Predictions">
              <PredictionsTable />
            </Card>
            <Card title="Feature Importance" sub="What the model looks at most">
              <Features />
            </Card>
          </div>
        </div>
      )}

      {tab === 'Backtesting' && (
        <div className="tm-grid">
          <Card glow title="Strategy vs Nifty" sub="₹100 invested at the start" action={<Seg<Range> small active={range} onChange={setRange} options={RANGES.map((r) => ({ id: r, label: r }))} />}>
            <EquityChart range={range} height={280} />
          </Card>
          <Card title="Backtest Results" sub="How each strategy did on past data">
            <div className="tm-table-wrap">
              <table className="tm-table">
                <thead>
                  <tr>
                    <th>Strategy</th>
                    <th className="tm-right">Trades</th>
                    <th className="tm-right">Win rate</th>
                    <th className="tm-right" title="Average result per ₹1 risked">Avg R</th>
                    <th className="tm-right">Return</th>
                    <th className="tm-right">Worst fall</th>
                  </tr>
                </thead>
                <tbody>
                  {backtests.map((b) => (
                    <tr key={b.strategy}>
                      <td className="tm-strong">{b.strategy}</td>
                      <td className="tm-right tm-num">{b.trades}</td>
                      <td className="tm-right tm-num">{b.winRate}%</td>
                      <td className="tm-right tm-num tm-pos">+{b.avgR}R</td>
                      <td className="tm-right tm-num tm-pos">+{b.returnPct}%</td>
                      <td className="tm-right tm-num tm-neg">{b.dd}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </div>
      )}

      {tab === 'Live Predictions' && (
        <Card glow title="Live Predictions" sub="Today's calls and how they are going">
          <PredictionsTable />
        </Card>
      )}

      {tab === 'Feature Importance' && (
        <div className="tm-grid tm-cols-2">
          <Card glow title="Feature Importance">
            <Features />
          </Card>
          <Card title="In plain words">
            <ul className="tm-bullets">
              <li>Price momentum — is the stock already moving up? Matters most.</li>
              <li>Volume — are many people buying, not just a few?</li>
              <li>Sector strength — is the whole industry doing well?</li>
              <li>Market sentiment — is the overall mood positive?</li>
              <li>Fundamentals — company health matters, but less for short trades.</li>
            </ul>
          </Card>
        </div>
      )}

      {tab === 'Model Comparison' && (
        <Card glow title="Model Comparison">
          <div className="tm-stack" style={{ gap: '0.9rem' }}>
            {mlModels.map((m) => (
              <div key={m.name}>
                <div className="tm-between" style={{ marginBottom: 4 }}>
                  <span className="tm-strong">{m.name}</span>
                  <span className="tm-flex" style={{ gap: '0.5rem' }}>
                    <span className="tm-num">{m.accuracy}%</span>
                    <Tag tone={m.status === 'Active' ? 'green' : 'blue'}>{m.status}</Tag>
                  </span>
                </div>
                <div className="tm-meter" style={{ height: 8 }}>
                  <span
                    style={{
                      width: `${m.accuracy}%`,
                      background: m.status === 'Active' ? 'linear-gradient(90deg,#16c172,#4dffb0)' : 'linear-gradient(90deg,#2563eb,#33d6ff)',
                      boxShadow: '0 0 8px rgba(80,200,255,.5)',
                    }}
                  />
                </div>
              </div>
            ))}
            <p className="tm-note">
              Active models make real calls. Shadow models run silently alongside so we can compare them before trusting them.
            </p>
          </div>
        </Card>
      )}
    </div>
  )
}
