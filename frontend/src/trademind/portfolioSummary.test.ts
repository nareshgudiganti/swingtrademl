import { describe, expect, it } from 'vitest'
import { portfolioSummary } from './trackerRules'
import type { WatchTrackerItem } from '../api/types'

const item = (o: Partial<WatchTrackerItem>) => o as WatchTrackerItem

describe('portfolioSummary', () => {
  it('adds up invested, total and 1-day returns, leaving out stocks without shares', () => {
    const s = portfolioSummary([
      item({ invested: 1000, profit_amount: 100, last_price: 110, today_pct: 10, quantity: 10 }),
      item({ invested: null, profit_amount: null, last_price: 50, today_pct: 1, quantity: null }),
    ])!
    expect(s.counted).toBe(1)
    expect(s.invested).toBe(1000)
    expect(s.totalReturn).toBe(100)
    expect(s.totalReturnPct).toBeCloseTo(10)
    expect(s.dayReturn).toBeCloseTo(100) // 10 shares x (110 - 100)
    expect(s.dayReturnPct).toBeCloseTo(10)
  })
  it('is null when nothing has shares and a price paid', () => {
    expect(portfolioSummary([item({ invested: null, profit_amount: null })])).toBeNull()
  })
})
