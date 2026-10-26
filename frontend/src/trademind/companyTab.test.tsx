// The Company and news tab shows each block with its source and date, says "Not available" or "Out of date"
// instead of guessing, and never uses advice words. It is display only.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToString } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import type { CompanyView } from '../api/types'
import { CompanyTab, CompanyTeaser, shortDate } from './CompanyTab'

const view = (over: Partial<CompanyView> = {}): CompanyView => ({
  symbol: 'KEI',
  headline: "From the company's own filings: 39% below its 1-year high; founders and promoters hold 35%.",
  price_position: { state: 'ok', source: 'Our price history', as_of: '2026-10-23', text: '39% below its 1-year high' },
  ownership: {
    state: 'ok',
    source: 'NSE shareholding filing',
    as_of: '2026-09-30',
    text: 'Founders and promoters hold 35%; everyone else holds 65%',
  },
  announcements: {
    state: 'ok',
    source: 'NSE announcements',
    as_of: '2026-10-22',
    items: [
      {
        at: '2026-10-22T13:38:27Z',
        category: 'Investor Presentation',
        summary: 'Presentation filed',
        attachment_url: 'https://nsearchives.nseindia.com/x.pdf',
      },
    ],
  },
  results: { state: 'not_available', source: 'NSE results', as_of: null, why: 'Results are not collected yet.' },
  coming_soon: ['What outside experts say', 'News about the company'],
  note: "Information from the company's filings. It does not change the brain's call.",
  ...over,
})

function render(node: React.ReactNode, data?: CompanyView) {
  const client = new QueryClient()
  if (data) client.setQueryData(['company', 'KEI'], data)
  return renderToString(
    <QueryClientProvider client={client}>
      <MemoryRouter>{node}</MemoryRouter>
    </QueryClientProvider>,
  ).replace(/<!-- -->/g, '')
}

describe('Company and news tab', () => {
  it('shows every block with its source and date', () => {
    const html = render(<CompanyTab symbol="KEI" />, view())
    expect(html).toContain('data-testid="company-tab"')
    expect(html).toContain('NSE shareholding filing')
    expect(html).toContain('as of 30 Sep 2026')
    expect(html).toContain('as of 22 Oct 2026')
    expect(html).toContain('Open the filing')
    expect(html).toContain('does not change the brain')
    expect(html).toContain('Coming soon')
  })

  it('results say Not available, never a number', () => {
    const html = render(<CompanyTab symbol="KEI" />, view())
    expect(html).toContain('data-testid="company-results"')
    expect(html).toContain('Not available yet.')
    expect(html).toContain('Results are not collected yet.')
  })

  it('an old block is flagged Out of date', () => {
    const old = view({
      ownership: { state: 'out_of_date', source: 'NSE shareholding filing', as_of: '2026-03-31', text: 'Founders and promoters hold 35%; everyone else holds 65%' },
    })
    const html = render(<CompanyTab symbol="KEI" />, old)
    expect(html).toContain('Out of date')
  })

  it('with no data at all it says so instead of inventing a summary', () => {
    const empty = view({
      headline: null,
      price_position: { state: 'not_available', source: 'Our price history', as_of: null, text: null },
      ownership: { state: 'not_available', source: 'NSE shareholding filing', as_of: null, text: null },
      announcements: { state: 'not_available', source: 'NSE announcements', as_of: null, items: [] },
    })
    const html = render(<CompanyTab symbol="KEI" />, empty)
    expect(html).toContain('not enough filed information')
    expect(html).toContain('Not available')
  })

  it('uses no advice words', () => {
    const html = render(<CompanyTab symbol="KEI" />, view()).toLowerCase()
    for (const w of ['buy', 'sell', 'cheap', 'expensive', 'undervalued', 'overvalued']) {
      expect(html).not.toContain(w)
    }
  })

  it('the stock-page teaser links to the tab, and stays silent with nothing to say', () => {
    const shown = render(<CompanyTeaser symbol="KEI" to="/trademind/stock/KEI/analysis?tab=company" />, view())
    expect(shown).toContain('data-testid="company-teaser"')
    expect(shown).toContain('tab=company')
    const quiet = render(<CompanyTeaser symbol="KEI" to="/x" />, view({ headline: null }))
    expect(quiet).not.toContain('company-teaser')
  })

  it('dates are shown as given, not shifted by time zone', () => {
    expect(shortDate('2026-10-22')).toBe('22 Oct 2026')
    expect(shortDate(null)).toBe('')
  })
})
