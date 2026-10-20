// Tax records export for the real Zerodha account (My Holdings > Real-money report).
// The backend does the matching and the CSV; this file only holds the shapes and
// the print-friendly page (the browser's "Save as PDF" turns it into a PDF).

export interface RealTaxRow {
  stock: string
  buy_date: string | null
  sell_date: string
  quantity: number
  buy_value: number | null
  sell_value: number
  charges: number | null
  gain: number | null
  days_held: number | null
  type: 'Short-term' | 'Long-term' | 'Same day (intraday)' | null
  buy_missing: boolean
}

export interface RealTaxExport {
  year: string
  start: string
  end: string
  years: string[]
  rows: RealTaxRow[]
  totals: {
    short_term: number
    long_term: number
    same_day: number
    charges: number
    buy_value: number
    sell_value: number
    sales: number
    missing_buy_count: number
  }
  charges_are_estimates: boolean
  method: string
  notes: string[]
}

export const TAX_NOTE = "For your records — check against Zerodha's Tax P&L (Console) and ask a tax adviser."

/** The financial year (1 April to 31 March) a date falls in, written "2025-26". */
export function fyOf(d: Date): string {
  const start = d.getMonth() >= 3 ? d.getFullYear() : d.getFullYear() - 1
  return `${start}-${String((start + 1) % 100).padStart(2, '0')}`
}

const esc = (s: string) =>
  s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')

const money = (n: number | null) =>
  n === null ? '' : `${n < 0 ? '−' : ''}₹${Math.abs(n).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

/** A self-contained page the owner can print or save as PDF. Every value is escaped. */
export function taxPrintHtml(data: RealTaxExport): string {
  const t = data.totals
  const rows = data.rows
    .map(
      (r) => `<tr${r.buy_missing ? ' class="missing"' : ''}>
<td>${esc(r.stock)}</td><td>${r.buy_date ?? ''}</td><td>${r.sell_date}</td><td class="n">${r.quantity}</td>
<td class="n">${money(r.buy_value)}</td><td class="n">${money(r.sell_value)}</td><td class="n">${money(r.charges)}</td>
<td class="n">${money(r.gain)}</td><td class="n">${r.days_held ?? ''}</td><td>${esc(r.type ?? '')}</td>
<td>${r.buy_missing ? 'Buy details missing — not in the totals' : ''}</td></tr>`,
    )
    .join('\n')
  return `<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Real trades for tax ${esc(data.year)}</title>
<style>
body{font:13px/1.4 system-ui,sans-serif;color:#111;background:#fff;margin:24px}
h1{font-size:18px;margin:0 0 4px}p{margin:4px 0}
table{border-collapse:collapse;width:100%;margin:12px 0}
th,td{border:1px solid #bbb;padding:4px 6px;text-align:left;vertical-align:top}
th{background:#eee}.n{text-align:right;white-space:nowrap}.missing td{background:#fff4d6}
.note{border:1px solid #c80;background:#fff8e6;padding:8px;margin:8px 0}
@media print{body{margin:8mm}button{display:none}}
</style></head><body>
<h1>Real trades for tax — financial year ${esc(data.year)}</h1>
<p>1 April ${data.start.slice(0, 4)} to 31 March ${data.end.slice(0, 4)}. Your real Zerodha account only (no practice trades).</p>
<p class="note"><strong>${esc(TAX_NOTE)}</strong></p>
<table><tbody>
<tr><th>Short-term gain or loss after charges</th><td class="n">${money(t.short_term)}</td></tr>
<tr><th>Long-term gain or loss after charges</th><td class="n">${money(t.long_term)}</td></tr>
<tr><th>Same-day (intraday) gain or loss after charges</th><td class="n">${money(t.same_day)}</td></tr>
<tr><th>Total estimated charges</th><td class="n">${money(t.charges)}</td></tr>
<tr><th>Sales counted</th><td class="n">${t.sales}</td></tr>
<tr><th>Sales with buy details missing (not counted)</th><td class="n">${t.missing_buy_count}</td></tr>
</tbody></table>
<table><thead><tr><th>Stock</th><th>Bought on</th><th>Sold on</th><th>Shares</th><th>Buy value</th><th>Sell value</th>
<th>Estimated charges</th><th>Gain or loss after charges</th><th>Days held</th><th>Short-term or long-term</th><th>Note</th></tr></thead>
<tbody>
${rows || '<tr><td colspan="11">No sales in this financial year.</td></tr>'}
</tbody></table>
${data.notes.map((n) => `<p>${esc(n)}</p>`).join('\n')}
<p><button onclick="window.print()">Print or save as PDF</button></p>
</body></html>`
}
