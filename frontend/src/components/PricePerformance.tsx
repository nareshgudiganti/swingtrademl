import { useState } from 'react'
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

import type { Candle } from '../api/types'
import { Empty } from './Loading'
import { formatCurrency, formatDate, formatSignedPercent, pnlClass } from '../lib/format'

function performanceFor(candles: Candle[], sessions: number) {
  const latest = candles.at(-1)
  const start = candles.at(-sessions - 1)
  if (!latest || !start || start.close <= 0) return null

  const change = latest.close - start.close
  return {
    startClose: start.close,
    startDate: start.ts,
    latestClose: latest.close,
    latestDate: latest.ts,
    change,
    changePct: change / start.close,
  }
}

function PerformanceCard({
  label,
  sessions,
  value,
}: {
  label: string
  sessions: number
  value: ReturnType<typeof performanceFor>
}) {
  if (!value) {
    return (
      <div className="card">
        <div className="stat-label">{label}</div>
        <div className="stat-sub">Need {sessions + 1} daily closes to calculate this.</div>
      </div>
    )
  }

  return (
    <div className="card">
      <div className="stat-label">{label}</div>
      <div className={`stat-value ${pnlClass(value.change)}`}>{formatSignedPercent(value.changePct)}</div>
      <div className={`stat-sub ${pnlClass(value.change)}`}>
        {value.change >= 0 ? '+' : ''}{formatCurrency(value.change)} per share
      </div>
      <div className="stat-sub">
        {formatCurrency(value.startClose)} on {formatDate(value.startDate)} to {formatCurrency(value.latestClose)}
      </div>
    </div>
  )
}

/** Per-symbol closing-price chart with a selectable lookback window — shared
 * by any page that lets you click a stock to see how its price has actually
 * moved (Dashboard's buy candidates, Search's looked-up symbol). */
export default function PricePerformance({ symbol, candles }: { symbol: string; candles: Candle[] }) {
  const [unit, setUnit] = useState<'days' | 'weeks'>('weeks')
  const [amount, setAmount] = useState(2)
  const latest = candles.at(-1)
  if (!latest) return <Empty label={`No daily price history is available for ${symbol}.`} />

  const availableSessions = candles.length - 1
  const multiplier = unit === 'weeks' ? 5 : 1
  const maxAmount = Math.max(1, Math.floor(availableSessions / multiplier))
  const selectedAmount = Math.min(amount, maxAmount)
  const sessions = selectedAmount * multiplier
  const selectedCandles = candles.slice(-sessions - 1)
  const performance = performanceFor(candles, sessions)
  const chartData = selectedCandles.map((candle) => ({
    date: formatDate(candle.ts),
    close: candle.close,
  }))

  return (
    <div>
      <h2 style={{ marginTop: 0 }}>{symbol} price performance</h2>
      <p className="muted" style={{ marginTop: 0 }}>
        Closing-price movement over trading sessions. This is per-share price gain/loss, not your realised profit.
      </p>
      <div className="performance-controls">
        <label>
          <span className="stat-label">Measure in</span>
          <select value={unit} onChange={(event) => setUnit(event.target.value as 'days' | 'weeks')}>
            <option value="days">Trading days</option>
            <option value="weeks">Weeks</option>
          </select>
        </label>
        <label className="performance-range">
          <span className="stat-label">
            Range: {selectedAmount} {unit === 'weeks' && selectedAmount === 1 ? 'week' : unit === 'weeks' ? 'weeks' : selectedAmount === 1 ? 'day' : 'days'}
            {' '}({sessions} sessions)
          </span>
          <input
            type="range"
            min="1"
            max={maxAmount}
            value={selectedAmount}
            onChange={(event) => setAmount(Number(event.target.value))}
          />
        </label>
      </div>
      <div className="grid">
        <div className="card">
          <div className="stat-label">Latest close</div>
          <div className="stat-value">{formatCurrency(latest.close)}</div>
          <div className="stat-sub">{formatDate(latest.ts)}</div>
        </div>
        <PerformanceCard
          label={`Selected ${unit === 'weeks' ? 'period' : 'range'}`}
          sessions={sessions}
          value={performance}
        />
      </div>
      <div className="performance-chart" aria-label={`${symbol} closing price chart`}>
        <ResponsiveContainer width="100%" height={260}>
          <AreaChart data={chartData} margin={{ top: 8, right: 8, left: 8, bottom: 0 }}>
            <defs>
              <linearGradient id="price-fill" x1="0" x2="0" y1="0" y2="1">
                <stop offset="5%" stopColor="var(--accent)" stopOpacity={0.35} />
                <stop offset="95%" stopColor="var(--accent)" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="var(--border)" vertical={false} />
            <XAxis dataKey="date" tick={{ fill: 'var(--text-dim)', fontSize: 11 }} minTickGap={28} />
            <YAxis
              dataKey="close"
              tick={{ fill: 'var(--text-dim)', fontSize: 11 }}
              tickFormatter={(value: number) => `₹${value.toFixed(0)}`}
              width={56}
              domain={['dataMin', 'dataMax']}
            />
            <Tooltip
              formatter={(value: number) => [formatCurrency(value), 'Close']}
              contentStyle={{ background: 'var(--surface-2)', border: '1px solid var(--border)' }}
            />
            <Area type="monotone" dataKey="close" stroke="var(--accent)" strokeWidth={2} fill="url(#price-fill)" />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
