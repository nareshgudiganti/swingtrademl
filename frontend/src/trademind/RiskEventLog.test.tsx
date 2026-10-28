// oa2: Admin > Risk shows the risk-event log. Acceptance: "Shows the same events as the classic Safety page for the
// same period." Same API call, same query (key and limit), same rule wording, every row shown.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToString } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import type { RiskEvent } from '../api/types'
import { RISK_EVENT_LIMIT, RULE_LABEL } from '../lib/riskRules'
import safetySource from '../pages/Safety.tsx?raw'
import riskSource from './pages/Risk.tsx?raw'
import logSource from './RiskEventLog.tsx?raw'
import RiskEventLog, { RiskEventLogView } from './RiskEventLog'

const EVENTS: RiskEvent[] = [
  { id: 3, ts: '2026-10-20T10:05:00+05:30', mode: 'paper', strategy_id: 7, instrument_id: 1, symbol: 'INFY', rule: 'SECTOR_CAP', reason: 'IT would be 31% of the account', amount_inr: 24000 },
  { id: 2, ts: '2026-10-19T10:05:00+05:30', mode: 'paper', strategy_id: 7, instrument_id: 2, symbol: null, rule: 'ENTRIES_HALTED', reason: 'Halted from the dashboard', amount_inr: null },
  { id: 1, ts: '2026-10-18T10:05:00+05:30', mode: 'paper', strategy_id: 7, instrument_id: 3, symbol: 'TCS', rule: 'SOMETHING_NEW', reason: 'A rule with no plain name yet', amount_inr: 5000 },
]

function render(seed?: { data?: RiskEvent[] }): string {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  if (seed?.data) client.setQueryData(['riskEvents'], seed.data)
  return renderToString(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <RiskEventLog />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('the risk-event log asks for exactly what the classic Safety page asks for', () => {
  it('uses the same query key and the same number of latest events', () => {
    expect(safetySource).toMatch(/queryKey: \['riskEvents'\], queryFn: \(\) => api\.riskEvents\(RISK_EVENT_LIMIT\)/)
    expect(logSource).toMatch(/queryKey: \['riskEvents'\], queryFn: \(\) => api\.riskEvents\(RISK_EVENT_LIMIT\)/)
    expect(RISK_EVENT_LIMIT).toBe(100)
  })

  it('is shown on Admin > Risk', () => {
    expect(riskSource).toMatch(/<RiskEventLog \/>/)
  })
})

describe('what it shows', () => {
  it('every event, newest first as the server sent them, in the same plain words as Safety', () => {
    const html = render({ data: EVENTS })
    const rows = html.match(/data-event="\d+"/g)
    expect(rows).toEqual(['data-event="3"', 'data-event="2"', 'data-event="1"'])
    expect(html).toContain(RULE_LABEL.SECTOR_CAP!)
    expect(html).toContain(RULE_LABEL.ENTRIES_HALTED!)
    expect(html).toContain('SOMETHING_NEW') // an unknown rule shows its own name, never a blank
    expect(html).toContain('IT would be 31% of the account')
    expect(html).toContain('INFY')
    expect(html).toContain('3 events')
  })

  it('says plainly when nothing was blocked', () => {
    expect(render({ data: [] })).toContain('Nothing has been blocked yet.')
  })

  it('says plainly when the list could not be loaded, never an empty list', () => {
    const html = renderToString(<RiskEventLogView loading={false} failed rows={undefined} />)
    expect(html).toContain('Could not load the list')
    expect(html).not.toContain('Nothing has been blocked yet.')
  })

  it('says when only the latest events are listed', () => {
    const many = Array.from({ length: RISK_EVENT_LIMIT }, (_, i) => ({ ...EVENTS[0]!, id: i + 10 }))
    const html = renderToString(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <RiskEventLogView loading={false} failed={false} rows={many} />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    expect(html).toContain(`only the latest ${RISK_EVENT_LIMIT} are shown`)
    expect(render({ data: EVENTS })).not.toContain('only the latest')
  })

  it('shows loading while it waits', () => {
    expect(render()).toContain('Loading')
  })
})
