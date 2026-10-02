import { drawdownSeries, portfolio, riskChecks, riskLimits } from '../data'
import { Card, CheckItem, GlowArea, Meter, Ring } from '../ui'

export default function Risk() {
  const blocked = riskChecks.filter((r) => !r.ok)

  return (
    <div className="tm-page tm-grid">
      <Card glow={blocked.length ? true : 'green'}>
        <div className="tm-between tm-wrap">
          <div className="tm-flex">
            <span className="tm-state-icon" style={blocked.length ? { borderColor: 'var(--tm-amber)', color: 'var(--tm-amber)', boxShadow: '0 0 24px rgba(255,181,71,.5)' } : undefined}>
              <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6l8-3z" />
              </svg>
            </span>
            <div>
              <div className="tm-state-word" style={{ fontSize: '1.5rem', color: blocked.length ? 'var(--tm-amber)' : undefined, textShadow: 'none' }}>
                {blocked.length ? 'TRADING ALLOWED — WITH LIMITS' : 'ALL CLEAR'}
              </div>
              <div className="tm-dim" style={{ marginTop: 4 }}>
                {blocked.length
                  ? `${blocked.length} limit is reached: ${blocked.map((b) => b.note).join('; ')}`
                  : 'Every safety check passed — new trades are allowed.'}
              </div>
            </div>
          </div>
        </div>
      </Card>

      <div className="tm-grid tm-cols-4">
        <Card>
          <div className="tm-score">
            <Ring value={portfolio.riskUsedPct} size={76} stroke={7} color="amber" center={<span className="tm-ring-value" style={{ fontSize: 18 }}>{portfolio.riskUsedPct}%</span>} />
            <div>
              <div className="tm-score-name">Risk used</div>
              <div className="tm-score-verdict tm-warn">Moderate</div>
            </div>
          </div>
        </Card>
        <Card>
          <div className="tm-score">
            <Ring value={4.2} max={15} size={76} stroke={7} color="red" center={<span className="tm-ring-value" style={{ fontSize: 16 }}>4.2%</span>} />
            <div>
              <div className="tm-score-name">Drawdown (halt at 15%)</div>
              <div className="tm-score-verdict tm-pos">Safe</div>
            </div>
          </div>
        </Card>
        <Card>
          <div className="tm-score">
            <Ring value={8} max={10} size={76} stroke={7} color="blue" center={<span className="tm-ring-value" style={{ fontSize: 18 }}>8/10</span>} />
            <div>
              <div className="tm-score-name">Open positions</div>
              <div className="tm-score-verdict">2 slots free</div>
            </div>
          </div>
        </Card>
        <Card>
          <div className="tm-score">
            <Ring value={portfolio.cashPct} size={76} stroke={7} color="violet" center={<span className="tm-ring-value" style={{ fontSize: 18 }}>{portfolio.cashPct}%</span>} />
            <div>
              <div className="tm-score-name">Cash available</div>
              <div className="tm-score-verdict tm-pos">Healthy</div>
            </div>
          </div>
        </Card>
      </div>

      <div className="tm-grid tm-cols-3">
        <Card className="tm-span-2" title="Risk Limits" sub="Each bar shows how close you are to a hard limit">
          <div className="tm-stack" style={{ gap: '0.9rem' }}>
            {riskLimits.map((l) => {
              const pct = (l.used / l.limit) * 100
              const color = pct >= 100 ? '#ff4d6a' : pct >= 75 ? '#ffb547' : '#2ee68a'
              return (
                <div key={l.name}>
                  <div className="tm-between" style={{ marginBottom: 4 }}>
                    <span>
                      <span className="tm-strong">{l.name}</span>
                      <span className="tm-faint"> · {l.plain}</span>
                    </span>
                    <span className="tm-num" style={{ color, fontWeight: 600 }}>
                      {l.used}
                      {l.unit} / {l.limit}
                      {l.unit}
                    </span>
                  </div>
                  <Meter pct={pct} color={color} />
                </div>
              )
            })}
          </div>
        </Card>
        <Card title="Safety Checks" sub="Run before every new trade">
          {riskChecks.map((r) => (
            <CheckItem key={r.name} tone={r.ok ? 'pos' : 'warn'}>
              {r.name}
              {r.note && <div className="tm-faint">{r.note}</div>}
            </CheckItem>
          ))}
        </Card>
      </div>

      <div className="tm-grid tm-cols-3">
        <Card className="tm-span-2" title="Drawdown" sub="How far the portfolio was below its best point, day by day">
          <GlowArea data={drawdownSeries} color="#ff4d6a" height={180} axes domain={[-5, 0]} formatter={(v) => `${v.toFixed(1)}%`} />
        </Card>
        <Card title="What the brain does automatically">
          <CheckItem tone="neutral">Loss today over 2% → pauses new trades until tomorrow</CheckItem>
          <CheckItem tone="neutral">Drawdown hits 15% → stops all new trades</CheckItem>
          <CheckItem tone="neutral">A sector over 25% → no more trades in it</CheckItem>
          <CheckItem tone="neutral">Market turns Defensive → smaller sizes</CheckItem>
        </Card>
      </div>
    </div>
  )
}
