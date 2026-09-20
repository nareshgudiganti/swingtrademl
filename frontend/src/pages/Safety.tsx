import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../api/client'
import { Empty, ErrorBox, Loading } from '../components/Loading'
import { formatCurrency, formatDateTime } from '../lib/format'

/** The risk layer records a rejection under a machine name. These are the
 * same limits in the words the rest of the app uses for them. */
const RULE_LABEL: Record<string, string> = {
  SECTOR_CAP: 'Too much in one sector',
  POSITION_LIMIT: 'Already holding the maximum number of stocks',
  CAP_TIER: 'Small-company budget full',
  LIQUIDITY: 'Stock trades too little to buy this size',
  DEPLOYABLE: 'Market conditions cap how much goes out today',
  CASH_FLOOR: 'Would eat into the cash reserve',
  CASH: 'Not enough cash',
  DRAWDOWN: 'Account down too far — new buying halted',
  ENTRIES_HALTED: 'You halted new buying',
  COOLDOWN: 'Stopped out of this stock recently',
  DUPLICATE: 'Already holding this stock',
}

export default function Safety() {
  const queryClient = useQueryClient()
  const [reason, setReason] = useState('')

  const state = useQuery({ queryKey: ['safetyState'], queryFn: api.safetyState })
  const events = useQuery({ queryKey: ['riskEvents'], queryFn: () => api.riskEvents(100) })

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['safetyState'] })
    void queryClient.invalidateQueries({ queryKey: ['riskEvents'] })
  }
  const halt = useMutation({ mutationFn: api.haltEntries, onSuccess: invalidate })
  const resume = useMutation({ mutationFn: api.resumeEntries, onSuccess: invalidate })

  const halted = state.data ? !state.data.new_entries_enabled : false
  const rows = events.data ?? []

  return (
    <>
      <div className="page-head">
        <h1>Safety</h1>
      </div>

      {state.isLoading && <Loading />}
      {state.isError && <ErrorBox error={state.error as Error} />}

      {state.data && (
        <>
          <div className="card" style={{ marginBottom: '1.25rem' }}>
            <h2>Switches</h2>

            <div className="between" style={{ marginTop: '0.9rem' }}>
              <div>
                <div style={{ fontWeight: 600 }}>Buying new stocks</div>
                <div className="stat-sub">
                  {halted
                    ? 'Halted. Nothing new will be bought until you resume.'
                    : 'Running. The bot may open new positions within your limits.'}
                </div>
              </div>
              <span className={`badge ${halted ? 'badge-off' : 'badge-on'}`}>
                {halted ? 'HALTED' : 'ON'}
              </span>
            </div>

            <div className="between" style={{ marginTop: '0.9rem' }}>
              <div>
                <div style={{ fontWeight: 600 }}>Selling</div>
                <div className="stat-sub">
                  {/* Deliberate: halting entries never stops exits, so capital is
                      never trapped in a position heading for its stop. */}
                  {state.data.exits_enabled
                    ? 'Running. Stops and targets are still being checked every minute.'
                    : 'Stopped. Positions are NOT being watched — this is dangerous.'}
                </div>
              </div>
              <span className={`badge ${state.data.exits_enabled ? 'badge-on' : 'badge-warn'}`}>
                {state.data.exits_enabled ? 'ON' : 'STOPPED'}
              </span>
            </div>

            {halted && state.data.halt_reason && (
              <div className="note" style={{ marginTop: '1rem' }}>
                Halted{state.data.halted_at ? ` on ${formatDateTime(state.data.halted_at)}` : ''}
                {state.data.halted_by ? ` by ${state.data.halted_by}` : ''}: {state.data.halt_reason}
              </div>
            )}

            <div className="row" style={{ marginTop: '1.1rem', flexWrap: 'wrap' }}>
              {halted ? (
                <button
                  className="primary"
                  onClick={() => resume.mutate()}
                  disabled={resume.isPending}
                >
                  {resume.isPending ? 'Resuming…' : 'Resume buying'}
                </button>
              ) : (
                <>
                  <input
                    id="halt-reason"
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    placeholder="Why are you halting?"
                    style={{ flex: '1 1 260px' }}
                  />
                  <button
                    className="danger"
                    onClick={() => halt.mutate(reason.trim() || 'Halted from the dashboard')}
                    disabled={halt.isPending}
                  >
                    {halt.isPending ? 'Halting…' : 'Halt new buying'}
                  </button>
                </>
              )}
            </div>
            {(halt.isError || resume.isError) && (
              <ErrorBox error={(halt.error ?? resume.error) as Error} />
            )}
          </div>

          <div className="card">
            <h2>Everything the safety rules blocked</h2>
            <p className="stat-sub" style={{ marginTop: '0.2rem' }}>
              A buy the model wanted that a limit turned away. These are not errors — they are the
              limits doing their job, and they are worth reading to see which one binds most often.
            </p>

            {events.isLoading && <Loading />}
            {events.isError && <ErrorBox error={events.error as Error} />}
            {!events.isLoading && rows.length === 0 && (
              <Empty label="Nothing has been blocked yet." />
            )}

            {rows.length > 0 && (
              <div className="table-wrap" style={{ marginTop: '0.8rem' }}>
                <table>
                  <thead>
                    <tr>
                      <th>When</th>
                      <th>Stock</th>
                      <th>Why it was skipped</th>
                      <th>Detail</th>
                      <th className="num">Amount</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row) => (
                      <tr key={row.id}>
                        <td>{formatDateTime(row.ts)}</td>
                        <td>{row.symbol ?? '—'}</td>
                        <td>{RULE_LABEL[row.rule] ?? row.rule}</td>
                        <td className="muted">{row.reason}</td>
                        <td className="num">
                          {row.amount_inr != null ? formatCurrency(row.amount_inr) : '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </>
  )
}
