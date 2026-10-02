import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'

const STATUS_PLAIN: Record<string, string> = {
  'on track': 'On track',
  drift: 'Drifting',
  breakdown: 'Breaking down',
  'stop hit': 'Stop hit',
  'past horizon': 'Past 15 days',
}

const W = 320
const H = 140
const PAD = 22

/** One open trade day by day: the shaded band is where similar past trades
 *  usually were (middle half), the line is this trade. Brain M15. */
export function HoldingTracker({ symbol }: { symbol: string }) {
  const track = useQuery({ queryKey: ['brainTrack', symbol], queryFn: () => api.brainTrack(symbol) })
  const data = track.data
  const last = data?.points[data.points.length - 1]
  if (!data || !last) return null

  const band = data.band
  const values = [0, ...band.flatMap(([, low, , high]) => [low, high]), ...data.points.map((p) => p.ret)]
  const lo = Math.min(...values)
  const hi = Math.max(...values)
  const span = hi - lo || 0.01
  const days = Math.max(15, ...data.points.map((p) => p.day_n))
  const x = (d: number) => PAD + (d / days) * (W - 2 * PAD)
  const y = (r: number) => H - PAD - ((r - lo) / span) * (H - 2 * PAD)

  const area =
    band.length > 0
      ? [
          `${x(0)},${y(0)}`,
          ...band.map(([d, , , high]) => `${x(d)},${y(high)}`),
          ...[...band].reverse().map(([d, low]) => `${x(d)},${y(low)}`),
        ].join(' ')
      : ''
  const line = [`${x(0)},${y(0)}`, ...data.points.map((p) => `${x(p.day_n)},${y(p.ret)}`)].join(' ')

  return (
    <div className="card" style={{ margin: '0.8rem 0', padding: '0.7rem' }}>
      <div className="between">
        <strong>{STATUS_PLAIN[last.status] ?? last.status}</strong>
        <span className="stat-sub">
          {last.day_n <= 15 ? `day ${last.day_n} of up to 15` : `day ${last.day_n}`} · {(last.ret * 100).toFixed(1)}%
        </span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={`${symbol} against similar trades`}>
        {area && <polygon points={area} fill="var(--accent-soft, #dbeafe)" />}
        <line x1={x(0)} x2={x(days)} y1={y(0)} y2={y(0)} stroke="currentColor" strokeOpacity={0.25} />
        <polyline points={line} fill="none" stroke="var(--accent, #2563eb)" strokeWidth={2} />
      </svg>
      <div className="stat-sub">{last.reason}</div>
      <div className="stat-sub" style={{ opacity: 0.8 }}>
        Shaded: where similar past trades usually were on each day (the middle half). Line: this trade.
      </div>
    </div>
  )
}
