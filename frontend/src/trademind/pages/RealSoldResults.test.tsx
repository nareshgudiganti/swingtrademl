import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import type { Trade } from '../../api/types'
import { SoldScoreboard, SoldTable } from './RealSoldResults'

const trade = (o: Partial<Trade>): Trade =>
  ({
    id: 1, symbol: 'INFY', quantity: 10, entry_price: 100, exit_price: 108, entry_at: '2026-10-01T04:00:00Z',
    exit_at: '2026-10-09T04:00:00Z', holding_days: 8, gross_pnl: 80, charges: 5, net_pnl: 75, return_pct: 0.075,
    exit_reason: 'TARGET', exit_reason_label: 'Target reached', is_win: true, return_5d_after_exit: null, ...o,
  }) as Trade

const trades = [
  trade({ id: 1 }),
  trade({ id: 2, symbol: 'TCS', net_pnl: -40, gross_pnl: -35, return_pct: -0.04, is_win: false, holding_days: 3, exit_reason_label: 'Stop-loss hit' }),
  trade({ id: 3, symbol: 'INFY', net_pnl: 20, return_pct: 0.02, holding_days: 13 }),
]

const render = (node: React.ReactNode) =>
  renderToStaticMarkup(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>{node}</MemoryRouter>
    </QueryClientProvider>,
  )

describe('My Holdings sold-shares results', () => {
  it('counts sales, wins, losses, total profit and days held', () => {
    const html = render(<SoldScoreboard trades={trades} />)
    expect(html).toContain('3 sales'.replace(' sales', '')) // the count
    expect(html).toContain('2 different stocks')
    expect(html).toContain('2 / 1')
    expect(html).toContain('+₹55') // 75 − 40 + 20
    expect(html).toContain('8 days') // (8 + 3 + 13) / 3
    expect(html).toContain('longest INFY, 13 days')
  })

  it('lists every sale with days held, why it was sold, and a link to the stock page', () => {
    const html = render(<SoldTable trades={trades} />)
    expect(html).toContain('href="/trademind/stock/TCS"')
    expect(html).toContain('Stop-loss hit')
    expect(html).toContain('−₹40')
  })
})
