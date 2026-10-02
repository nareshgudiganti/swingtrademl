import {
  breadth,
  indices,
  marketEvents,
  marketSignals,
  marketState,
  regimeHistory,
  regimeTimeline,
  sectors,
  series,
} from '../data'
import { Card, Donut, GlowArea, HBar, Icon, Ring, Tag, inr, signed, toneClass } from '../ui'

const MOOD_COLORS = ['#2ee68a', '#ffb547', '#ff7a45', '#ff4d6a']
const vix = series(77, 40, 16, -0.004, 0.06)
const VIX = indices[2]!

function RegimeStrip() {
  // One column per day, height = Nifty level, colour = the brain's mood that day.
  const vals = regimeTimeline.map((p) => p.v)
  const lo = Math.min(...vals)
  const hi = Math.max(...vals)
  const W = 300
  const H = 120
  const w = W / regimeTimeline.length
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} preserveAspectRatio="none">
      {regimeTimeline.map((p, i) => {
        const h = 20 + ((p.v - lo) / (hi - lo || 1)) * (H - 26)
        return (
          <rect
            key={i}
            x={i * w}
            y={H - h}
            width={w + 0.4}
            height={h}
            fill={MOOD_COLORS[p.mood]}
            opacity={0.75}
            style={{ filter: `drop-shadow(0 0 3px ${MOOD_COLORS[p.mood]})` }}
          />
        )
      })}
    </svg>
  )
}

