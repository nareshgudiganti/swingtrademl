import { useQuery } from '@tanstack/react-query'

import { api, ApiError } from '../api/client'
import type { HorizonReport, HorizonReportRow } from '../api/types'
import { Empty, ErrorBox, Loading } from '../components/Loading'

// One side-by-side report of the 5-, 10- and 15-day tests (owner only, read only). It never starts, promotes or
// switches anything. A missing number says so in words and is never shown as zero.

const CAP_LABEL: Record<string, string> = { large: 'Large cap', mid: 'Mid cap', small: 'Small cap' }
const NOT_MEASURED = 'Not measured yet'
const QUALIFICATION_BADGE: Record<string, string> = {
  qualified: 'Qualified',
  not_qualified: 'Not qualified yet',
  not_run: 'Not tested yet',
}

function pct(v: number | null | undefined): string {
  return v === null || v === undefined ? NOT_MEASURED : `${v >= 0 ? '+' : ''}${(v * 100).toFixed(2)}%`
}

function hitRate(v: number | null): string {
  return v === null ? NOT_MEASURED : `${(v * 100).toFixed(0)}%`
}

function Line({ k, children }: { k: string; children: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, padding: '2px 0', fontSize: 13 }}>
      <span className="muted">{k}</span>
      <span style={{ textAlign: 'right' }}>{children}</span>
    </div>
  )
}

export function HorizonCard({ row }: { row: HorizonReportRow }) {
  const f = row.forward
  const isFold = row.model?.role === 'fold'
  const nifty = f.nifty
  return (
    <div className="card" style={{ padding: 12, margin: '8px 0' }} data-horizon-row={row.key}>
      <strong>
        {row.horizon_days}-day · {CAP_LABEL[row.cap_group] ?? row.cap_group}
      </strong>
      <div style={{ fontSize: 13, margin: '4px 0' }}>
        {row.model ? (
          <>
            {row.model.name} ({row.model.version}) ·{' '}
            <span
              style={{
                fontWeight: 600,
                padding: '1px 6px',
                borderRadius: 6,
                background: isFold ? 'rgba(200,140,0,0.18)' : 'rgba(120,120,120,0.15)',
              }}
              data-model-role={row.model.role}
            >
              {row.model.role_label}
            </span>
          </>
        ) : (
          'No model chosen yet'
        )}
      </div>
      <p style={{ fontSize: 13, margin: '4px 0' }}>
        <strong>{QUALIFICATION_BADGE[row.qualification.state] ?? row.qualification.state}.</strong>{' '}
        {row.qualification.text} <span className="muted">Test: {row.qualification.protocol}.</span>
      </p>
      <Line k="Days finished (counted)">
        {f.matured_days} of {row.verdict.needed_days} needed before any reading
      </Line>
      <Line k="Picks">
        {f.picks} total · {f.finished} finished
      </Line>
      <Line k="Average result per pick, after costs">{pct(f.net_per_trade)}</Line>
      <Line k="Better than every eligible stock by">{pct(f.edge_vs_every_stock)}</Line>
      <Line k="Picks that made money">{hitRate(f.hit_rate)}</Line>
      <Line k="NIFTY 50, same dates (no costs)">
        {nifty.available && nifty.mean_return !== null
          ? `${pct(nifty.mean_return)} (${nifty.windows} windows)`
          : (nifty.note ?? NOT_MEASURED)}
      </Line>
      <p
        style={{ fontSize: 13, fontWeight: 600, margin: '6px 0 0' }}
        data-verdict={row.verdict.state}
      >
        {row.verdict.state === 'not_enough_days' ? 'Not enough days to judge.' : row.verdict.text}
      </p>
    </div>
  )
}

/** The report. No data (endpoint missing or empty) says so plainly. */
export function HorizonReportView({ data }: { data: HorizonReport | null }) {
  if (!data || data.horizons.length === 0) return <Empty label="No horizon report yet." />
  return (
    <div>
      <p className="muted">{data.note}</p>
      <div className="card" style={{ padding: 10, margin: '8px 0', fontSize: 13 }} role="note">
        <strong>Fold models are not daily models.</strong> {data.fold_model_note}
      </div>
      <p className="muted" style={{ fontSize: 12 }}>
        {data.nifty_note} {data.edge_notes.join(' ')}
      </p>
      {data.horizons.map((r) => (
        <HorizonCard key={r.key} row={r} />
      ))}
    </div>
  )
}

export function HorizonReportSection() {
  const q = useQuery({
    queryKey: ['research-horizon-report'],
    retry: false,
    queryFn: async () => {
      try {
        return await api.horizonReport()
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) return null
        throw e
      }
    },
  })
  return (
    <section aria-labelledby="horizon-report-title">
      <h2 id="horizon-report-title">All three horizons side by side</h2>
      {q.isLoading ? <Loading /> : q.error ? <ErrorBox error={q.error} /> : <HorizonReportView data={q.data ?? null} />}
    </section>
  )
}
