// A TradeMind-styled telling of components/HoldingTracker.tsx's band chart
// (brain M15): one open trade, day by day, against similar past trades. The
// shaded band is where similar past trades usually sat on each day (their
// middle half, p25-p75); the line is this trade. Pure presentational — the
// page fetches `useTrack(symbol)` through live.ts and hands the result in.

import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import type { BrainTrack } from '../api/types'
import { signed, toneClass } from './ui'

const STATUS_PLAIN: Record<string, string> = {
  'on track': 'On track',
  drift: 'Drifting',
  breakdown: 'Breaking down',
  'stop hit': 'Stop hit',
  'past horizon': 'Past 15 days',
  'no data': 'No new prices',
}

export function PositionBand({
  track,
  entry,
  target,
  stop,
  height = 240,
}: {
  track: BrainTrack
  entry?: number | null
  target?: number | null
  stop?: number | null
  height?: number
}) {
  const last = track.points[track.points.length - 1]
  if (!last) return <p className="tm-dim">No days tracked yet for this trade.</p>

  const byDay = new Map<number, { low?: number; high?: number; actual?: number | null }>()
  for (const [day, low, , high] of track.band) {
    byDay.set(day, { ...byDay.get(day), low: low * 100, high: high * 100 })
  }
  for (const p of track.points) {
    byDay.set(p.day_n, { ...byDay.get(p.day_n), actual: p.ret * 100 })
  }
  const data = Array.from(byDay.entries())
    .sort(([a], [b]) => a - b)
    .map(([day, v]) => ({
      day,
      band: v.low != null && v.high != null ? ([v.low, v.high] as [number, number]) : undefined,
      actual: v.actual ?? null,
    }))

  // Target/stop are prices; this chart's Y axis is % return, so the lines
  // are drawn at the same % move from entry the price levels represent —
  // computed from the real entry price, never invented.
  const targetRet = entry && target ? ((target - entry) / entry) * 100 : null
  const stopRet = entry && stop ? ((stop - entry) / entry) * 100 : null

  return (
    <div>
      <div className="tm-flex" style={{ justifyContent: 'space-between', marginBottom: '0.4rem' }}>
        <strong>{STATUS_PLAIN[last.status] ?? last.status}</strong>
        <span className={`tm-num ${toneClass(last.ret)}`}>
          {last.day_n <= 15 ? `day ${last.day_n} of up to 15` : `day ${last.day_n}`} · {signed(last.ret * 100)}
        </span>
      </div>
      <div className="tm-chart" style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={{ top: 10, right: 50, left: -6, bottom: 0 }}>
            <CartesianGrid vertical={false} />
            <XAxis dataKey="day" tickLine={false} axisLine={false} />
            <YAxis tickLine={false} axisLine={false} width={46} tickFormatter={(v: number) => `${v}%`} />
            <Tooltip
              content={({ active, payload }) =>
                active && payload?.length ? (
                  <div className="tm-tooltip">
                    {payload
                      .filter((p) => p.dataKey === 'actual' && p.value != null)
                      .map((p) => (
                        <div key={String(p.dataKey)}>{signed(Number(p.value))}</div>
                      ))}
                  </div>
                ) : null
              }
            />
            <Area dataKey="band" stroke="none" fill="#4f8cff" fillOpacity={0.18} isAnimationActive={false} />
            {targetRet != null && (
              <ReferenceLine
                y={targetRet}
                stroke="#2ee68a"
                strokeDasharray="5 4"
                label={{ value: 'Target', position: 'right', fill: '#2ee68a', fontSize: 10 }}
              />
            )}
            {stopRet != null && (
              <ReferenceLine
                y={stopRet}
                stroke="#ff4d6a"
                strokeDasharray="5 4"
                label={{ value: 'Stop', position: 'right', fill: '#ff4d6a', fontSize: 10 }}
              />
            )}
            <Line
              dataKey="actual"
              stroke="#2ee68a"
              strokeWidth={2.4}
              dot={false}
              connectNulls={false}
              isAnimationActive={false}
              style={{ filter: 'drop-shadow(0 0 5px #2ee68a)' }}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <p className="tm-dim" style={{ fontSize: '0.76rem', marginTop: '0.4rem' }}>
        Shaded: where similar past trades usually were on each day (the middle half). Line: this trade.
      </p>
      <p className="tm-dim" style={{ fontSize: '0.76rem' }}>{last.reason}</p>
    </div>
  )
}
