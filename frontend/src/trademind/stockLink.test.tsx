import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import type { BrainRun } from '../api/types'
import StockLink from './StockLink'

function render(node: React.ReactNode, run?: Partial<BrainRun>) {
  const qc = new QueryClient()
  if (run) qc.setQueryData(['brainLatest', 'nightly'], run)
  return renderToStaticMarkup(
    <QueryClientProvider client={qc}>
      <MemoryRouter>{node}</MemoryRouter>
    </QueryClientProvider>,
  )
}

const run = {
  decisions: [
    { symbol: 'INFY', kind: 'idea', confidence: 0.862 },
    { symbol: 'TCS', kind: 'holding', confidence: 0.4 },
  ],
} as unknown as Partial<BrainRun>

describe('StockLink', () => {
  it('opens the stock page and shows the model score beside the name', () => {
    const html = render(<StockLink symbol="INFY" />, run)
    expect(html).toContain('href="/trademind/stock/INFY"')
    expect(html).toContain('>INFY</a>')
    expect(html).toContain('class="tm-scorechip"')
    expect(html).toContain('>86<')
  })

  it('still links, with no score, when the run does not list the stock', () => {
    const html = render(<StockLink symbol="ZZZZ" />, run)
    expect(html).toContain('href="/trademind/stock/ZZZZ"')
    expect(html).not.toContain('tm-scorechip')
  })

  it('leaves out the score where the row has its own score column', () => {
    const html = render(<StockLink symbol="INFY" withScore={false} />, run)
    expect(html).toContain('href="/trademind/stock/INFY"')
    expect(html).not.toContain('tm-scorechip')
  })

  it('encodes odd symbols in the link', () => {
    expect(render(<StockLink symbol="M&M" />)).toContain('href="/trademind/stock/M%26M"')
  })
})
