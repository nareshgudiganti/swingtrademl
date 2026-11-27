// What a position nobody has priced yet says (#281 D2). Never a 0% or the entry price standing in for a live price.
export const PRICE_UNAVAILABLE = 'Price unavailable'

/** "Price unavailable", plus "· last price 25 Nov 15:30 IST" when the server knows when a price was last taken. */
export function priceUnavailableText(asOf?: string | null): string {
  if (!asOf) return PRICE_UNAVAILABLE
  const d = new Date(asOf)
  if (Number.isNaN(d.getTime())) return PRICE_UNAVAILABLE
  const parts = new Intl.DateTimeFormat('en-GB', {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    timeZone: 'Asia/Kolkata',
  }).formatToParts(d)
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? ''
  return `${PRICE_UNAVAILABLE} · last price ${get('day')} ${get('month')} ${get('hour')}:${get('minute')} IST`
}
