import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { api, ApiError } from '../api/client'
import type { LanePick, LanePickRow, LanesResponse, LaneSummary } from '../api/types'
import { Empty, ErrorBox, Loading } from '../components/Loading'
import { formatDate } from '../lib/format'

// Horizon picks (owner only). Per-lane cards keep HISTORY (past data) and FORWARD (live, watch-only) apart, then the
// older 5-day table. It only reads. There is no action button here: a row is a test record, not a trade and not advice.

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

export const BANNER = 'Test picks only. A history pass allows watch-only testing, not trading. Nothing here is advice.'
const NOT_MEASURED = 'Not measured yet'

const LANE_STATUS_TEXT: Record<string, string> = {
  history_only: 'History test only',
  forward_watching: 'Watching live',
  review_due: 'Review due',
  inconclusive: 'Not enough data yet',
}
const LANE_ORDER = ['10-large', '15-large', '15-mid']

export function pctText(v: number | null): string {
  if (v === null || v === undefined) return '—'
  return `${v >= 0 ? '+' : ''}${(v * 100).toFixed(2)}%`
}

/** A fraction shown as a percent. A missing number says so in words and is never shown as zero. */
export function pctOrWords(v: number | null | undefined): string {
  return v === null || v === undefined ? NOT_MEASURED : pctText(v)
}

function numOrWords(v: number | null | undefined, digits = 3): string {
  return v === null || v === undefined ? NOT_MEASURED : v.toFixed(digits)
}

function laneRank(l: LaneSummary): number {
  const i = LANE_ORDER.indexOf(`${l.horizon_days}-${l.cap_group}`)
  return i === -1 ? LANE_ORDER.length : i
}

function Row({ k, children }: { k: string; children: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, padding: '2px 0', fontSize: 13 }}>
      <span className="muted">{k}</span>
      <span style={{ textAlign: 'right' }}>{children}</span>
    </div>
  )
}

const panelStyle = { flex: '1 1 260px', border: '1px solid var(--border, #ddd)', borderRadius: 8, padding: 10 }
const DRAWDOWN_NOTE = 'This is the fall in the running total of picks, not a portfolio drawdown.'

export function HistoryPanel({ h }: { h: LaneSummary['history'] }) {
  const days = h.ranking.days === null ? 'number of days not given' : `${h.ranking.days} days tested`
  const trades = h.after_cost.trades === null ? 'number of trades not given' : `${h.after_cost.trades} trades`
  return (
    <div style={panelStyle} data-panel="history">
      <h4 style={{ margin: '0 0 6px' }}>History (past data)</h4>
      {!h.available ? (
        <p className="muted" style={{ fontSize: 13 }}>
          {NOT_MEASURED}. No past-data test is available for this lane.
        </p>
      ) : (
        <>
          {h.label && <p style={{ fontSize: 12, fontWeight: 600, margin: '0 0 6px' }}>{h.label}</p>}
          <Row k="Ranking skill">
            {numOrWords(h.ranking.mean_ic)} ({days}
            {h.ranking.lower_bound === null ? '' : `; at worst about ${h.ranking.lower_bound.toFixed(3)}`})
          </Row>
          <Row k="Average result after costs">
            {pctOrWords(h.after_cost.mean_net_return)} ({trades})
          </Row>
          <Row k="Excess over the group's own average stock">{pctOrWords(h.benchmark_excess)}</Row>
          <Row k="Fall in the running total of picks">{pctOrWords(h.drawdown)}</Row>
          <p className="muted" style={{ fontSize: 11, margin: '2px 0 0' }}>
            {DRAWDOWN_NOTE}
          </p>
          {h.note && (
            <p className="muted" style={{ fontSize: 12, margin: '6px 0 0' }}>
              {h.note}
            </p>
          )}
        </>
      )}
    </div>
  )
}

export function ForwardPanel({ f, cap }: { f: LaneSummary['forward']; cap: string }) {
  const { low, high } = f.uncertainty
  const range =
    low === null || high === null
      ? `${NOT_MEASURED} (only ${f.completed} finished picks)`
      : `Could be as low as ${pctOrWords(low)} or as high as ${pctOrWords(high)} (from ${f.completed} finished picks)`
  const review =
    f.review.state === 'done'
      ? 'Done'
      : f.review.state === 'due'
        ? `Due now (after ${f.review.due_after_sessions} sessions)`
        : `Not due yet (${f.review.sessions_done} of ${f.review.due_after_sessions} sessions)`
  return (
    <div style={panelStyle} data-panel="forward">
      <h4 style={{ margin: '0 0 6px' }}>Forward (live, watch-only)</h4>
      {(f.sample_warning || cap === 'mid') && (
        <p style={{ fontSize: 12, fontWeight: 600, margin: '0 0 6px', padding: 6, background: 'rgba(200,140,0,0.15)', borderRadius: 6 }}>
          {f.sample_warning ?? ''}
          {cap === 'mid' && ' Mid-cap stocks trade thinner, so real prices can differ more from these test prices.'}
        </p>
      )}
      <Row k="Picks">
        {f.picks} total · {f.completed} finished · {f.open} open
      </Row>
      <Row k="Hit rate">
        {f.hit_rate === null ? NOT_MEASURED : `${(f.hit_rate * 100).toFixed(0)}% of ${f.completed} finished picks`}
      </Row>
      <Row k="Average result after costs">
        {pctOrWords(f.mean_net_return)} ({f.completed} finished picks)
      </Row>
      <Row k="Excess over the group's own average stock">{pctOrWords(f.benchmark_excess)}</Row>
      <Row k="Fall in the running total of picks">{pctOrWords(f.drawdown)}</Row>
      <p className="muted" style={{ fontSize: 11, margin: '2px 0 4px' }}>
        {DRAWDOWN_NOTE}
      </p>
      <Row k="Uncertainty">{range}</Row>
      <Row k="Review">{review}</Row>
    </div>
  )
}

