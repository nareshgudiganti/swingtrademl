import { useNavigate, Link } from 'react-router-dom'

import {
  featured,
  ideas,
  indices,
  marketEvents,
  marketState,
  portfolio,
  todaysInsights,
} from '../data'
import { ActionPill, BrainArt, Card, CheckItem, GlowArea, Icon, Ring, Tag, inr, signed, toneClass } from '../ui'

export default function Home() {
  const navigate = useNavigate()
  const top = ideas.filter((i) => i.action === 'TRADE' || i.action === 'WATCH').slice(0, 5)

  return (
    <div className="tm-page tm-grid">
      {/* Hero: market state · brain · indices */}
      <Card glow className="tm-hero">
        <div>
          <div className="tm-card-title" style={{ marginBottom: '0.9rem' }}>
            Market State
          </div>
          <div className="tm-hero-state">
            <span className="tm-state-icon">
              <Icon.Check />
            </span>
            <div>
              <div className="tm-state-word">{marketState.mood}</div>
              <div className="tm-pos" style={{ marginTop: 4, fontWeight: 600 }}>
                {marketState.confidence}% Confidence
              </div>
            </div>
          </div>
          <p className="tm-dim" style={{ fontSize: '0.78rem', margin: '0.9rem 0 0', maxWidth: 340 }}>
            {marketState.headline}
          </p>
        </div>

        <div className="tm-brain">
          <BrainArt />
          <div className="tm-brain-title">TradeMind Brain</div>
          <div className="tm-dim" style={{ fontSize: '0.74rem' }}>
            Analyzing {marketState.signalsAnalysed}+ signals in real-time
          </div>
        </div>

        <div className="tm-rows tm-index-list" style={{ justifySelf: 'end', width: '100%', maxWidth: 300 }}>
          {indices.map((x) => (
            <div key={x.name} className="tm-row" title={x.hint}>
              <span className="tm-strong">{x.name}</span>
              <span className="tm-num tm-strong">{inr(x.value, x.value < 100 ? 1 : 0)}</span>
              <span className={`tm-num ${toneClass(x.changePct)}`} style={{ minWidth: 56, textAlign: 'right' }}>
                {signed(x.changePct, 2)}
              </span>
            </div>
          ))}
        </div>
      </Card>

      <div className="tm-grid tm-cols-3">
        {/* Top opportunities */}
        <Card title="Top Opportunities" action={<Link className="tm-link" to="/trademind/opportunities">View All</Link>}>
          <table className="tm-table">
            <tbody>
              {top.map((i) => (
                <tr key={i.symbol} className="tm-clickable" onClick={() => navigate(`/trademind/stock/${encodeURIComponent(i.symbol)}`)}>
                  <td className="tm-strong">{i.name.toUpperCase()}</td>
                  <td>
                    <ActionPill action={i.action} />
                  </td>
                  <td className="tm-num">{i.confidence}%</td>
                  <td className="tm-num tm-pos tm-right" title="Expected reward for every ₹1 risked">
                    +{i.expectedR.toFixed(1)}R
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>

        {/* Portfolio health */}
        <Card title="Portfolio Health" action={<Link className="tm-link" to="/trademind/portfolio">Details</Link>}>
          <div className="tm-flex" style={{ gap: '1.25rem' }}>
            <div style={{ textAlign: 'center' }}>
              <Ring value={portfolio.health} size={128} stroke={11} label="Good" />
              <div className="tm-pos" style={{ fontWeight: 600, marginTop: 6 }}>
                Good
              </div>
            </div>
            <dl className="tm-kv" style={{ flex: 1 }}>
              <dt>Positions</dt>
              <dd>{portfolio.positions}</dd>
              <dt>Open P&amp;L</dt>
              <dd className="tm-pos">+₹{inr(portfolio.gain, 0)}</dd>
              <dt title="Share of your allowed risk already in use">Risk Used</dt>
              <dd className="tm-warn">{portfolio.riskUsedPct}%</dd>
              <dt>Cash</dt>
              <dd className="tm-neg">{portfolio.cashPct}%</dd>
            </dl>
          </div>
        </Card>

        {/* Today's insights */}
        <Card title="Today's Insights">
          {todaysInsights.map((x) => (
            <CheckItem key={x.text} tone={x.tone}>
              {x.text}
            </CheckItem>
          ))}
        </Card>
      </div>

      {/* Extra row */}
      <div className="tm-grid tm-cols-3">
        <Card
          className="tm-span-2"
          title="Portfolio Growth"
          sub="Last 3 months"
          action={
            <span className="tm-pos tm-strong tm-num">
              ₹{inr(portfolio.value, 0)} <small>({signed(portfolio.gainPct)})</small>
            </span>
          }
        >
          <GlowArea data={portfolio.equity} height={170} axes formatter={(v) => `${(v / 100000).toFixed(1)}L`} />
        </Card>

        <Card title="Best Idea Today" glow="green">
          <div className="tm-between" style={{ marginBottom: '0.6rem' }}>
            <div>
              <div className="tm-strong" style={{ fontSize: '1rem' }}>
                {featured.name}
              </div>
              <div className="tm-num">
                ₹{inr(featured.price)} <span className="tm-pos">{signed(featured.changePct)}</span>
              </div>
            </div>
            <Ring value={featured.confidence} size={70} stroke={7} center={<span className="tm-ring-value" style={{ fontSize: 17 }}>{featured.confidence}%</span>} />
          </div>
          {featured.why.slice(0, 3).map((w) => (
            <CheckItem key={w}>{w}</CheckItem>
          ))}
          <div style={{ marginTop: '0.6rem' }}>
            <Link className="tm-btn" to={`/trademind/ai/${featured.symbol}`}>
              Why this trade?
            </Link>
          </div>
        </Card>
      </div>

      <div className="tm-grid tm-cols-2">
        <Card title="Coming Up" sub="Events that can move prices">
          <div className="tm-rows">
            {marketEvents.map((e) => (
              <div className="tm-row" key={e.title}>
                <span className="tm-flex">
                  <span className="tm-icon-badge">
                    <Icon.Clock />
                  </span>
                  <span>
                    <div className="tm-strong">{e.title}</div>
                    <div className="tm-faint">{e.date}</div>
                  </span>
                </span>
                <Tag tone={e.impact === 'High' ? 'red' : 'amber'}>{e.impact} impact</Tag>
              </div>
            ))}
          </div>
        </Card>
        <Card title="Brain Status" sub="What the brain checked this morning">
          <CheckItem>Prices updated for all 24 watchlist stocks</CheckItem>
          <CheckItem>Market mood judged: {marketState.mood.toLowerCase()}</CheckItem>
          <CheckItem>Risk limits checked — new trades allowed</CheckItem>
          <CheckItem tone="warn">Banking is above the 25% sector limit</CheckItem>
          <CheckItem tone="neutral">Next full scan: tomorrow 08:45</CheckItem>
        </Card>
      </div>
    </div>
  )
}
