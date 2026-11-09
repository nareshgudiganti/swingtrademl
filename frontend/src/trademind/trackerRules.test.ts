import { describe, expect, it } from 'vitest'

import type { WatchTrackerItem } from '../api/types'
import {
  barPosition,
  buildPatch,
  deltaView,
  filterItems,
  fmtMoney,
  fmtPct,
  fmtPrice,
  fmtRupees,
  formFromItem,
  needsActionCount,
  parseBuyPrice,
  parseQuantity,
  todayIst,
  pips,
  scoreText,
  sortItems,
  stopTarget,
  whatToDo,
} from './trackerRules'

const item = (symbol: string, state: WatchTrackerItem['state'], over: Partial<WatchTrackerItem> = {}): WatchTrackerItem => ({
  symbol, name: null, added_at: '2026-11-01T00:00:00Z', note: null, buy_price: null, bought_on: '2026-11-02', quantity: null,
  invested: null, profit_amount: null, entry_price: 100, entry_source: 'added_close',
  last_price: 103, return_pct: 3, today_pct: 0.5, days_done: 4, score_today: 80, score_prev: 78, score_delta: 2, score_first: 75,
  scores: [], closes: [], state, ...over,
})

describe('tracker rules', () => {
  it('formats numbers and never shows NaN', () => {
    expect(fmtPct(3.24)).toBe('+3.2%')
    expect(fmtPct(-1)).toBe('−1.0%')
    expect(fmtPct(-0.001, 1)).toBe('0.0%')
    expect(fmtPct(null)).toBe('—')
    expect(fmtPct(Number.NaN)).toBe('—')
    expect(fmtPrice(4210)).toBe('₹4,210')
    expect(fmtPrice(182.4)).toBe('₹182.4')
    expect(fmtPrice(null)).toBe('—')
    expect(scoreText(null)).toBe('—')
    expect(scoreText(84.4)).toBe('84')
  })

  it('stop and target prices only when the entry is known', () => {
    expect(stopTarget(1000)).toEqual({ stop: 960, target: 1080 })
    expect(stopTarget(null)).toBeNull()
    expect(stopTarget(0)).toBeNull()
  })

  it('bar position is clamped between -6% and +10%', () => {
    expect(barPosition(-6)).toBe(0)
    expect(barPosition(-50)).toBe(0)
    expect(barPosition(10)).toBe(100)
    expect(barPosition(99)).toBe(100)
    expect(barPosition(2)).toBe(50)
    expect(barPosition(null)).toBeNull()
  })

  it('score change shows an arrow and the size', () => {
    expect(deltaView(3)).toEqual({ arrow: '▲', text: '3', tone: 'pos' })
    expect(deltaView(-2.4)).toEqual({ arrow: '▼', text: '2', tone: 'neg' })
    expect(deltaView(0).arrow).toBe('–')
    expect(deltaView(null).text).toBe('—')
  })

  it('dots: one per day of the plan, last three late', () => {
    const p = pips(2, 15)
    expect(p).toHaveLength(15)
    expect(p.filter((x) => x.filled)).toHaveLength(2)
    expect(p.filter((x) => x.late)).toHaveLength(3)
    expect(pips(99, 15).every((x) => x.filled)).toBe(true)
  })

  it('filters, counts and sorts by urgency using the server state', () => {
    const items = [item('A', 'ok'), item('B', 'weak'), item('C', 'stop'), item('D', 'target', { days_done: 9 }), item('E', 'ok', { days_done: 9 })]
    expect(needsActionCount(items)).toBe(3)
    expect(needsActionCount(undefined)).toBe(0)
    expect(filterItems(items, 'act').map((i) => i.symbol)).toEqual(['B', 'C', 'D'])
    expect(filterItems(items, 'stop').map((i) => i.symbol)).toEqual(['C'])
    expect(filterItems(items, 'all')).toHaveLength(5)
    expect(sortItems(items).map((i) => i.symbol)).toEqual(['C', 'D', 'B', 'E', 'A'])
  })

  it('what to do is plain English for each state and survives nulls', () => {
    expect(whatToDo(item('KEI', 'stop', { return_pct: -3.5 }), 15)).toMatch(/−3.5% since you added it.*sell in Groww/)
    expect(whatToDo(item('KEI', 'target', { return_pct: 6 }), 15)).toMatch(/\+6.0%.*sell half at \+5%/)
    expect(whatToDo(item('KEI', 'time', { days_done: 13 }), 15)).toMatch(/Day 13 of 15/)
    expect(whatToDo(item('KEI', 'weak', { score_first: 78, score_today: 54 }), 15)).toMatch(/fell from 78 to 54/)
    expect(whatToDo(item('KEI', 'ok', { days_done: 3 }), 15)).toMatch(/12 trading days remain/)
    expect(whatToDo(item('KEI', 'ok', { return_pct: null, score_today: null }), 15)).not.toMatch(/NaN|null/)
  })

  it('parses the buy price box', () => {
    expect(parseBuyPrice('4,210')).toBe(4210)
    expect(parseBuyPrice('₹182.4')).toBe(182.4)
    expect(parseBuyPrice('  ')).toBeNull()
    expect(parseBuyPrice('abc')).toBeUndefined()
    expect(parseBuyPrice('-5')).toBeUndefined()
    expect(parseBuyPrice('0')).toBeUndefined()
  })
})

