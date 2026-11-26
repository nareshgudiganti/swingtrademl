// #281 D2: a never-priced position says "Price unavailable", with the time of the last known price when there is one.
import { describe, expect, it } from 'vitest'

import { PRICE_UNAVAILABLE, priceUnavailableText } from './priceUnavailable'

describe('priceUnavailableText', () => {
  it('is exactly "Price unavailable" when no time is known', () => {
    expect(PRICE_UNAVAILABLE).toBe('Price unavailable')
    expect(priceUnavailableText(null)).toBe('Price unavailable')
    expect(priceUnavailableText(undefined)).toBe('Price unavailable')
    expect(priceUnavailableText('not a date')).toBe('Price unavailable')
  })

  it('adds the last price time in IST, not UTC', () => {
    // 10:00 UTC is 15:30 IST the same day
    expect(priceUnavailableText('2026-11-25T10:00:00Z')).toBe('Price unavailable · last price 25 Nov 15:30 IST')
    // 20:00 UTC on 25 Nov is 01:30 IST on 26 Nov
    expect(priceUnavailableText('2026-11-25T20:00:00+00:00')).toBe('Price unavailable · last price 26 Nov 01:30 IST')
  })
})
