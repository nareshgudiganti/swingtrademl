// #281 D2: a never-priced position says "Price unavailable" (with the last price time when known),
// shows no percent or P&L, and never the entry price as if it were live.
import { renderToString } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import type { DetailedPosition } from '../api/types'
import PositionAttentionCard, { detailForPosition } from '../components/PositionAttentionCard'
import { hasPrice, priceText, returnText } from './pages/PositionParts'

const unpriced = (over: Partial<DetailedPosition> = {}) =>
  ({
    id: 1,
    symbol: 'NP281',
    quantity: 10,
    entry_price: 100,
    current_price: null,
    has_price: false,
    price_status: 'none',
    price_as_of: null,
    invested: 1000,
    current_value: 1000,
    unrealized_pnl: null,
    unrealized_pnl_pct: null,
    day_pnl: null,
    stop_loss: 96,
    take_profit: 108,
    action_code: 'hold',
    action_label: 'Holding',
    entry_confidence: null,
    last_confidence: null,
    ...over,
  }) as unknown as DetailedPosition

describe('a never-priced position (#281 D2)', () => {
  it('is not priced, and reads "Price unavailable" everywhere the helpers are used', () => {
    expect(hasPrice(unpriced())).toBe(false)
    expect(returnText(unpriced())).toBe('Price unavailable')
    expect(priceText(unpriced())).toBe('Price unavailable')
    expect(priceText(unpriced({ price_as_of: '2026-11-25T10:00:00Z' }))).toBe(
      'Price unavailable · last price 25 Nov 15:30 IST',
    )
  })

  it('the attention card shows "Price unavailable", no percent, no entry price as the current price', () => {
    const html = renderToString(<PositionAttentionCard position={unpriced({ price_as_of: '2026-11-25T10:00:00Z' })} book="bot" onOpen={() => {}} />)
    expect(html).toContain('Price unavailable · last price 25 Nov 15:30 IST')
    expect(html).not.toContain('No price yet')
    expect(html).not.toMatch(/0\.0%/)
    expect(html).not.toMatch(/NaN/)
  })

  it('the pop-up payload carries a null price and the time', () => {
    expect(detailForPosition(unpriced({ price_as_of: '2026-11-25T10:00:00Z' }))).toMatchObject({
      price: null,
      priceAsOf: '2026-11-25T10:00:00Z',
    })
  })

  it('a priced position is unchanged', () => {
    const priced = unpriced({ has_price: true, current_price: 103, unrealized_pnl: 30, unrealized_pnl_pct: 0.03, price_status: 'ok' })
    expect(hasPrice(priced)).toBe(true)
    expect(returnText(priced)).toBe('+3.0%')
    expect(priceText(priced)).toBe('₹103.00')
  })
})
