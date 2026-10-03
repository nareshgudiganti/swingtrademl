// Pure mapper from the app's stored daily candles to the shape the
// TradeMind chart (ui.tsx's <Candles>) draws. Kept out of live.ts because it
// belongs to one symbol's price history, not a brain run.

import type { Candle } from '../api/types'
import type { CandleBar } from './types'

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

export function barsFrom(candles: Candle[]): CandleBar[] {
  return candles.map((c) => {
    const d = new Date(c.ts)
    return { t: `${d.getDate()} ${MONTHS[d.getMonth()]}`, o: c.open, h: c.high, l: c.low, c: c.close, vol: c.volume ?? 0 }
  })
}
