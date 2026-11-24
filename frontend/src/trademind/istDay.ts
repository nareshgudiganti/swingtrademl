// The India trading day of a stored daily candle (#470).
//
// Daily candles are stamped at India midnight, which is 18:30 UTC the day before: the UTC date (the first ten
// characters of the string) is a day early, and reading the date with the browser's own time zone is wrong
// anywhere outside India. India has no daylight saving, so the day is the instant plus 5 hours 30 minutes, read as UTC.

const IST_OFFSET_MINUTES = 330

/** "2026-11-30" for the bar stamped 2026-11-29T18:30:00Z. A bare YYYY-MM-DD is already an India date; a timestamp with
 *  no zone is read as UTC (the API always sends one). Anything unreadable falls back to its first ten characters. */
export function istDay(ts: string): string {
  if (/^\d{4}-\d{2}-\d{2}$/.test(ts)) return ts
  // "YYYY-MM-DD HH:MM:SS" (a space, not a T) is not valid ISO and some browsers refuse it: make it the T form first.
  const iso = ts.replace(/^(\d{4}-\d{2}-\d{2}) (?=\d)/, '$1T')
  const zoned = /(Z|[+-]\d{2}:?\d{2})$/i.test(iso) ? iso : `${iso}Z`
  const instant = new Date(zoned)
  if (Number.isNaN(instant.getTime())) return ts.slice(0, 10)
  return new Date(instant.getTime() + IST_OFFSET_MINUTES * 60_000).toISOString().slice(0, 10)
}

/** "30 Nov 2026": the India trading day of a candle, printed the way the classic screens print dates. The day is worked
 *  out first and then formatted as a plain calendar date, so the browser's own time zone cannot move it. */
export const formatIstDate = (ts: string): string =>
  new Date(`${istDay(ts)}T00:00:00Z`).toLocaleDateString('en-IN', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC',
  })

/** "11-30": the chart label used by the line charts (month and day of the India trading day). */
export const istMonthDay = (ts: string): string => istDay(ts).slice(5, 10)
