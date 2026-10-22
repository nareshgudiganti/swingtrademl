import { renderToString } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { StockSearchView, pickIndex, stockUrl } from './StockSearch'

const RELIANCE = [{ tradingsymbol: 'RELIANCE', name: 'Reliance Industries' }]

describe('StockSearchView', () => {
  it('lists RELIANCE when typing RELI', () => {
    const html = renderToString(<StockSearchView query="RELI" results={RELIANCE} onQuery={() => {}} onPick={() => {}} />)
    expect(html).toContain('RELIANCE')
    expect(html).toContain('Reliance Industries')
    expect(html).toContain('Search a stock')
  })
  it('shows no list for an empty query', () => {
    const html = renderToString(<StockSearchView query="" results={RELIANCE} onQuery={() => {}} onPick={() => {}} />)
    expect(html).not.toContain('RELIANCE')
    expect(html).not.toContain('No stock found')
  })
  it('says no stock found when nothing matches', () => {
    const html = renderToString(<StockSearchView query="ZZZ" results={[]} onQuery={() => {}} onPick={() => {}} />)
    expect(html).toContain('No stock found')
  })
  it('does not say not-found while results are still loading', () => {
    const html = renderToString(<StockSearchView query="ZZ" results={[]} loading onQuery={() => {}} onPick={() => {}} />)
    expect(html).not.toContain('No stock found')
  })
})

describe('stockUrl / pickIndex', () => {
  it('builds the stock page url', () => {
    expect(stockUrl('RELIANCE')).toBe('/trademind/stock/RELIANCE')
    expect(stockUrl('M&M')).toBe('/trademind/stock/M%26M')
  })
  it('Enter picks the highlighted or first result', () => {
    expect(pickIndex(3, 0)).toBe(0)
    expect(pickIndex(3, 2)).toBe(2)
    expect(pickIndex(0, 0)).toBe(-1)
  })
})
