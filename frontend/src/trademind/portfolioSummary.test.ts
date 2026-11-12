import { describe, expect, it } from 'vitest'
import { portfolioSummary, soldSummary } from './trackerRules'
import type { SoldRecord, WatchTrackerItem } from '../api/types'

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

describe('soldSummary', () => {
  const sale = (o: Partial<SoldRecord>) => o as SoldRecord
  it('adds up realized profit, counts wins, and leaves out sales without shares from the rupee totals', () => {
    const s = soldSummary([
      sale({ invested: 1000, profit_amount: 80, result: 'win' }),
      sale({ invested: 1000, profit_amount: -60, result: 'loss' }),
      sale({ invested: null, profit_amount: null, result: 'win' }),
    ])
    expect(s.invested).toBe(2000)
    expect(s.profit).toBe(20)
    expect(s.profitPct).toBeCloseTo(1)
    expect([s.wins, s.decided, s.withoutShares]).toEqual([2, 3, 1])
  })

  it('counts sales and stocks, averages the days held, and ranks only sales that have rupees', () => {
    const s = soldSummary([
      sale({ symbol: 'CUB', days_held: 5, profit_amount: 80 }),
      sale({ symbol: 'KEC', days_held: 3, profit_amount: -60 }),
      sale({ symbol: 'CUB', days_held: 13, profit_amount: null }),
    ])
    expect([s.count, s.stocks]).toEqual([3, 2])
    expect(s.avgDays).toBe(7)
    expect(s.longest).toEqual({ symbol: 'CUB', days: 13 })
    expect(s.best).toEqual({ symbol: 'CUB', profit: 80 })
    expect(s.worst).toEqual({ symbol: 'KEC', profit: -60 })
  })

  it('has no averages for no sales, and no "worst" when only one sale can be ranked', () => {
    expect(soldSummary([]).avgDays).toBeNull()
    const one = soldSummary([sale({ symbol: 'CUB', days_held: 5, profit_amount: 80 })])
    expect(one.best).toEqual({ symbol: 'CUB', profit: 80 })
    expect(one.worst).toBeNull()
  })
})
