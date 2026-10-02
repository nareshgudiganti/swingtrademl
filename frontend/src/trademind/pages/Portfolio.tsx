import { Link } from 'react-router-dom'

import { allocation, holdings, portfolio, suggestions } from '../data'
import { Card, CheckItem, Donut, GlowArea, Ring, inr, signed, toneClass } from '../ui'

export default function Portfolio() {
  return (
    <div className="tm-page tm-grid">
      <div className="tm-grid tm-cols-3">
        <Card glow className="tm-span-2" title="Portfolio Overview">
          <div className="tm-flex" style={{ alignItems: 'flex-end', gap: '1.5rem' }}>
            <div style={{ minWidth: 220 }}>
              <div className="tm-big tm-num" style={{ fontSize: '2.2rem' }}>
                ₹ {inr(portfolio.value, 0)}
              </div>
              <div className="tm-pos tm-num" style={{ fontWeight: 600, marginTop: 4 }}>
                {signed(portfolio.gainPct)} (+₹{inr(portfolio.gain, 0)})
              </div>
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <GlowArea data={portfolio.equity} height={130} formatter={(v) => `₹${inr(v, 0)}`} />
            </div>
          </div>
        </Card>
        <Card>
          <div className="tm-rows">
            <div className="tm-row">
              <span className="tm-dim">Positions</span>
              <span className="tm-strong">{portfolio.positions}</span>
            </div>
            <div className="tm-row">
              <span className="tm-dim">Cash</span>
              <span className="tm-strong">{portfolio.cashPct}%</span>
            </div>
            <div className="tm-row" title="Share of your allowed risk already in use">
              <span className="tm-dim">Risk Used</span>
              <span className="tm-strong tm-warn">{portfolio.riskUsedPct}%</span>
            </div>
            <div className="tm-row" title="Biggest fall from a high point">
              <span className="tm-dim">Max Drawdown</span>
              <span className="tm-strong tm-neg">{portfolio.maxDrawdownPct}%</span>
            </div>
          </div>
        </Card>
      </div>

      <div className="tm-grid tm-cols-3">
        <Card title="Sector Allocation">
          <div className="tm-flex" style={{ gap: '1.4rem' }}>
            <Donut size={140} stroke={22} segments={allocation} />
            <div className="tm-legend" style={{ flex: 1 }}>
              {allocation.map((a) => (
                <div key={a.name} className="tm-legend-row" style={{ color: a.color }}>
                  <span>
                    <span className="tm-swatch" />
                    <span style={{ color: 'var(--tm-text)' }}>{a.name}</span>
                  </span>
                  <span className="tm-strong tm-num">{a.pct}%</span>
                </div>
              ))}
            </div>
          </div>
        </Card>

        <Card title="Risk Metrics" action={<Link className="tm-link" to="/trademind/risk">Open Risk</Link>}>
          <div className="tm-grid tm-cols-2" style={{ alignItems: 'center' }}>
            <div style={{ display: 'grid', placeItems: 'center' }}>
              <Ring
                value={portfolio.riskUsedPct}
                size={110}
                stroke={10}
                color="amber"
                center={
                  <>
                    <span className="tm-ring-value" style={{ fontSize: 26 }}>
                      {portfolio.riskUsedPct}%
                    </span>
                    <span className="tm-ring-label" style={{ color: 'var(--tm-violet)' }}>
                      Risk Used
                    </span>
                  </>
                }
              />
            </div>
            <div className="tm-stack">
              <div>
                <div className="tm-stat-value tm-pos">{portfolio.gainPct}%</div>
                <div className="tm-stat-label">Portfolio Return</div>
              </div>
              <div>
                <div className="tm-stat-value tm-neg">{portfolio.maxDrawdownPct}%</div>
                <div className="tm-stat-label">Max Drawdown</div>
              </div>
            </div>
            <div style={{ display: 'grid', placeItems: 'center' }}>
              <Ring value={portfolio.health} size={84} stroke={8} />
            </div>
            <div>
              <div className="tm-stat-value tm-pos">{portfolio.health}</div>
              <div className="tm-stat-label">Portfolio Health</div>
            </div>
          </div>
        </Card>

        <Card title="Position-wise P&L">
          <div className="tm-rows">
            {holdings.map((h) => (
              <Link key={h.symbol} to={`/trademind/positions/${h.symbol}`} className="tm-row" style={{ color: 'inherit', textDecoration: 'none' }}>
                <span className="tm-strong">{h.name.toUpperCase()}</span>
                <span className={`tm-num ${toneClass(h.pnlPct)}`} style={{ fontWeight: 600 }}>
                  {signed(h.pnlPct)}
                </span>
              </Link>
            ))}
          </div>
        </Card>
      </div>

      <div className="tm-grid tm-cols-2">
        <Card title="Holdings" sub="What you own right now">
          <div className="tm-table-wrap">
            <table className="tm-table">
              <thead>
                <tr>
                  <th>Stock</th>
                  <th className="tm-right">Qty</th>
                  <th className="tm-right">Avg price</th>
                  <th className="tm-right">Value</th>
                  <th className="tm-right">P&amp;L</th>
                </tr>
              </thead>
              <tbody>
                {holdings.map((h) => {
                  const now = h.avg * (1 + h.pnlPct / 100)
                  return (
                    <tr key={h.symbol}>
                      <td className="tm-strong">{h.name}</td>
                      <td className="tm-right tm-num">{h.qty}</td>
                      <td className="tm-right tm-num">₹{inr(h.avg)}</td>
                      <td className="tm-right tm-num">₹{inr(now * h.qty, 0)}</td>
                      <td className={`tm-right tm-num ${toneClass(h.pnlPct)}`}>
                        {h.pnlPct >= 0 ? '+' : '−'}₹{inr(Math.abs((now - h.avg) * h.qty), 0)}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </Card>
        <Card glow title="Suggestions" sub="What the brain would change">
          {suggestions.map((s) => (
            <CheckItem key={s.text} tone={s.tone === 'warn' ? 'warn' : s.tone === 'pos' ? 'pos' : 'neutral'}>
              {s.text}
            </CheckItem>
          ))}
        </Card>
      </div>
    </div>
  )
}
