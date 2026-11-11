import { describe, expect, it } from 'vitest'

import { allocationBySector, allocationByStock, closedSummary } from './portfolioViews'

const held = [
  { symbol: 'AAA', sector: 'Banks', current_value: 600 },
  { symbol: 'BBB', sector: 'Banks', current_value: 200 },
  { symbol: 'CCC', sector: null, current_value: 200 },
]

describe('allocation rings', () => {
  it('splits the money by stock, biggest first, adding to 100%', () => {
    const s = allocationByStock(held)
    expect(s.map((x) => x.name)).toEqual(['AAA', 'BBB', 'CCC'])
    expect(s[0]?.pct).toBeCloseTo(60)
    expect(s.reduce((t, x) => t + x.pct, 0)).toBeCloseTo(100)
  })

  it('groups by sector and names a missing sector Unclassified', () => {
    const s = allocationBySector(held)
    expect(s.map((x) => [x.name, Math.round(x.pct)])).toEqual([
      ['Banks', 80],
      ['Unclassified', 20],
    ])
  })

  it('folds the long tail into Others', () => {
    const many = Array.from({ length: 12 }, (_, i) => ({ symbol: `S${i}`, current_value: 100 - i }))
    const s = allocationByStock(many, 5)
    expect(s).toHaveLength(5)
    expect(s[4]?.name).toBe('Others')
    expect(s.reduce((t, x) => t + x.pct, 0)).toBeCloseTo(100)
  })

  it('returns nothing for an empty or zero-value book', () => {
    expect(allocationByStock([])).toEqual([])
    expect(allocationBySector([{ symbol: 'X', current_value: 0 }])).toEqual([])
  })
})

describe('closed trades scoreboard', () => {
  const t = (symbol: string, net_pnl: number) => ({ symbol, net_pnl, is_win: net_pnl > 0, quantity: 1, entry_price: 100 })

  it('counts wins, losses, win rate and net profit', () => {
    const s = closedSummary([t('A', 500), t('B', -200), t('C', 300), t('D', -100)])
    expect(s).toMatchObject({ count: 4, wins: 2, losses: 2, winRate: 50, net: 500 })
    expect(s.avgWin).toBe(400)
    expect(s.avgLoss).toBe(-150)
    expect(s.best).toEqual({ symbol: 'A', net: 500 })
    expect(s.worst).toEqual({ symbol: 'B', net: -200 })
  })

  it('says "no data" rather than 0% when nothing has closed', () => {
    const s = closedSummary([])
    expect(s.count).toBe(0)
    expect(s.winRate).toBeNull()
    expect(s.best).toBeNull()
    expect(s.worst).toBeNull()
  })

  it('has no separate worst trade when only one has closed', () => {
    expect(closedSummary([t('A', 100)]).worst).toBeNull()
  })
})
