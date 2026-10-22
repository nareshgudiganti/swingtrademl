// oa8: the bell lists what the brain really sent (brain_alerts), the stage chip says what /brain/stage says, and an
// account the server refuses sees nothing at all (no error in the top bar).
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToString } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import type { BrainAlertRecord, BrainStage } from '../api/types'
import TopBarAlerts, { TopBarAlertsView } from './TopBarAlerts'

const alerts: BrainAlertRecord[] = [
  { id: 12, kind: 'holding', text: 'TCS: time to EXIT.', alert_date: '2026-10-20', sent_at: '2026-10-20T10:25:00+00:00', channel: 'telegram' },
  { id: 11, kind: 'banner', text: 'Market mode is now DEFENSIVE.', alert_date: '2026-10-20', sent_at: '2026-10-20T10:20:00+00:00', channel: 'telegram' },
]
const stage = { stage: 'shadow', plain: 'Practice only: the brain records ideas but buys nothing.' } as BrainStage

const draw = (el: React.ReactElement) => renderToString(<MemoryRouter>{el}</MemoryRouter>)

describe('TopBarAlertsView', () => {
  it('shows the stage chip with the stage from /brain/stage', () => {
    const html = draw(<TopBarAlertsView stage={stage} alerts={alerts} seenId={0} />)
    expect(html).toContain('data-testid="stage-chip"')
    expect(html).toContain('data-stage="shadow"')
    expect(html).toContain('Practice')
    expect(html).toContain('Practice only: the brain records ideas but buys nothing.')
  })

  it.each([
    ['approval', 'Approval'],
    ['auto', 'Auto'],
  ])('names the %s stage', (name, label) => {
    const html = draw(<TopBarAlertsView stage={{ ...stage, stage: name } as BrainStage} alerts={[]} seenId={0} />)
    expect(html).toContain(`data-stage="${name}"`)
    expect(html).toContain(`>${label}<`)
  })

  it('the bell is a named button that counts unseen alerts', () => {
    const html = draw(<TopBarAlertsView stage={stage} alerts={alerts} seenId={11} />)
    expect(html).toContain('aria-label="Alerts, 1 new"')
    expect(html).toContain('aria-expanded="false"')
    expect(html).toContain('data-testid="alerts-bell"')
  })

  it('lists the alerts when open, newest first, marking which are new', () => {
    const html = draw(<TopBarAlertsView stage={stage} alerts={alerts} seenId={11} initiallyOpen />)
    expect(html).toContain('aria-expanded="true"')
    expect(html.indexOf('TCS: time to EXIT.')).toBeLessThan(html.indexOf('Market mode is now DEFENSIVE.'))
    expect(html.match(/data-new="true"/g)).toHaveLength(1)
    expect(html).toContain('Trading stage: Practice')
  })

  it('an empty list says so in plain words', () => {
    const html = draw(<TopBarAlertsView stage={stage} alerts={[]} seenId={0} initiallyOpen />)
    expect(html).toContain('No alerts yet')
    expect(html).toContain('aria-label="Alerts"')
  })

  it('draws nothing for what the server refused', () => {
    expect(draw(<TopBarAlertsView stage={undefined} alerts={undefined} seenId={0} />)).toBe('')
    const onlyStage = draw(<TopBarAlertsView stage={stage} alerts={undefined} seenId={0} />)
    expect(onlyStage).toContain('stage-chip')
    expect(onlyStage).not.toContain('alerts-bell')
    const onlyBell = draw(<TopBarAlertsView stage={undefined} alerts={alerts} seenId={0} />)
    expect(onlyBell).toContain('alerts-bell')
    expect(onlyBell).not.toContain('stage-chip')
  })
})

describe('TopBarAlerts (with the server)', () => {
  it('draws nothing while the answers are not in (no spinner, no error)', () => {
    const client = new QueryClient()
    const html = renderToString(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <TopBarAlerts />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    expect(html).toBe('')
  })

  it('uses whatever is cached: the stage and the alerts', () => {
    const client = new QueryClient()
    client.setQueryData(['brainStage'], stage)
    client.setQueryData(['brainAlertsRecent'], alerts)
    const html = renderToString(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <TopBarAlerts />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    expect(html).toContain('data-stage="shadow"')
    expect(html).toContain('alerts-bell')
  })
})