export default function Market() {
  const total = breadth.advancing + breadth.declining + breadth.unchanged
  const advPct = Math.round((breadth.advancing / total) * 100)
  const maxSector = Math.max(...sectors.map((s) => Math.abs(s.changePct)))

  return (
    <div className="tm-page tm-grid">
      <div className="tm-grid tm-cols-3">
        <Card glow className="tm-span-2" title="Market Regime">
          <div className="tm-flex" style={{ alignItems: 'stretch', gap: '1.25rem' }}>
            <div className="tm-hero-state" style={{ minWidth: 200 }}>
              <span className="tm-state-icon">
                <Icon.Check />
              </span>
              <div>
                <div className="tm-state-word" style={{ fontSize: '1.7rem' }}>
                  {marketState.mood}
                </div>
                <div className="tm-pos" style={{ fontWeight: 600, marginTop: 4 }}>
                  {marketState.confidence}% Confidence
                </div>
              </div>
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <GlowArea data={regimeTimeline} height={150} />
            </div>
          </div>
          <p className="tm-note">{marketState.headline}</p>
        </Card>

        <Card title="Regime History" sub="The brain's market mood, last 3 months">
          <div className="tm-flex" style={{ alignItems: 'flex-start' }}>
            <div className="tm-legend" style={{ minWidth: 92 }}>
              {regimeHistory.map((r) => (
                <div key={r.mood} style={{ color: r.color }}>
                  <span className="tm-swatch" />
                  <span style={{ color: 'var(--tm-text)' }}>{r.mood}</span>
                </div>
              ))}
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <RegimeStrip />
            </div>
          </div>
          <div className="tm-flex tm-wrap" style={{ marginTop: '0.6rem', gap: '0.4rem' }}>
            {regimeHistory.map((r) => (
              <span key={r.mood} className="tm-faint" style={{ fontSize: '0.72rem' }}>
                {r.mood} {r.share}%
              </span>
            ))}
          </div>
        </Card>
      </div>

      <div className="tm-grid tm-cols-3">
        <Card title="Sector Rotation" sub="Today's change by sector">
          {sectors.map((s) => (
            <HBar
              key={s.name}
              label={s.name}
              value={s.changePct}
              max={maxSector}
              tone={s.changePct > 0.5 ? 'up' : s.changePct < 0 ? 'down' : 'flat'}
              right={signed(s.changePct)}
            />
          ))}
        </Card>

        <Card title="Market Breadth" sub="How many stocks rose vs fell today">
          <div style={{ display: 'grid', placeItems: 'center', padding: '0.4rem 0' }}>
            <Ring
              value={advPct}
              size={150}
              stroke={12}
              center={
                <>
                  <span className="tm-ring-value" style={{ fontSize: 34 }}>
                    {advPct}
                    <small style={{ fontSize: 16 }}>%</small>
                  </span>
                  <span className="tm-pos" style={{ fontSize: '0.78rem' }}>
                    Advancing
                  </span>
                </>
              }
            />
          </div>
          <div className="tm-between" style={{ marginTop: '0.6rem', padding: '0 0.6rem' }}>
            <div style={{ textAlign: 'center' }}>
              <div className="tm-stat-value tm-pos" style={{ fontSize: '1.4rem' }}>
                {inr(breadth.advancing, 0)}
              </div>
              <div className="tm-stat-label">Advancing</div>
            </div>
            <div style={{ textAlign: 'center' }}>
              <div className="tm-stat-value tm-neg" style={{ fontSize: '1.4rem' }}>
                {inr(breadth.declining, 0)}
              </div>
              <div className="tm-stat-label">Declining</div>
            </div>
          </div>
        </Card>

        <Card title="Key Market Signals">
          <div className="tm-rows">
            {marketSignals.map((s) => (
              <div key={s.label} className="tm-row" title={s.hint}>
                <span className="tm-flex" style={{ gap: '0.55rem' }}>
                  <span
                    className="tm-check-icon"
                    style={{ color: s.tone === 'pos' ? 'var(--tm-green)' : 'var(--tm-amber)', width: 18, height: 18 }}
                  >
                    {s.tone === 'pos' ? <Icon.Check /> : <Icon.Minus />}
                  </span>
                  <span className={s.tone === 'pos' ? 'tm-pos' : 'tm-warn'}>{s.label}</span>
                </span>
                <span className="tm-num tm-strong">{s.value}</span>
              </div>
            ))}
          </div>
        </Card>
      </div>

      <div className="tm-grid tm-cols-3">
        <Card title="Fear Gauge (India VIX)" sub="Lower = calmer market, better for new trades">
          <GlowArea data={vix} color="#33d6ff" height={140} formatter={(v) => v.toFixed(1)} />
          <div className="tm-between tm-note">
            <span>Now {VIX.value}</span>
            <span className={toneClass(-VIX.changePct)}>{signed(VIX.changePct, 1)} today</span>
          </div>
        </Card>
        <Card title="Breadth Mix">
          <div className="tm-flex" style={{ gap: '1.25rem' }}>
            <Donut
              size={130}
              stroke={18}
              segments={[
                { pct: breadth.advancing, color: '#2ee68a', name: 'Advancing' },
                { pct: breadth.declining, color: '#ff4d6a', name: 'Declining' },
                { pct: breadth.unchanged, color: '#4f8cff', name: 'Unchanged' },
              ]}
              center={<span className="tm-dim" style={{ fontSize: '0.72rem' }}>{inr(total, 0)} stocks</span>}
            />
            <div className="tm-legend" style={{ flex: 1 }}>
              <div className="tm-legend-row" style={{ color: '#2ee68a' }}>
                <span><span className="tm-swatch" /><span style={{ color: 'var(--tm-text)' }}>Advancing</span></span>
                <span>{inr(breadth.advancing, 0)}</span>
              </div>
              <div className="tm-legend-row" style={{ color: '#ff4d6a' }}>
                <span><span className="tm-swatch" /><span style={{ color: 'var(--tm-text)' }}>Declining</span></span>
                <span>{inr(breadth.declining, 0)}</span>
              </div>
              <div className="tm-legend-row" style={{ color: '#4f8cff' }}>
                <span><span className="tm-swatch" /><span style={{ color: 'var(--tm-text)' }}>Unchanged</span></span>
                <span>{inr(breadth.unchanged, 0)}</span>
              </div>
            </div>
          </div>
        </Card>
        <Card title="Key Events" sub="Dates that can move the market">
          <div className="tm-rows">
            {marketEvents.map((e) => (
              <div className="tm-row" key={e.title}>
                <span>
                  <span className="tm-faint" style={{ marginRight: 8 }}>{e.date}</span>
                  {e.title}
                </span>
                <Tag tone={e.impact === 'High' ? 'red' : 'amber'}>{e.impact}</Tag>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  )
}
