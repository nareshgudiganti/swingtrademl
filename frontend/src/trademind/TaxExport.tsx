import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { api } from '../api/client'
import { QueryNotice } from './PageState'
import { TAX_NOTE, fyOf, taxPrintHtml, type RealTaxExport } from './taxRecords'
import { Card, inr, toneClass } from './ui'

const signedRupees = (n: number) => `${n > 0 ? '+' : n < 0 ? '−' : ''}₹${inr(Math.abs(n))}`

export function TaxExportView({
  data,
  year,
  onYear,
  onDownload,
  onPrint,
  busy = false,
  error = null,
}: {
  data: RealTaxExport
  year: string
  onYear: (y: string) => void
  onDownload: () => void
  onPrint: () => void
  busy?: boolean
  error?: string | null
}) {
  const t = data.totals
  const years = data.years.includes(year) ? data.years : [year, ...data.years]
  return (
    <div data-testid="tax-export">
      <p className="tm-dim" style={{ marginTop: 0 }}>
        Every share you sold in one financial year (1 April to 31 March), with buy and sell values, charges and
        whether it was short-term (held 12 months or less) or long-term (more than 12 months).
      </p>
      <div className="tm-flex tm-wrap" style={{ gap: '0.5rem', alignItems: 'center', marginBottom: '0.6rem' }}>
        <label className="tm-flex" style={{ gap: '0.4rem', alignItems: 'center' }}>
          <span className="tm-dim">Financial year</span>
          <select
            className="tm-select"
            aria-label="Financial year"
            data-testid="tax-year"
            value={year}
            onChange={(e) => onYear(e.target.value)}
          >
            {years.map((y) => (
              <option key={y} value={y}>
                {y}
              </option>
            ))}
          </select>
        </label>
        <button className="tm-btn" onClick={onDownload} disabled={busy} data-testid="tax-download">
          {busy ? 'Preparing…' : 'Download for tax (spreadsheet)'}
        </button>
        <button className="tm-btn tm-btn-ghost" onClick={onPrint} data-testid="tax-print">
          Printable page (save as PDF)
        </button>
      </div>
      {error && <p className="tm-neg">{error}</p>}
      <div className="tm-rows">
        <div className="tm-row">
          <span className="tm-dim">Short-term gain or loss after charges</span>
          <span className={`tm-strong ${toneClass(t.short_term)}`}>{signedRupees(t.short_term)}</span>
        </div>
        <div className="tm-row">
          <span className="tm-dim">Long-term gain or loss after charges</span>
          <span className={`tm-strong ${toneClass(t.long_term)}`}>{signedRupees(t.long_term)}</span>
        </div>
        {t.same_day !== 0 && (
          <div className="tm-row">
            <span className="tm-dim">Bought and sold the same day (intraday)</span>
            <span className={`tm-strong ${toneClass(t.same_day)}`}>{signedRupees(t.same_day)}</span>
          </div>
        )}
        <div className="tm-row">
          <span className="tm-dim">Estimated charges</span>
          <span className="tm-strong">₹{inr(t.charges)}</span>
        </div>
        <div className="tm-row">
          <span className="tm-dim">Sales counted</span>
          <span className="tm-strong">{t.sales}</span>
        </div>
      </div>
      {t.missing_buy_count > 0 && (
        <p className="tm-warn">
          {t.missing_buy_count} sale{t.missing_buy_count === 1 ? ' has' : 's have'} no buy on record. They are listed
          as “Buy details missing” and left out of the totals. Importing your Zerodha tradebook fixes this.
        </p>
      )}
      <p className="tm-callout">{TAX_NOTE}</p>
      <p className="tm-dim" style={{ fontSize: '0.8rem' }}>
        Sales are matched to your oldest shares first (first in, first out). Charges are estimated with the app’s
        cost model, not taken from your contract notes. This does not work out any tax.
      </p>
    </div>
  )
}

export default function TaxExportCard() {
  const [year, setYear] = useState(() => fyOf(new Date()))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const tax = useQuery({
    queryKey: ['realTax', year],
    queryFn: () => api.realTax(year),
    retry: false,
    placeholderData: (previous) => previous,
  })

  async function download() {
    setBusy(true)
    setError(null)
    try {
      const text = await api.realTaxCsv(year)
      const url = URL.createObjectURL(new Blob([text], { type: 'text/csv;charset=utf-8' }))
      const a = document.createElement('a')
      a.href = url
      a.download = `real-trades-tax-${year}.csv`
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      setError(`Could not download: ${(e as Error).message}`)
    } finally {
      setBusy(false)
    }
  }

  function print() {
    if (!tax.data) return
    const w = window.open('', '_blank')
    if (!w) {
      setError('Your browser blocked the new tab. Allow pop-ups for this site and try again.')
      return
    }
    w.document.write(taxPrintHtml(tax.data))
    w.document.close()
  }

  return (
    <Card title="For your tax records" sub="Real Zerodha account only. Read-only.">
      {tax.data === undefined ? (
        <QueryNotice q={tax} what="your tax records" />
      ) : (
        <TaxExportView
          data={tax.data}
          year={year}
          onYear={setYear}
          onDownload={download}
          onPrint={print}
          busy={busy}
          error={error}
        />
      )}
    </Card>
  )
}
