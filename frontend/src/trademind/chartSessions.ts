// Missing-day markers for the line and area charts (#240).
//
// A chart marks a day only when it was an EXPECTED trading session (a weekday that is not an NSE holiday, the list
// comes from the server: trademind/tradingRules.ts) and no stored daily price exists for it. Weekends and holidays are
// never marked, and nothing is drawn or invented for the marked day. Only days between the first and last price on the
// chart are checked: how old the newest price is has its own label (PricesBadge).

import type { Candle } from '../api/types'
import { istDay, istMonthDay } from './istDay'
import { holidays } from './tradingRules'

/** A chart point. A point with `missing: true` has no price: it is the marker for a trading day with none on file. */
export type SessionPoint = { t: string; v: number | null; missing?: boolean }

const iso = (d: Date) => d.toISOString().slice(0, 10)

/** The expected trading sessions strictly between two India dates (YYYY-MM-DD): weekdays that are not holidays. */
export function expectedSessionsBetween(first: string, last: string, holidayList: readonly string[]): string[] {
  const out: string[] = []
  const d = new Date(`${first}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() + 1)
  for (let guard = 0; guard < 800 && iso(d) < last; guard += 1) {
    const dow = d.getUTCDay()
    if (dow !== 0 && dow !== 6 && !holidayList.includes(iso(d))) out.push(iso(d))
    d.setUTCDate(d.getUTCDate() + 1)
  }
  return out
}

/** The server's holiday list, or null when it is not loaded (then no day can be called "expected", so none is marked). */
function loadedHolidays(): readonly string[] | null {
  try {
    return holidays()
  } catch {
    return null
  }
}

/** Candles (oldest first) as chart points labelled with their India trading day, with a marker point for every
 *  expected trading session that has no candle. `holidayList` is injectable for tests. */
export function candlePoints(
  candles: readonly Candle[],
  holidayList: readonly string[] | null = loadedHolidays(),
): SessionPoint[] {
  const out: SessionPoint[] = []
  let prevDay: string | null = null
  for (const c of candles) {
    const day = istDay(c.ts)
    if (holidayList && prevDay && day > prevDay) {
      for (const m of expectedSessionsBetween(prevDay, day, holidayList)) {
        out.push({ t: `${m.slice(5, 10)}`, v: null, missing: true })
      }
    }
    out.push({ t: istMonthDay(c.ts), v: c.close })
    prevDay = day
  }
  return out
}

export const MISSING_DAY_NOTE = 'A dotted line marks a trading day with no price on file.'
