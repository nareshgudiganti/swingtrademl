// "21 Nov": the India trading day of a stored daily candle, for the stock page's last-close label (#486).
// A daily candle is stamped at India midnight (18:30 UTC the day before), so the UTC date is a day early and the
// browser's own zone is wrong outside India. India has no daylight saving: the day is the instant plus 5h 30m, read as UTC.

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

export function closeDateText(ts: string | undefined | null): string | null {
  if (!ts) return null
  const bare = /^\d{4}-\d{2}-\d{2}$/.test(ts)
  const instant = new Date(bare ? `${ts}T00:00:00Z` : /(Z|[+-]\d{2}:?\d{2})$/i.test(ts) ? ts : `${ts}Z`)
  if (Number.isNaN(instant.getTime())) return null
  const day = bare ? instant : new Date(instant.getTime() + 330 * 60_000)
  return `${day.getUTCDate()} ${MONTHS[day.getUTCMonth()]}`
}
