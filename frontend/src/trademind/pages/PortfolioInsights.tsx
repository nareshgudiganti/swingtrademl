// Two read-only cards for the Portfolio page: where the money sits (rings by stock and by sector) and the closed-trades
// scoreboard. Display only; the Add / Sell buttons live in the position panel and call the existing paper paths.

import { useState } from 'react'

import type { DetailedPosition, Trade } from '../../api/types'
import { Card, Donut, inr, toneClass } from '../ui'
import { allocationBySector, allocationByStock, closedSummary } from './portfolioViews'

const money = (n: number) => `${n < 0 ? '−' : ''}₹${inr(Math.abs(n), 0)}`

export function AllocationCard({ rows }: { rows: DetailedPosition[] }) {
  const [by, setBy] = useState<'stock' | 'sector'>('stock')
  const slices = by === 'stock' ? allocationByStock(rows) : allocationBySector(rows)
  if (slices.length === 0) return null
  const total = slices.reduce((s, x) => s + x.value, 0)
  return (
    <Card title="Where your money is" sub="Share of the current value of what you hold.">
      <div className="tm-toolbar" style={{ marginBottom: '0.6rem' }}>
        {(['stock', 'sector'] as const).map((k) => (
          <button key={k} type="button" className="tm-btn op-chip" aria-pressed={by === k} onClick={() => setBy(k)}>
            {k === 'stock' ? 'By stock' : 'By sector'}
          </button>
        ))}
      </div>
      <div className="tm-flex tm-wrap" style={{ gap: '1.5rem', alignItems: 'center' }} data-testid="allocation">
        <Donut
          segments={slices.map((s) => ({ pct: Math.round(s.pct * 10) / 10, color: s.color, name: s.name }))}
          center={
            <>
              <div className="tm-ring-value">{money(total)}</div>
              <div className="tm-ring-label">held now</div>
            </>
          }
        />
        <ul style={{ listStyle: 'none', margin: 0, padding: 0, flex: 1, minWidth: 200 }}>
          {slices.map((s) => (
            <li key={s.name} className="tm-flex" style={{ justifyContent: 'space-between', gap: '0.75rem', padding: '0.2rem 0' }}>
              <span>
                <span aria-hidden style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 2, background: s.color, marginRight: 8 }} />
                {s.name}
              </span>
              <span className="tm-num">
                {s.pct.toFixed(0)}% <span className="tm-dim">· {money(s.value)}</span>
              </span>
            </li>
          ))}
        </ul>
      </div>
    </Card>
  )
}

function Stat({ label, value, note, tone }: { label: string; value: string; note?: string; tone?: string }) {
  return (
    <div>
      <div className="tm-stat-label">{label}</div>
      <div className={`tm-stat-value ${tone ?? ''}`}>{value}</div>
      {note && <div className="tm-dim">{note}</div>}
    </div>
  )
}

export function ClosedScoreboard({ trades }: { trades: Trade[] }) {
  const s = closedSummary(trades)
  if (s.count === 0) return null
  return (
    <div className="tm-grid tm-cols-4" data-testid="closed-scoreboard" style={{ marginBottom: '0.8rem' }}>
      <Stat label="Trades closed" value={String(s.count)} note={`${s.wins} won · ${s.losses} lost`} />
      <Stat label="Win rate" value={s.winRate === null ? '—' : `${s.winRate.toFixed(0)}%`} note="of closed trades made money" />
      <Stat label="Total profit / loss" value={money(s.net)} tone={toneClass(s.net)} note="after charges, closed trades only" />
      <Stat
        label="Average win / loss"
        value={`${s.avgWin === null ? '—' : money(s.avgWin)} / ${s.avgLoss === null ? '—' : money(s.avgLoss)}`}
        note={s.best ? `best ${s.best.symbol} ${money(s.best.net)}` : undefined}
      />
    </div>
  )
}
