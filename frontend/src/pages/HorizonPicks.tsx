import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { api } from '../api/client'
import type { LanePick } from '../api/types'
import { Empty, ErrorBox, Loading } from '../components/Loading'
import { formatDate } from '../lib/format'

// Horizon picks (owner only). One table of every recorded test pick, tagged by horizon and cap size. It only reads.
// There is no buy button here: a row is a test record, not a trade and not advice.

const CAPS: { key: string; label: string }[] = [
  { key: '', label: 'All sizes' },
  { key: 'large', label: 'Large cap' },
  { key: 'mid', label: 'Mid cap' },
  { key: 'small', label: 'Small cap' },
]
const STATUS_LABEL: Record<string, string> = {
  open: 'Open',
  hit: 'Hit target',
  stopped: 'Stopped out',
  expired: 'Time ran out',
  closed: 'Finished',
}

export function pctText(v: number | null): string {
  if (v === null || v === undefined) return '—'
  return `${v >= 0 ? '+' : ''}${(v * 100).toFixed(2)}%`
}

export function PicksTable({ rows }: { rows: LanePick[] }) {
  if (rows.length === 0) return <Empty label="No picks recorded yet for this choice." />
  return (
    <div style={{ overflowX: 'auto' }}>
      <table className="table" style={{ width: '100%', fontSize: 13 }}>
        <thead>
          <tr>
            <th>Day</th>
            <th>Stock</th>
            <th>Horizon</th>
            <th>Size</th>
            <th>Rank</th>
            <th>Score</th>
            <th>Status</th>
            <th>Entry</th>
            <th>Result after costs</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={`${r.lane}-${r.run_no}-${r.signal_day}-${r.symbol}`}>
              <td>{formatDate(r.signal_day)}</td>
              <td>
                <strong>{r.symbol}</strong>
              </td>
              <td>{r.horizon_days}-day</td>
              <td>{r.cap_label}</td>
              <td>{r.rank ?? '—'}</td>
              <td title="A ranking score for this horizon only. Not a chance of profit.">
                {r.score === null ? '—' : r.score.toFixed(3)}
              </td>
              <td>{STATUS_LABEL[r.status] ?? r.status}</td>
              <td>{r.entry_price === null ? 'Not yet' : r.entry_price.toFixed(2)}</td>
              <td>{pctText(r.net_return)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function HorizonPicks() {
  const [horizon, setHorizon] = useState<number | undefined>(undefined)
  const [cap, setCap] = useState('')
  const q = useQuery({ queryKey: ['lane-picks', horizon, cap], queryFn: () => api.lanePicks(horizon, cap || undefined) })

  if (q.isLoading) return <Loading />
  if (q.error || !q.data) return <ErrorBox error={q.error} />
  const d = q.data
  const horizons = Array.from(new Set(d.lanes.map((l) => l.horizon_days))).sort((a, b) => a - b)

  return (
    <div>
      <h1>Horizon picks</h1>
      <p className="muted">{d.note}</p>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', margin: '8px 0' }}>
        <button className={horizon === undefined ? 'btn' : 'btn btn-ghost'} onClick={() => setHorizon(undefined)}>
          All horizons
        </button>
        {horizons.map((h) => (
          <button key={h} className={horizon === h ? 'btn' : 'btn btn-ghost'} onClick={() => setHorizon(h)}>
            {h}-day
          </button>
        ))}
        <span style={{ width: 12 }} />
        {CAPS.map((c) => (
          <button key={c.key} className={cap === c.key ? 'btn' : 'btn btn-ghost'} onClick={() => setCap(c.key)}>
            {c.label}
          </button>
        ))}
      </div>
      <div className="card" style={{ padding: 12, margin: '8px 0' }}>
        <strong>{d.summary.picks}</strong> picks · <strong>{d.summary.finished}</strong> finished ·{' '}
        <strong>{d.summary.open}</strong> open · <strong>{d.summary.wins}</strong> made money · average after costs{' '}
        <strong>{pctText(d.summary.mean_net_return)}</strong>
      </div>
      <PicksTable rows={d.rows} />
    </div>
  )
}
