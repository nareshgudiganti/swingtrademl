import { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import {
  candles,
  findIdea,
  fundamentals,
  news,
  optionsView,
  reasoningChain,
  similarCases,
  stockAnalysis,
  stockScores,
  technicals,
} from '../data'
import { ActionPill, Candles, Card, CheckItem, Icon, Ring, Seg, Tabs, Tag, inr, signed, toneClass } from '../ui'

const TABS = ['Overview', 'Technical', 'Fundamental', 'AI Analysis', 'Similar Cases', 'News', 'Options'] as const
type TabId = (typeof TABS)[number]

const RANGES = ['1D', '1W', '1M', '3M', '6M', '1Y', '5Y'] as const
type Range = (typeof RANGES)[number]
const RANGE_BARS: Record<Range, number> = { '1D': 26, '1W': 35, '1M': 44, '3M': 70, '6M': 95, '1Y': 120, '5Y': 140 }

const SCORE_COLOR = ['blue', 'green', 'violet', 'blue'] as const

export default function StockDetail() {
  const { symbol } = useParams()
  const idea = findIdea(symbol)
  const [tab, setTab] = useState<TabId>('Overview')
  const [range, setRange] = useState<Range>('3M')
  const bars = useMemo(
    () => candles(idea.symbol.length * 97 + RANGE_BARS[range], RANGE_BARS[range], idea.price * 0.95, idea.price),
    [idea, range],
  )
  const targetPct = ((idea.target - idea.price) / idea.price) * 100
  const stopPct = ((idea.stop - idea.price) / idea.price) * 100

  const chart = (
    <Card
      className="tm-span-2"
      title={<span className="tm-dim" style={{ fontWeight: 500 }}>{idea.name} · daily price</span>}
      action={
        <Seg<Range> small active={range} onChange={setRange} options={RANGES.map((r) => ({ id: r, label: r }))} />
      }
    >
      <Candles bars={bars} height={300} target={idea.target} stop={idea.stop} />
    </Card>
  )

  return (
    <div className="tm-page">
      <div className="tm-flex tm-wrap" style={{ marginBottom: '0.8rem', gap: '0.9rem' }}>
        <Link to="/trademind/opportunities" className="tm-link tm-flex" style={{ gap: 2 }}>
          <Icon.Back size={14} /> Opportunities
        </Link>
        <span className="tm-icon-badge" style={{ borderColor: 'rgba(79,140,255,.6)', color: 'var(--tm-blue)' }}>
          <Icon.Target />
        </span>
        <span style={{ fontSize: '1.25rem', fontWeight: 700 }}>{idea.name.toUpperCase()}</span>
        <span className="tm-num" style={{ fontSize: '1.15rem', fontWeight: 600 }}>
          ₹{inr(idea.price)}
        </span>
        <span className={`tm-num ${toneClass(idea.changePct)}`} style={{ fontWeight: 600 }}>
          {signed(idea.changePct)}
        </span>
        <ActionPill action={idea.action} />
        <Tag tone="violet">{idea.confidence}% Confidence</Tag>
      </div>

      <Tabs tabs={TABS} active={tab} onChange={setTab} />

      {tab === 'Overview' && (
        <div className="tm-grid">
          <div className="tm-grid tm-cols-3">
            {chart}
            <Card glow title="TradeMind Analysis">
              {stockAnalysis.map((s) => (
                <CheckItem key={s}>{s}</CheckItem>
              ))}
              <div className="tm-grid tm-cols-2" style={{ marginTop: '0.9rem', gap: '0.7rem' }}>
                <div>
                  <div className="tm-stat-label">Target</div>
                  <div className="tm-stat-value tm-pos">
                    ₹{inr(idea.target, 0)} <small>({signed(targetPct, 0)})</small>
                  </div>
                </div>
                <div>
                  <div className="tm-stat-label">Stop Loss</div>
                  <div className="tm-stat-value tm-neg">
                    ₹{inr(idea.stop, 0)} <small>({signed(stopPct, 0)})</small>
                  </div>
                </div>
                <div>
                  <div className="tm-stat-label" title="Expected reward for every ₹1 risked">
                    Expected R
                  </div>
                  <div className="tm-stat-value tm-pos">+{idea.expectedR.toFixed(1)}R</div>
                </div>
                <div>
                  <div className="tm-stat-label">Timeframe</div>
                  <div className="tm-stat-value" style={{ color: 'var(--tm-violet)' }}>
                    {idea.timeframe}
                  </div>
                </div>
              </div>
            </Card>
          </div>

          <div className="tm-grid tm-cols-4">
            {stockScores.map((s, i) => (
              <Card key={s.name} glow={i === 3}>
                <div className="tm-score" title={s.hint}>
                  <Ring value={s.value} size={66} stroke={6} color={SCORE_COLOR[i]} />
                  <div>
                    <div className="tm-score-name">{s.name}</div>
                    <div className={`tm-score-verdict ${i === 3 ? '' : 'tm-pos'}`} style={i === 3 ? { color: '#8db4ff' } : undefined}>
                      {s.verdict}
                    </div>
                  </div>
                </div>
              </Card>
            ))}
          </div>
        </div>
      )}

      {tab === 'Technical' && (
        <div className="tm-grid tm-cols-3">
          {chart}
          <Card title="What the chart says" sub="Each signal in plain words">
            <div className="tm-rows">
              {technicals.map((t) => (
                <div key={t.name} className="tm-row" style={{ alignItems: 'flex-start' }}>
                  <span>
                    <div className="tm-strong">{t.name}</div>
                    <div className="tm-faint">{t.plain}</div>
                  </span>
                  <span className={t.tone === 'pos' ? 'tm-pos' : 'tm-dim'} style={{ fontWeight: 600, whiteSpace: 'nowrap' }}>
                    {t.value}
                  </span>
                </div>
              ))}
            </div>
          </Card>
        </div>
      )}

      {tab === 'Fundamental' && (
        <div className="tm-grid tm-cols-3">
          <Card glow title="Business Health">
            <div style={{ display: 'grid', placeItems: 'center', padding: '0.5rem 0' }}>
              <Ring value={72} size={140} stroke={12} label="Good" />
            </div>
            <p className="tm-note" style={{ textAlign: 'center' }}>
              Sales and profits are growing, and the share isn't expensive for its earnings.
            </p>
          </Card>
          <Card className="tm-span-2" title="Key Numbers">
            <div className="tm-grid tm-cols-3">
              {fundamentals.map((f) => (
                <div key={f.name} className="tm-card" style={{ padding: '0.75rem' }}>
                  <div className="tm-stat-label">{f.name}</div>
                  <div className={`tm-stat-value ${f.tone === 'pos' ? 'tm-pos' : ''}`}>{f.value}</div>
                </div>
              ))}
            </div>
          </Card>
        </div>
      )}

      {tab === 'AI Analysis' && (
        <div className="tm-grid tm-cols-2">
          <Card glow title="How the brain reached this">
            <div className="tm-chain">
              {reasoningChain.map((s, i) => (
                <div key={s.title} className={`tm-chain-step ${i === reasoningChain.length - 1 ? 'tm-final' : ''}`}>
                  <span className="tm-chain-dot">
                    <Icon.Check />
                  </span>
                  <div>
                    <div className="tm-chain-title">{s.title}</div>
                    <div className="tm-chain-sub">{s.sub}</div>
                  </div>
                </div>
              ))}
            </div>
          </Card>
          <Card title="In plain words">
            <p style={{ marginTop: 0 }}>
              TradeMind suggests <strong className="tm-pos">{idea.action}</strong> for {idea.name} with{' '}
              <strong>{idea.confidence}% confidence</strong>.
            </p>
            <ul className="tm-bullets">
              {idea.why.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
            <div style={{ marginTop: '1rem' }}>
              <Link className="tm-btn" to={`/trademind/ai/${idea.symbol}`}>
                Open full reasoning
              </Link>
            </div>
          </Card>
        </div>
      )}

      {tab === 'Similar Cases' && (
        <Card glow title="Times this looked the same before" sub="What happened next, in each case">
          <div className="tm-table-wrap">
            <table className="tm-table">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Stock</th>
                  <th>Situation</th>
                  <th>Market</th>
                  <th className="tm-right">Outcome</th>
                </tr>
              </thead>
              <tbody>
                {similarCases.map((c) => (
                  <tr key={c.date + c.symbol}>
                    <td>{c.date}</td>
                    <td className="tm-strong">{c.symbol}</td>
                    <td>{c.situation}</td>
                    <td className={c.regime === 'Bullish' ? 'tm-pos' : 'tm-warn'}>{c.regime}</td>
                    <td className={`tm-right tm-num ${toneClass(c.outcomePct)}`}>{signed(c.outcomePct)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {tab === 'News' && (
        <Card glow title="Recent News" sub="Sample headlines — news feed not connected yet">
          <div className="tm-rows">
            {news.map((n) => (
              <div key={n.title} className="tm-row">
                <span className="tm-flex">
                  <Tag tone={n.tone === 'pos' ? 'green' : n.tone === 'neg' ? 'red' : 'blue'}>
                    {n.tone === 'pos' ? 'Positive' : n.tone === 'neg' ? 'Negative' : 'Neutral'}
                  </Tag>
                  <span>
                    <div className="tm-strong">{n.title}</div>
                    <div className="tm-faint">{n.source}</div>
                  </span>
                </span>
                <span className="tm-faint">{n.when}</span>
              </div>
            ))}
          </div>
        </Card>
      )}

      {tab === 'Options' && (
        <div className="tm-grid tm-cols-4">
          {[
            { label: 'Put/Call ratio', value: optionsView.pcr.toFixed(2), hint: 'Above 1 = more traders betting on a rise', tone: 'tm-pos' },
            { label: 'Max pain', value: `₹${optionsView.maxPain}`, hint: 'Price where most options expire worthless', tone: '' },
            { label: 'Resistance (call wall)', value: `₹${optionsView.callWall}`, hint: 'Many sellers expect a ceiling here', tone: 'tm-neg' },
            { label: 'Support (put wall)', value: `₹${optionsView.putWall}`, hint: 'Many sellers expect a floor here', tone: 'tm-pos' },
          ].map((o) => (
            <Card key={o.label}>
              <div className="tm-stat-label">{o.label}</div>
              <div className={`tm-stat-value ${o.tone}`} style={{ fontSize: '1.5rem' }}>
                {o.value}
              </div>
              <div className="tm-note">{o.hint}</div>
            </Card>
          ))}
          <Card className="tm-span-2" title="Option fear level" sub="How costly options are vs the past year">
            <div className="tm-flex">
              <Ring value={optionsView.ivRank} size={90} stroke={8} color="blue" />
              <p className="tm-dim" style={{ margin: 0 }}>
                Options are cheaper than usual — traders don't expect wild swings in this stock right now.
              </p>
            </div>
          </Card>
        </div>
      )}
    </div>
  )
}
