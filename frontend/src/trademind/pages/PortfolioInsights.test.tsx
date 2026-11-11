import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import type { DetailedPosition, Trade } from '../../api/types'
import paperSource from './PaperPositions.tsx?raw'
import { AllocationCard, ClosedScoreboard } from './PortfolioInsights'

const pos = (symbol: string, sector: string, current_value: number) => ({ symbol, sector, current_value }) as DetailedPosition
const trade = (symbol: string, net_pnl: number) => ({ symbol, net_pnl, is_win: net_pnl > 0, quantity: 1, entry_price: 100 }) as Trade

describe('Portfolio insights cards', () => {
  it('draws the allocation ring with every stock named', () => {
    const html = renderToStaticMarkup(<AllocationCard rows={[pos('AAA', 'Banks', 700), pos('BBB', 'IT', 300)]} />)
    expect(html).toContain('Where your money is')
    expect(html).toContain('AAA')
    expect(html).toContain('70%')
    expect(html).toContain('By sector')
  })

  it('shows nothing when no money is held', () => {
    expect(renderToStaticMarkup(<AllocationCard rows={[]} />)).toBe('')
  })

  it('shows the closed-trade count, win rate and total', () => {
    const html = renderToStaticMarkup(<ClosedScoreboard trades={[trade('A', 500), trade('B', -200)]} />)
    expect(html).toContain('Trades closed')
    expect(html).toContain('1 won · 1 lost')
    expect(html).toContain('50%')
    expect(html).toContain('₹300')
  })

  it('shows nothing before any trade has closed', () => {
    expect(renderToStaticMarkup(<ClosedScoreboard trades={[]} />)).toBe('')
  })
})

describe('Add and Sell stay on the existing paper paths', () => {
  it('still sells through closePosition and buys through testerPaperBuy only', () => {
    expect(paperSource).toContain("api.closePosition(id, 'MANUAL')")
    expect(paperSource).toContain('api.testerPaperBuy(')
    expect(paperSource).not.toMatch(/api\.(placeOrder|realBuy|realSell|kite)/i)
  })
})
