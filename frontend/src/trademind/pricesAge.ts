// "Prices from ..." badge in the top bar: how old the app's latest daily prices are, counted in TRADING days
// (weekends and NSE holidays skipped), in plain words. Pure, so it can be tested without a browser.
//
// How old is "old"? The server's calendar (GET /market/session) sends the recent finished trading days, newest
// first. A day counts as finished from 15:40 IST. Each finished trading day after the latest price is one day of age:
//   - Monday morning showing Friday's close: no trading day has finished since Friday, so 0 days old.
//   - After 15:40 on a trading day, yesterday's close is 1 day old. Zerodha only publishes today's closing prices
//     overnight (see _expected_latest_trading_day in api/v1/endpoints/system.py), so that one day is normal and is
//     not shown in amber. Anything older than that is.

export type PricesAgeTone = 'fresh' | 'stale'

export interface PricesAge {
  tone: PricesAgeTone
  /** Trading days of age; null when there are no prices at all. */
  days: number | null
  /** The badge text, e.g. "Prices from yesterday's close" or "Prices are 2 days old". */
  label: string
  /** A shorter form for a phone, e.g. "Prices: 17 Oct" or "2 days old". */
  short: string
  /** One or two plain sentences for the tooltip / screen readers. */
  detail: string
}

export interface PricesAgeInput {
  /** The newest daily candle's date (YYYY-MM-DD, already an IST date), or null when there is none. */
  latestCandleDate: string | null
  /** Today's date in India (YYYY-MM-DD). */
  today: string
  /** Finished trading days, newest first. At least one entry (the last finished trading day). */
  recentClosedTradingDays: string[]
}

const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

function parts(iso: string): { y: number; m: number; d: number } {
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number)
  return { y: y!, m: m!, d: d! }
}

/** "Fri 17 Oct" */
export function dayLabel(iso: string): string {
  const { y, m, d } = parts(iso)
  return `${WEEKDAYS[new Date(Date.UTC(y, m - 1, d)).getUTCDay()]} ${d} ${MONTHS[m - 1]}`
}

/** "17 Oct" */
function shortDay(iso: string): string {
  const { m, d } = parts(iso)
  return `${d} ${MONTHS[m - 1]}`
}

function calendarYesterday(today: string): string {
  const { y, m, d } = parts(today)
  return new Date(Date.UTC(y, m - 1, d - 1)).toISOString().slice(0, 10)
}

/** "today's close" / "yesterday's close" / "the Fri 17 Oct close" */
function closeWords(day: string, today: string): string {
  if (day === today) return "today's close"
  if (day === calendarYesterday(today)) return "yesterday's close"
  return `the ${dayLabel(day)} close`
}

const DAILY =
  'The app works from each trading day’s closing prices, not live prices. Weekends and market holidays are not counted.'

export function pricesAge({ latestCandleDate, today, recentClosedTradingDays }: PricesAgeInput): PricesAge {
  if (!latestCandleDate) {
    return {
      tone: 'stale',
      days: null,
      label: 'No prices yet',
      short: 'No prices',
      detail: 'The app has not loaded any stock prices yet, so nothing on this page is based on real prices.',
    }
  }
  const candle = latestCandleDate.slice(0, 10)
  const days = recentClosedTradingDays.map((d) => d.slice(0, 10))
  // Finished trading days after the latest price. ISO dates compare correctly as strings.
  const newer = days.filter((d) => d > candle).length
  const olderThanList = days.length > 0 && candle < days[days.length - 1]!
  // Today's close only arrives overnight, so once today has finished one day of age is expected.
  const allowed = days[0] === today ? 1 : 0
  const from = closeWords(candle, today)

  if (newer === 0) {
    return {
      tone: 'fresh',
      days: 0,
      label: `Prices from ${from}`,
      short: `Prices: ${shortDay(candle)}`,
      detail: `Up to date: these are the latest closing prices (${dayLabel(candle)}). ${DAILY}`,
    }
  }
  if (newer <= allowed) {
    return {
      tone: 'fresh',
      days: newer,
      label: 'Prices are 1 day old',
      short: '1 day old',
      detail: `These are ${dayLabel(candle)}’s closing prices. Today’s closing prices usually arrive overnight, so this is normal in the evening. ${DAILY}`,
    }
  }
  if (olderThanList) {
    return {
      tone: 'stale',
      days: newer,
      label: `Prices last updated ${dayLabel(candle)}`,
      short: `Old: ${shortDay(candle)}`,
      detail: `Out of date: the latest prices are from ${dayLabel(candle)}, more than ${newer} trading days ago. Treat scores and ideas on this page with care until prices update.`,
    }
  }
  return {
    tone: 'stale',
    days: newer,
    label: `Prices are ${newer} days old`,
    short: `${newer} days old`,
    detail: `Out of date: the latest prices are from ${from}. They should update after every trading day, so treat scores and ideas on this page with care until they do. ${DAILY}`,
  }
}

/** Today's date in India (YYYY-MM-DD) — only used when an older server does not send `today`. */
export function istToday(now: Date): string {
  return new Date(now.getTime() + 330 * 60_000).toISOString().slice(0, 10)
}
