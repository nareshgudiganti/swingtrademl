// Admin > Risk: the risk-event log (tracker oa2). Every buy the bot wanted that a safety limit turned away, newest
// first. Read only. It asks for exactly what the classic Safety page asks for (same call, same latest 100, same
// cached query), so both pages always show the same events in the same words.

import { useQuery } from '@tanstack/react-query'

import { api } from '../api/client'
import type { RiskEvent } from '../api/types'
import { formatCurrency, formatDateTime } from '../lib/format'
import { RISK_EVENT_LIMIT, ruleLabel } from '../lib/riskRules'
import { Card } from './ui'

export default function RiskEventLog() {
  const events = useQuery({ queryKey: ['riskEvents'], queryFn: () => api.riskEvents(RISK_EVENT_LIMIT) })
  return <RiskEventLogView loading={events.isLoading} failed={events.isError} rows={events.data} />
}

/** The panel itself, given the query's state (kept apart so each state can be tested). */
export function RiskEventLogView({ loading, failed, rows }: { loading: boolean; failed: boolean; rows?: RiskEvent[] }) {
  return (
    <Card
      title="Everything the safety rules blocked"
      sub={`A buy the bot wanted that a limit turned away. These are not errors: they are the limits doing their job. The latest ${RISK_EVENT_LIMIT}, newest first.`}
    >
      <div data-testid="risk-event-log">
        {loading && <p className="tm-dim">Loading…</p>}
        {failed && <p className="tm-neg">Could not load the list of blocked buys. Try again shortly.</p>}
        {!loading && !failed && rows && rows.length === 0 && <p className="tm-dim">Nothing has been blocked yet.</p>}
        {!failed && rows && rows.length > 0 && (
          <>
            <p className="tm-dim" style={{ marginTop: 0 }}>
              {`${rows.length} ${rows.length === 1 ? 'event' : 'events'}`}
              {rows.length >= RISK_EVENT_LIMIT && ` (only the latest ${RISK_EVENT_LIMIT} are shown; older ones are kept but not listed)`}
            </p>
            <div className="tm-table-wrap" tabIndex={0} role="region" aria-label="Table, scroll sideways to see more">
              <table className="tm-table">
                <thead>
                  <tr>
                    <th>When</th>
                    <th>Stock</th>
                    <th>Why it was skipped</th>
                    <th>Detail</th>
                    <th>Amount</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.id} data-event={row.id}>
                      <td>{formatDateTime(row.ts)}</td>
                      <td className="tm-strong">{row.symbol ?? '—'}</td>
                      <td className="tm-wrap">{ruleLabel(row.rule)}</td>
                      <td className="tm-wrap tm-dim">{row.reason}</td>
                      <td className="tm-num">{row.amount_inr != null ? formatCurrency(row.amount_inr) : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </Card>
  )
}
