import { renderToString } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { TaxExportView } from './TaxExport'
import { TAX_NOTE, fyOf, taxPrintHtml, type RealTaxExport } from './taxRecords'

const data = (over: Partial<RealTaxExport> = {}): RealTaxExport => ({
  year: '2025-26',
  start: '2025-04-01',
  end: '2026-03-31',
  years: ['2026-27', '2025-26'],
  rows: [
    {
      stock: 'ABC', buy_date: '2025-04-07', sell_date: '2025-06-02', quantity: 10, buy_value: 1000,
      sell_value: 1200, charges: 2.5, gain: 197.5, days_held: 56, type: 'Short-term', buy_missing: false,
    },
    {
      stock: '<b>X</b>', buy_date: null, sell_date: '2025-07-01', quantity: 2, buy_value: null,
      sell_value: 400, charges: null, gain: null, days_held: null, type: null, buy_missing: true,
    },
  ],
  totals: {
    short_term: 197.5, long_term: 0, same_day: 0, charges: 2.5, buy_value: 1000, sell_value: 1200,
    sales: 1, missing_buy_count: 1,
  },
  charges_are_estimates: true,
  method: 'FIFO',
  notes: ['Sales are matched first in, first out.'],
  ...over,
})

const view = (d: RealTaxExport, year = d.year) =>
  renderToString(
    <TaxExportView data={d} year={year} onYear={() => {}} onDownload={() => {}} onPrint={() => {}} />,
  )

describe('fyOf', () => {
  it('starts the financial year on 1 April', () => {
    expect(fyOf(new Date(2026, 2, 31))).toBe('2025-26')
    expect(fyOf(new Date(2026, 3, 1))).toBe('2026-27')
    expect(fyOf(new Date(2099, 11, 1))).toBe('2099-00')
  })
})

describe('TaxExportView', () => {
  it('has a year picker, a download button and a printable-page button', () => {
    const html = view(data())
    expect(html).toContain('aria-label="Financial year"')
    expect(html).toContain('<option value="2026-27">')
    expect(html).toContain('Download for tax (spreadsheet)')
    expect(html).toContain('Printable page (save as PDF)')
  })

  it('shows the short-term and long-term totals and charges in plain words', () => {
    const html = view(data())
    expect(html).toContain('Short-term gain or loss after charges')
    expect(html).toContain('Long-term gain or loss after charges')
    expect(html).toContain('Estimated charges')
  })

  it('says sales with no buy on record are left out, and carries the tax note', () => {
    const html = view(data())
    expect(html.replace(/<!-- -->/g, '')).toContain('1 sale has no buy on record')
    expect(html).toContain("check against Zerodha&#x27;s Tax P&amp;L (Console) and ask a tax adviser")
  })

  it('keeps a chosen year in the picker even if it has no sales', () => {
    expect(view(data({ years: ['2025-26'] }), '2023-24')).toContain('<option value="2023-24" selected="">')
  })
})

describe('taxPrintHtml', () => {
  it('is a full page with totals, the note, and every row', () => {
    const html = taxPrintHtml(data())
    expect(html.startsWith('<!doctype html>')).toBe(true)
    expect(html).toContain('financial year 2025-26')
    expect(html).toContain(TAX_NOTE.replace('&', '&amp;'))
    expect(html).toContain('Buy details missing')
    expect(html).toContain('₹197.50')
  })

  it('escapes stock names so nothing in the data can run as code', () => {
    const html = taxPrintHtml(data())
    expect(html).not.toContain('<b>X</b>')
    expect(html).toContain('&lt;b&gt;X&lt;/b&gt;')
  })
})