export function LaneCard({
  lane,
  selected,
  onSelect,
}: {
  lane: LaneSummary
  selected: boolean
  onSelect: (k: string) => void
}) {
  return (
    <div className="card" style={{ padding: 12, margin: '8px 0', outline: selected ? '2px solid var(--accent, #2563eb)' : 'none' }}>
      <button
        className="btn btn-ghost"
        style={{ width: '100%', textAlign: 'left', display: 'block' }}
        aria-pressed={selected}
        onClick={() => onSelect(lane.slot_key)}
      >
        <strong>
          {lane.horizon_days}-day · {lane.cap_group === 'mid' ? 'Mid cap' : 'Large cap'}
        </strong>
        {' · '}
        {lane.model ? `${lane.model.name} (${lane.model.version})` : 'No model chosen yet'}
        <br />
        <span className="muted" style={{ fontSize: 13 }}>
          {LANE_STATUS_TEXT[lane.status] ?? lane.status} · {lane.sessions_recorded} sessions recorded
          {lane.started_on ? ` since ${formatDate(lane.started_on)}` : ''} · tap to see its picks
        </span>
      </button>
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 8 }}>
        <HistoryPanel h={lane.history} />
        <ForwardPanel f={lane.forward} cap={lane.cap_group} />
      </div>
    </div>
  )
}

export function LanePickRowsTable({ rows }: { rows: LanePickRow[] }) {
  if (rows.length === 0) return <Empty label="No picks recorded yet for this lane." />
  return (
    <div style={{ overflowX: 'auto' }}>
      <table className="table" style={{ width: '100%', fontSize: 13 }}>
        <thead>
          <tr>
            <th>Day</th>
            <th>Stock</th>
            <th>Rank</th>
            <th>Score</th>
            <th>Status</th>
            <th>Result after costs</th>
            <th>Excess over group average</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={`${r.signal_day}-${r.symbol}`}>
              <td>{formatDate(r.signal_day)}</td>
              <td>
                <strong>{r.symbol}</strong>
              </td>
              <td>{r.rank}</td>
              <td title="A ranking score. Not a chance of profit.">{r.score === null ? '—' : r.score.toFixed(3)}</td>
              <td>{STATUS_LABEL[r.status] ?? r.status}</td>
              <td>{r.net_return === null ? 'Not yet' : pctText(r.net_return)}</td>
              <td>{r.excess_return === null ? 'Not yet' : pctText(r.excess_return)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** The lane cards. No data (endpoint missing or empty) says so plainly. */
export function LanesView({
  data,
  selected,
  onSelect,
}: {
  data: LanesResponse | null
  selected: string | null
  onSelect: (k: string) => void
}) {
  if (!data || data.lanes.length === 0) return <Empty label="No lane data yet." />
  const lanes = [...data.lanes].sort((a, b) => laneRank(a) - laneRank(b))
  return (
    <div>
      {data.note && <p className="muted">{data.note}</p>}
      {lanes.map((l) => (
        <LaneCard key={l.slot_key} lane={l} selected={selected === l.slot_key} onSelect={onSelect} />
      ))}
    </div>
  )
}

function SelectedLanePicks({ slotKey }: { slotKey: string }) {
  const q = useQuery({ queryKey: ['lane-pick-rows', slotKey], queryFn: () => api.lanePickRows(slotKey, 100) })
  if (q.isLoading) return <Loading />
  if (q.error || !q.data) return <ErrorBox error={q.error} />
  return (
    <div>
      <h3>Picks for {slotKey}</h3>
      <LanePickRowsTable rows={q.data} />
    </div>
  )
}

function LanesSection() {
  const [selected, setSelected] = useState<string | null>(null)
  const q = useQuery({
    queryKey: ['research-lanes'],
    retry: false,
    queryFn: async () => {
      try {
        return await api.lanes()
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) return null
        throw e
      }
    },
  })
  if (q.isLoading) return <Loading />
  if (q.error) return <ErrorBox error={q.error} />
  return (
    <div>
      <LanesView data={q.data ?? null} selected={selected} onSelect={setSelected} />
      {selected && <SelectedLanePicks slotKey={selected} />}
    </div>
  )
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

function FiveDayLane() {
  const [horizon, setHorizon] = useState<number | undefined>(undefined)
  const [cap, setCap] = useState('')
  const q = useQuery({ queryKey: ['lane-picks', horizon, cap], queryFn: () => api.lanePicks(horizon, cap || undefined) })

  if (q.isLoading) return <Loading />
  if (q.error || !q.data) return <ErrorBox error={q.error} />
  const d = q.data
  const horizons = Array.from(new Set(d.lanes.map((l) => l.horizon_days))).sort((a, b) => a - b)

  return (
    <div>
      <h2>5-day lane (existing models)</h2>
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

export default function HorizonPicks() {
  return (
    <div>
      <h1>Horizon picks</h1>
      <div className="card" style={{ padding: 12, margin: '8px 0', fontWeight: 600 }} role="note">
        {BANNER}
      </div>
      <LanesSection />
      <FiveDayLane />
    </div>
  )
}
