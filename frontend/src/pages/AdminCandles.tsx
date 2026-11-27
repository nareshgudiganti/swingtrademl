import { useCallback, useEffect, useState } from 'react'

import { ErrorBox, Loading } from '../components/Loading'
import type { AdminCall } from './AdminModules'

// Admin only, read only (#565): daily price bars that reached us late, or were changed after we stored them. The
// ingestion writer already records both; this screen only shows them. Nothing here changes a price or a decision.

export type LateRow = { symbol: string; day: string; due_by: string; received_at: string; late_by_hours: number }
export type CorrectionRow = {
  symbol: string
  day: string
  corrected_at: string
  old_close: number
  new_close: number
  close_change_pct: number | null
  old_volume: number
  new_volume: number
}
export type CandleLog = {
  window_days: number
  late_rule: string
  unknown_note: string
  late_total: number
  late: LateRow[]
  corrections: CorrectionRow[]
}

const when = (iso: string) => new Date(iso).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' }) + ' IST'
// `day` is already the India date (YYYY-MM-DD); read it as a plain date so no time zone can shift it.
const day = (iso: string) =>
  new Date(`${iso}T00:00:00Z`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })
const pct = (x: number | null) => (x == null ? 'unknown' : `${x > 0 ? '+' : ''}${(x * 100).toFixed(2)}%`)

export function CandleLogView({ data }: { data: CandleLog }) {
  return (
    <div>
      <h2 style={{ marginTop: 0 }}>Late and corrected prices</h2>
      <p>
        Last {data.window_days} days. This page only shows information. Nothing here changes a price, a score or a
        decision.
      </p>
      <h3>Prices that arrived late</h3>
      <p>
        {data.late_rule} {data.unknown_note}
      </p>
      {data.late.length === 0 ? (
        <p>No late prices in this period.</p>
      ) : (
        <>
          {data.late_total > data.late.length && (
            <p>
              Showing the newest {data.late.length} of {data.late_total}.
            </p>
          )}
          <table className="table">
            <thead>
              <tr>
                <th>Stock</th>
                <th>Day of the price</th>
                <th>Needed by</th>
                <th>Arrived</th>
                <th>Late by</th>
              </tr>
            </thead>
            <tbody>
              {data.late.map((r) => (
                <tr key={`${r.symbol}-${r.day}`}>
                  <td>{r.symbol}</td>
                  <td>{day(r.day)}</td>
                  <td>{when(r.due_by)}</td>
                  <td>{when(r.received_at)}</td>
                  <td>{r.late_by_hours} hours</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
      <h3>Prices changed after we stored them</h3>
      {data.corrections.length === 0 ? (
        <p>No corrected prices in this period.</p>
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th>Stock</th>
              <th>Day of the price</th>
              <th>Changed</th>
              <th>Close before → after</th>
              <th>Change</th>
              <th>Volume before → after</th>
            </tr>
          </thead>
          <tbody>
            {data.corrections.map((r) => (
              <tr key={`${r.symbol}-${r.day}-${r.corrected_at}`}>
                <td>{r.symbol}</td>
                <td>{day(r.day)}</td>
                <td>{when(r.corrected_at)}</td>
                <td>
                  ₹{r.old_close} → ₹{r.new_close}
                </td>
                <td>{pct(r.close_change_pct)}</td>
                <td>
                  {r.old_volume} → {r.new_volume}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

export default function AdminCandles({ call, onExpired }: { call: AdminCall; onExpired: () => void }) {
  const [data, setData] = useState<CandleLog | null>(null)
  const [error, setError] = useState<unknown>(null)
  const load = useCallback(() => {
    call<CandleLog>('/admin/console/candle-log')
      .then(setData)
      .catch((e: { code?: string | null }) => (e.code === 'mfa_required' ? onExpired() : setError(e)))
  }, [call, onExpired])
  useEffect(load, [load])
  if (error != null) return <ErrorBox error={error} />
  if (data === null) return <Loading label="Loading late and corrected prices…" />
  return <CandleLogView data={data} />
}