describe('edit form helpers', () => {
  const base = item('KEI', 'ok', { bought_on: '2026-11-02', buy_price: 4210, quantity: null, note: null })

  it('parses shares: empty clears, positive numbers pass, junk is refused', () => {
    expect(parseQuantity('')).toBeNull()
    expect(parseQuantity(' 1,250 ')).toBe(1250)
    expect(parseQuantity('2.5')).toBe(2.5)
    expect(parseQuantity('0')).toBeUndefined()
    expect(parseQuantity('-3')).toBeUndefined()
    expect(parseQuantity('abc')).toBeUndefined()
  })

  it('formats rupees with a real minus and a dash for unknown', () => {
    expect(fmtMoney(1250.4)).toBe('+₹1,250')
    expect(fmtMoney(-300)).toBe('−₹300')
    expect(fmtMoney(0)).toBe('₹0')
    expect(fmtMoney(null)).toBe('—')
    expect(fmtRupees(42100)).toBe('₹42,100')
    expect(fmtRupees(undefined)).toBe('—')
  })

  it('today in India does not slip a day for late-evening UTC', () => {
    expect(todayIst(new Date('2026-11-09T20:00:00Z'))).toBe('2026-11-10')
    expect(todayIst(new Date('2026-11-09T10:00:00Z'))).toBe('2026-11-09')
  })

  it('sends only what changed', () => {
    const f = formFromItem(base)
    expect(buildPatch(base, f, '2026-11-09')).toEqual({ patch: {}, errors: {}, changed: false })
    const r = buildPatch(base, { ...f, quantity: '10', note: ' hi ' }, '2026-11-09')
    expect(r.patch).toEqual({ quantity: 10, note: 'hi' })
    expect(r.changed).toBe(true)
    expect(buildPatch(base, { ...f, price: '' }, '2026-11-09').patch).toEqual({ buy_price: null })
  })

  it('refuses a future date, a date over 120 days back, a bad price and bad shares in plain words', () => {
    const f = formFromItem(base)
    expect(buildPatch(base, { ...f, boughtOn: '2026-11-10' }, '2026-11-09').errors.boughtOn).toMatch(/future/)
    expect(buildPatch(base, { ...f, boughtOn: '2026-07-01' }, '2026-11-09').errors.boughtOn).toMatch(/120 days/)
    expect(buildPatch(base, { ...f, boughtOn: '' }, '2026-11-09').errors.boughtOn).toMatch(/Pick/)
    expect(buildPatch(base, { ...f, price: 'x' }, '2026-11-09').errors.price).toMatch(/number above 0/)
    expect(buildPatch(base, { ...f, quantity: '0' }, '2026-11-09').errors.quantity).toMatch(/shares/)
    expect(buildPatch(base, { ...f, boughtOn: '2026-11-05' }, '2026-11-09').patch).toEqual({ bought_on: '2026-11-05' })
  })

  it('does not re-send an old buy date that was not edited', () => {
    const old = item('KEI', 'ok', { bought_on: '2026-01-02' })
    const r = buildPatch(old, { ...formFromItem(old), quantity: '4' }, '2026-11-09')
    expect(r.errors).toEqual({})
    expect(r.patch).toEqual({ quantity: 4 })
  })
})
