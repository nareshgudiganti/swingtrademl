// Indian-locale formatting. Rupee amounts use the lakh/crore digit grouping
// (12,34,567) that `en-IN` provides, which is what an Indian user expects.

const inr = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  maximumFractionDigits: 2,
})

const inrCompact = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  notation: 'compact',
  maximumFractionDigits: 2,
})

export const formatCurrency = (value: number): string => inr.format(value)

export const formatCompact = (value: number): string => inrCompact.format(value)

export const formatPercent = (value: number, digits = 2): string =>
  `${(value * 100).toFixed(digits)}%`

export const formatSignedPercent = (value: number, digits = 2): string =>
  `${value >= 0 ? '+' : ''}${(value * 100).toFixed(digits)}%`

export const formatNumber = (value: number): string =>
  new Intl.NumberFormat('en-IN').format(value)

export const formatDate = (iso: string): string =>
  new Date(iso).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })

export const formatDateTime = (iso: string): string =>
  new Date(iso).toLocaleString('en-IN', {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })

/** Tailwind-free colour class for a P&L value. */
export const pnlClass = (value: number): string =>
  value > 0 ? 'pos' : value < 0 ? 'neg' : 'flat'
