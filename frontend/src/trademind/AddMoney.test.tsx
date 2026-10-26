// Adding practice money: the owner can record a top-up, sees what was added, and is told it is not profit.
// "Buy more" on the Testing page's open positions adds a second lot through the same tester buy.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToString } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import clientSource from '../api/client.ts?raw'
import AddMoneyCard from './AddMoney'
import paperSource from './pages/PaperPositions.tsx?raw'
import portfolioNewSource from './pages/PortfolioNew.tsx?raw'
import portfolioSource from './pages/Portfolio.tsx?raw'

function render(seed?: unknown): string {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  if (seed) client.setQueryData(['capitalAdded'], seed)
  return renderToString(
    <QueryClientProvider client={client}>
      <AddMoneyCard />
    </QueryClientProvider>,
  )
}

describe('the add-money card', () => {
  it('says plainly that added money is never counted as profit', () => {
    const html = render()
    expect(html).toContain('Add practice money')
    expect(html).toContain('never counted as profit')
    expect(html).toContain('Add money')
  })

  it('lists the first funding and every top-up', () => {
    const html = render({
      starting_capital: 1000000,
      added: [{ at: '2026-10-26T12:00:00+00:00', amount: 4000000 }],
      total_added: 4000000,
    })
    expect(html).toContain('First funding')
    expect(html).toContain('10,00,000')
    expect(html).toContain('40,00,000')
  })

  it('is on the owner Portfolio pages only', () => {
    expect(portfolioSource).toMatch(/\{canManage && <AddMoneyCard \/>\}/)
    expect(portfolioNewSource).toMatch(/\{owner && <AddMoneyCard \/>\}/)
  })

  it('posts to the capital-added endpoint', () => {
    expect(clientSource).toMatch(/post<[^>]*>\('\/portfolio\/capital-added'/)
  })
})

describe('buy more on the Testing page', () => {
  it('uses the same tester buy as Opportunities, with the stock’s own cap tier', () => {
    expect(paperSource).toMatch(/api\.testerPaperBuy\(\{ symbol: p\.symbol, quantity: Number\(buyQty\), cap_tier: p\.cap_tier \?\? 'large' \}\)/)
    expect(paperSource).toContain('Buy more')
    expect(paperSource).toContain('Added as a separate lot')
  })
})
