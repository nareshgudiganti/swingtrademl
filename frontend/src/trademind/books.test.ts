import { describe, expect, it } from 'vitest'

import { bookOf } from './books'

describe('which money book a Portfolio screen shows', () => {
  it.each([
    ['/trademind/positions', 'paper', 'Bot (Paper)'],
    ['/trademind/positions/INFY', 'paper', 'Bot (Paper)'],
    ['/trademind/testing', 'paper', 'Testing (Paper)'],
    ['/trademind/holdings', 'real', 'My Zerodha (Real)'],
    ['/trademind/portfolio', 'paper', 'Paper Overview'],
  ])('%s is %s money (%s)', (path, kind, name) => {
    const b = bookOf(path)
    expect(b?.kind).toBe(kind)
    expect(b?.name).toBe(name)
  })

  it('says nothing on screens outside Portfolio', () => {
    for (const p of ['/trademind', '/trademind/dashboard', '/trademind/opportunities', '/trademind/control', '/trademind/records']) {
      expect(bookOf(p)).toBeUndefined()
    }
  })

  it('the Paper Overview note says real holdings and testing trades are not in it', () => {
    expect(bookOf('/trademind/portfolio')?.note).toMatch(/real/i)
    expect(bookOf('/trademind/portfolio')?.note).toMatch(/testing/i)
  })
})
