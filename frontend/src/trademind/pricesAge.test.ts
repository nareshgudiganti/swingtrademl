import { describe, expect, it } from 'vitest'

import { dayLabel, istToday, pricesAge } from './pricesAge'

// October 2026: Fri 2 Oct is a holiday (Gandhi Jayanti). Trading days below are what GET /market/session sends,
// newest first.
const BEFORE_MON_CLOSE = ['2026-10-16', '2026-10-15', '2026-10-14', '2026-10-13', '2026-10-12']
const AFTER_MON_CLOSE = ['2026-10-19', ...BEFORE_MON_CLOSE]

describe('pricesAge — how old the prices are, in trading days', () => {
  it('Monday morning showing Friday’s close is up to date', () => {
    const a = pricesAge({ latestCandleDate: '2026-10-16', today: '2026-10-19', recentClosedTradingDays: BEFORE_MON_CLOSE })
    expect(a).toMatchObject({ tone: 'fresh', days: 0, label: 'Prices from the Fri 16 Oct close', short: 'Prices: 16 Oct' })
  })

  it('says yesterday’s close in words on a Tuesday morning', () => {
    const a = pricesAge({ latestCandleDate: '2026-10-19', today: '2026-10-20', recentClosedTradingDays: AFTER_MON_CLOSE })
    expect(a).toMatchObject({ tone: 'fresh', days: 0, label: "Prices from yesterday's close" })
  })

  it('after 15:40 on a trading day, the previous close is 1 day old but not amber (today’s arrives overnight)', () => {
    const a = pricesAge({ latestCandleDate: '2026-10-16', today: '2026-10-19', recentClosedTradingDays: AFTER_MON_CLOSE })
    expect(a).toMatchObject({ tone: 'fresh', days: 1, label: 'Prices are 1 day old', short: '1 day old' })
    expect(a.detail).toContain('arrive overnight')
  })

  it('Tuesday morning still on Friday’s close is stale (Monday finished without new prices)', () => {
    const a = pricesAge({ latestCandleDate: '2026-10-16', today: '2026-10-20', recentClosedTradingDays: AFTER_MON_CLOSE })
    expect(a).toMatchObject({ tone: 'stale', days: 1 })
  })

  it('counts two missed trading days in amber', () => {
    const a = pricesAge({ latestCandleDate: '2026-10-14', today: '2026-10-19', recentClosedTradingDays: BEFORE_MON_CLOSE })
    expect(a).toMatchObject({ tone: 'stale', days: 2, label: 'Prices are 2 days old', short: '2 days old' })
    expect(a.detail).toContain('Wed 14 Oct')
  })

  it('skips holidays: Thu 1 Oct is fresh on Mon 5 Oct morning because Fri 2 Oct was a holiday', () => {
    const a = pricesAge({ latestCandleDate: '2026-10-01', today: '2026-10-05', recentClosedTradingDays: ['2026-10-01', '2026-09-30'] })
    expect(a).toMatchObject({ tone: 'fresh', days: 0 })
  })

  it('prices older than the whole calendar list show the date instead of a count', () => {
    const a = pricesAge({ latestCandleDate: '2026-09-01', today: '2026-10-19', recentClosedTradingDays: BEFORE_MON_CLOSE })
    expect(a).toMatchObject({ tone: 'stale', label: 'Prices last updated Tue 1 Sep', short: 'Old: 1 Sep' })
  })

  it('no prices at all is amber', () => {
    const a = pricesAge({ latestCandleDate: null, today: '2026-10-19', recentClosedTradingDays: BEFORE_MON_CLOSE })
    expect(a).toMatchObject({ tone: 'stale', days: null, label: 'No prices yet' })
  })

  it('formats dates and India’s today', () => {
    expect(dayLabel('2026-10-16')).toBe('Fri 16 Oct')
    // 19:00 UTC on 18 Oct is already 00:30 on 19 Oct in India.
    expect(istToday(new Date('2026-10-18T19:00:00Z'))).toBe('2026-10-19')
    expect(istToday(new Date('2026-10-18T18:00:00Z'))).toBe('2026-10-18')
  })
})
