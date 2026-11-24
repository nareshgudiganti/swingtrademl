// Pure mapper from the app's stored daily candles to the shape the
// TradeMind chart (ui.tsx's <Candles>) draws. Kept out of live.ts because it
// belongs to one symbol's price history, not a brain run.

import type { Candle } from '../api/types'
import { istDay } from './istDay'
import type { CandleBar } from './types'

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

export function barsFrom(candles: Candle[]): CandleBar[] {
  return candles.map((c) => {
    // The India trading day of the bar (istDay.ts), the same in every browser time zone.
    const day = istDay(c.ts)
    return {
      t: `${Number(day.slice(8, 10))} ${MONTHS[Number(day.slice(5, 7)) - 1]}`,
      o: c.open,
      h: c.high,
      l: c.low,
      c: c.close,
      vol: c.volume ?? 0,
    }
  })
}
